import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadUiPrefs, saveUiPrefs, setServerCache } from "../prefs";
import { createApprovalAlerts, inQuietHours, playAlertSound } from "../alerts";
import { createElement } from "react";
import { act, cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { api, chatStream } from "../api";
import { StoreProvider, useStore } from "../store";
import { BrowserAlertSettings } from "../views2";

vi.mock("../api", async (original) => ({ ...await original<typeof import("../api")>(), chatStream: vi.fn() }));

beforeEach(() => {
  setServerCache({ quiet_start: "", quiet_end: "", timezone: "Africa/Nairobi" });
  vi.stubGlobal("AudioContext", undefined);
  vi.stubGlobal("webkitAudioContext", undefined);
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function notificationBrowser(permission: NotificationPermission = "granted", hidden = true) {
  const delivered: { title: string; options?: NotificationOptions }[] = [];
  class FakeNotification {
    static permission = permission;
    static requestPermission = vi.fn();
    constructor(title: string, options?: NotificationOptions) { delivered.push({ title, options }); }
  }
  vi.stubGlobal("Notification", FakeNotification);
  vi.spyOn(document, "hidden", "get").mockReturnValue(hidden);
  return { delivered, request: FakeNotification.requestPermission };
}

function audioBrowser(state: AudioContextState = "running", resume = () => Promise.resolve()) {
  const oscillator = { connect: vi.fn(), disconnect: vi.fn(), start: vi.fn(), stop: vi.fn(), frequency: { value: 0 }, onended: null as (() => void) | null };
  const gain = { connect: vi.fn(), disconnect: vi.fn(), gain: { setValueAtTime: vi.fn(), exponentialRampToValueAtTime: vi.fn() } };
  const close = vi.fn().mockResolvedValue(undefined);
  class FakeAudioContext {
    state = state;
    currentTime = 0;
    destination = {};
    resume = resume;
    close = close;
    createOscillator = () => oscillator;
    createGain = () => gain;
  }
  vi.stubGlobal("AudioContext", FakeAudioContext);
  return { oscillator, gain, close };
}

describe("quiet hours", () => {
  it.each([
    ["2026-09-17T18:59:00Z", false],
    ["2026-09-17T19:00:00Z", true],
    ["2026-09-17T21:00:00Z", true],
    ["2026-09-18T03:59:00Z", true],
    ["2026-09-18T04:00:00Z", false],
  ])("uses the cached timezone across midnight at %s", (date, expected) => {
    setServerCache({ quiet_start: "22:00", quiet_end: "07:00" });
    expect(inQuietHours(new Date(date))).toBe(expected);
  });

  it("handles daytime, equal and unset boundaries", () => {
    const now = new Date("2026-09-17T09:00:00Z");
    setServerCache({ quiet_start: "09:00", quiet_end: "17:00" });
    expect(inQuietHours(now)).toBe(true);
    setServerCache({ quiet_end: "09:00" });
    expect(inQuietHours(now)).toBe(false);
    setServerCache({ quiet_end: "" });
    expect(inQuietHours(now)).toBe(false);
  });
});

describe("approval alerts", () => {
  it("does nothing by default", () => {
    const browser = notificationBrowser();
    createApprovalAlerts()([1]);
    expect(browser.delivered).toEqual([]);
    expect(browser.request).not.toHaveBeenCalled();
  });

  it.each(["denied", "default"] as const)("never requests %s permission", (permission) => {
    saveUiPrefs({ ...loadUiPrefs(), desktopApprovalAlerts: true });
    const browser = notificationBrowser(permission);
    createApprovalAlerts()([1]);
    expect(browser.delivered).toEqual([]);
    expect(browser.request).not.toHaveBeenCalled();
  });

  it("handles missing Notification support and visible pages", () => {
    saveUiPrefs({ ...loadUiPrefs(), desktopApprovalAlerts: true });
    vi.stubGlobal("Notification", undefined);
    expect(() => createApprovalAlerts()([1])).not.toThrow();
    const browser = notificationBrowser("granted", false);
    createApprovalAlerts()([2]);
    expect(browser.delivered).toEqual([]);
  });

  it("deduplicates IDs across refresh and stream including equal-count replacements", () => {
    saveUiPrefs({ ...loadUiPrefs(), desktopApprovalAlerts: true });
    const browser = notificationBrowser();
    const update = createApprovalAlerts();
    update([1]);
    update([1, 1]);
    update([2]);
    update([]);
    update([1, 2]);
    expect(browser.delivered).toEqual(Array.from({ length: 2 }, () => ({
      title: "AURA approval needed",
      options: { body: "Open AURA to review pending approvals.", tag: "aura-approval", silent: true },
    })));
  });

  it("suppresses sound and desktop alerts during quiet hours without replay", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-17T21:00:00Z"));
    setServerCache({ quiet_start: "22:00", quiet_end: "07:00" });
    saveUiPrefs({ ...loadUiPrefs(), alertSound: true, desktopApprovalAlerts: true });
    const browser = notificationBrowser();
    const audio = audioBrowser();
    const update = createApprovalAlerts();
    update([1]);
    expect(await playAlertSound()).toBe(false);
    expect(audio.oscillator.start).not.toHaveBeenCalled();
    vi.setSystemTime(new Date("2026-09-18T09:00:00Z"));
    update([1]);
    expect(browser.delivered).toEqual([]);
  });

  it("contains notification constructor failures", () => {
    saveUiPrefs({ ...loadUiPrefs(), desktopApprovalAlerts: true });
    notificationBrowser();
    vi.stubGlobal("Notification", class {
      static permission = "granted";
      constructor() { throw new Error("unsupported"); }
    });
    expect(() => createApprovalAlerts()([1])).not.toThrow();
  });
});

describe("alert sound", () => {
  it("is opt-in but allows an explicit preview", async () => {
    const audio = audioBrowser();
    expect(await playAlertSound()).toBe(false);
    expect(audio.oscillator.start).not.toHaveBeenCalled();
    expect(await playAlertSound(true)).toBe(true);
    audio.oscillator.onended?.();
    expect(audio.close).toHaveBeenCalledTimes(1);
    expect(audio.oscillator.disconnect).toHaveBeenCalled();
    expect(audio.gain.disconnect).toHaveBeenCalled();
  });

  it("handles unsupported audio", async () => {
    expect(await playAlertSound(true)).toBe(false);
  });

  it("closes after autoplay rejection", async () => {
    const audio = audioBrowser("suspended", () => Promise.reject(new Error("blocked")));
    expect(await playAlertSound(true)).toBe(false);
    expect(audio.close).toHaveBeenCalledTimes(1);
  });

  it("closes even when resume never settles", async () => {
    vi.useFakeTimers();
    const audio = audioBrowser("suspended", () => new Promise(() => undefined));
    const result = playAlertSound(true);
    await vi.advanceTimersByTimeAsync(2000);
    expect(await result).toBe(false);
    expect(audio.close).toHaveBeenCalledTimes(1);
  });

  it("cleans up if an ended event never arrives", async () => {
    vi.useFakeTimers();
    const audio = audioBrowser();
    expect(await playAlertSound(true)).toBe(true);
    await vi.advanceTimersByTimeAsync(2000);
    expect(audio.close).toHaveBeenCalledTimes(1);
  });
});

describe("store alert wiring", () => {
  beforeEach(() => {
    vi.spyOn(api.me, "get").mockResolvedValue({} as Awaited<ReturnType<typeof api.me.get>>);
    vi.spyOn(api, "dashboard").mockResolvedValue({} as Awaited<ReturnType<typeof api.dashboard>>);
    vi.spyOn(api, "health").mockResolvedValue({ services: [] } as unknown as Awaited<ReturnType<typeof api.health>>);
    vi.spyOn(api.approvals, "list").mockResolvedValue({ approvals: [] });
    vi.spyOn(api.settings, "get").mockResolvedValue({ values: {}, secrets: {}, sources: {} } as Awaited<ReturnType<typeof api.settings.get>>);
  });

  it("shares ID deduplication between polling, onApproval and results", async () => {
    saveUiPrefs({ ...loadUiPrefs(), desktopApprovalAlerts: true });
    const browser = notificationBrowser();
    const { result } = renderHook(() => useStore(), { wrapper: StoreProvider });
    await act(async () => { await result.current.refresh(); });
    const approval = { id: 7, title: "private message", risk: "R2", drafts: [] };
    vi.mocked(chatStream).mockImplementation(async (_text, _sid, events) => {
      events.onApproval?.(approval);
      events.onApproval?.(approval);
      events.onResult?.({ text: "private result", model: "mock", memories_used: [], approval });
    });
    await act(async () => { await result.current.send("mock input"); });
    vi.mocked(api.approvals.list).mockResolvedValue({ approvals: [approval] } as unknown as Awaited<ReturnType<typeof api.approvals.list>>);
    await act(async () => { await result.current.refresh(); });
    expect(browser.delivered).toHaveLength(1);
    expect(JSON.stringify(browser.delivered)).not.toContain("private");
    expect(result.current.pendingApprovals).toBe(1);
    act(() => result.current.requestComposerFocus());
    expect(result.current.composerFocus).toBe(1);
  });

  it("chimes only for enabled error toasts without creating recursive errors", async () => {
    saveUiPrefs({ ...loadUiPrefs(), alertSound: true });
    const audio = audioBrowser();
    const { result } = renderHook(() => useStore(), { wrapper: StoreProvider });
    await act(async () => { await result.current.refresh(); });
    act(() => result.current.toast("info"));
    expect(audio.oscillator.start).not.toHaveBeenCalled();
    act(() => result.current.toast("error", "error"));
    expect(audio.oscillator.start).toHaveBeenCalledTimes(1);
    audio.oscillator.onended?.();
    vi.stubGlobal("AudioContext", undefined);
    await act(async () => { result.current.toast("unsupported", "error"); });
    expect(result.current.toasts).toHaveLength(3);
  });
});

describe("browser alert settings", () => {
  it("persists labeled opt-ins without requesting permission and explicitly tests sound", async () => {
    const browser = notificationBrowser("denied");
    const audio = audioBrowser();
    render(createElement(BrowserAlertSettings));
    fireEvent.click(screen.getByRole("switch", { name: "Alert sound" }));
    fireEvent.click(screen.getByRole("switch", { name: "Desktop approval alerts" }));
    expect(loadUiPrefs()).toMatchObject({ alertSound: true, desktopApprovalAlerts: true });
    expect(browser.request).not.toHaveBeenCalled();
    expect(audio.oscillator.start).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Test sound" })); });
    expect(audio.oscillator.start).toHaveBeenCalledTimes(1);
    audio.oscillator.onended?.();
  });
});

describe("alert preferences", () => {
  it("defaults both browser alerts off", () => {
    expect(loadUiPrefs()).toMatchObject({ alertSound: false, desktopApprovalAlerts: false });
  });

  it("persists explicit opt-in alongside appearance", () => {
    saveUiPrefs({ ...loadUiPrefs(), alertSound: true, desktopApprovalAlerts: true });
    expect(loadUiPrefs()).toMatchObject({ alertSound: true, desktopApprovalAlerts: true, theme: "dark" });
  });

  it("rejects non-boolean opt-ins", () => {
    localStorage.setItem("aura-ui-prefs", JSON.stringify({ alertSound: "true", desktopApprovalAlerts: 1 }));
    expect(loadUiPrefs()).toMatchObject({ alertSound: false, desktopApprovalAlerts: false });
  });
});
