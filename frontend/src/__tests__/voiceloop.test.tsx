/* VoiceLoopPanel smoke tests — off-states only (no mic in jsdom). */
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, cleanup } from "@testing-library/react";
import { LangProvider } from "../i18n";
import { StoreProvider } from "../store";
import { VoiceLoopPanel } from "../views2";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const DASH = {
  priorities: [], counts: {}, projects: [], clients: [], activity: [],
  notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {},
};

function mockApi(loop: unknown) {
  const FX: Record<string, unknown> = {
    "/api/me": { name: "T", role: "R", location: "L", version: "1.15.0" },
    "/api/dashboard": DASH,
    "/api/voice/loop/status": loop,
  };
  vi.stubGlobal("fetch", (async (url: string) => {
    const body = FX[url] ?? {};
    return { ok: true, json: async () => body, text: async () => JSON.stringify(body) };
  }) as unknown as typeof fetch);
}
const wrap = () => render(<LangProvider><StoreProvider><VoiceLoopPanel /></StoreProvider></LangProvider>);

function liveBrowser() {
  mockApi({ whisper: true });
  const track = { stop: vi.fn() };
  const stream = { getTracks: () => [track] };
  const getUserMedia = vi.fn().mockResolvedValue(stream);
  vi.stubGlobal("navigator", { mediaDevices: { getUserMedia } });
  const sockets: Socket[] = [];
  class Socket {
    readyState = 1;
    onopen: (() => Promise<void>) | null = null;
    onmessage: ((e: { data: string | ArrayBuffer }) => void) | null = null;
    onclose: (() => void) | null = null;
    onerror: (() => void) | null = null;
    send = vi.fn();
    close = vi.fn();
    constructor() { sockets.push(this); }
  }
  const ctx = { audioWorklet: { addModule: vi.fn().mockResolvedValue(undefined) }, createMediaStreamSource: () => ({ connect: vi.fn() }), close: vi.fn().mockResolvedValue(undefined) };
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal("AudioContext", class { constructor() { return ctx; } });
  vi.stubGlobal("AudioWorkletNode", class { port = { onmessage: null }; disconnect = vi.fn(); });
  const synth = { speak: vi.fn(), cancel: vi.fn() };
  vi.stubGlobal("speechSynthesis", synth);
  vi.stubGlobal("SpeechSynthesisUtterance", class { constructor(public text: string) {} });
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:loop");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  return { track, stream, getUserMedia, sockets, synth, ctx };
}

async function startLive() {
  const browser = liveBrowser();
  const view = wrap();
  fireEvent.click(await screen.findByText("Start live loop"));
  await act(async () => {});
  await act(async () => browser.sockets[0].onopen?.());
  return { ...browser, ...view };
}

describe("VoiceLoopPanel", () => {
  it.each(["thinking", "speaking"])("offers Stop speaking during %s and rejects late audio", async (state) => {
    const b = await startLive();
    const ws = b.sockets[0];
    const message = ws.onmessage!;
    const audio = vi.fn();
    vi.stubGlobal("Audio", audio);
    act(() => message({ data: JSON.stringify({ t: "state", state }) }));
    fireEvent.click(screen.getByRole("button", { name: "Stop speaking" }));
    expect(ws.send).toHaveBeenCalledWith("stop");
    expect(ws.close).toHaveBeenCalled();
    act(() => message({ data: new ArrayBuffer(2) }));
    expect(audio).not.toHaveBeenCalled();
    expect(screen.getByText("Start live loop")).toBeInTheDocument();
  });
  it("cancels browser fallback and sends stop before closing the socket", async () => {
    const b = await startLive();
    const ws = b.sockets[0];
    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ t: "answer", text: "hello" }) });
      ws.onmessage?.({ data: JSON.stringify({ t: "error", stage: "speak" }) });
    });
    expect(b.synth.speak).toHaveBeenCalledTimes(1);
    const ended = b.synth.speak.mock.calls[0][0].onend;
    b.synth.cancel.mockClear();
    fireEvent.click(screen.getByText("Stop"));
    expect(b.synth.cancel).toHaveBeenCalled();
    expect(ws.send).toHaveBeenCalledWith("stop");
    expect(ws.send.mock.invocationCallOrder[0]).toBeLessThan(ws.close.mock.invocationCallOrder[0]);
    act(() => ended());
    expect(ws.send).not.toHaveBeenCalledWith("played");
    expect(b.track.stop).toHaveBeenCalled();
  });
  it("offers Stop while microphone permission is pending and discards late capture", async () => {
    const b = liveBrowser();
    let resolve!: (stream: unknown) => void;
    b.getUserMedia.mockReturnValue(new Promise((yes) => { resolve = yes; }));
    wrap();
    fireEvent.click(await screen.findByText("Start live loop"));
    const stop = screen.queryByText("Stop");
    expect(stop).not.toBeNull();
    fireEvent.click(stop!);
    await act(async () => resolve(b.stream));
    expect(b.track.stop).toHaveBeenCalled();
    expect(b.sockets).toHaveLength(0);
  });
  it("ignores captured socket callbacks after unmount", async () => {
    const b = await startLive();
    const message = b.sockets[0].onmessage!;
    b.unmount();
    act(() => {
      message({ data: JSON.stringify({ t: "answer", text: "late" }) });
      message({ data: JSON.stringify({ t: "error", stage: "speak" }) });
    });
    expect(b.synth.speak).not.toHaveBeenCalled();
  });
  it("does not fall back to browser speech when old audio play rejects after stop", async () => {
    let reject!: (reason: Error) => void;
    const audio = { play: vi.fn(() => new Promise((_, no) => { reject = no; })), pause: vi.fn(), removeAttribute: vi.fn(), load: vi.fn(), onended: null, onerror: null };
    vi.stubGlobal("Audio", class { constructor() { return audio; } });
    const b = await startLive();
    act(() => {
      b.sockets[0].onmessage?.({ data: JSON.stringify({ t: "answer", text: "hello" }) });
      b.sockets[0].onmessage?.({ data: new ArrayBuffer(2) });
    });
    fireEvent.click(screen.getByText("Stop"));
    await act(async () => reject(new Error("late failure")));
    expect(b.synth.speak).not.toHaveBeenCalled();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:loop");
  });
  it("shows install state when server STT is missing", async () => {
    mockApi({ wake_available: false, wake_model: "hey_jarvis_v0.1", wake_enabled: false, whisper: false, tts: {}, ws: "/api/voice/loop" });
    wrap();
    expect(await screen.findByText("Server voice not installed")).toBeInTheDocument();
  });
  it("offers tap-to-talk when wake word is unavailable", async () => {
    mockApi({ wake_available: false, wake_model: "hey_jarvis_v0.1", wake_enabled: false, whisper: true, tts: {}, ws: "/api/voice/loop" });
    wrap();
    expect(await screen.findByText(/tap Talk and speak/)).toBeInTheDocument();
    expect(screen.getByText("Start live loop")).toBeInTheDocument();
  });
  it("shows the wake phrase when fully enabled", async () => {
    mockApi({ wake_available: true, wake_model: "hey_jarvis_v0.1", wake_enabled: true, whisper: true, tts: {}, ws: "/api/voice/loop" });
    wrap();
    expect(await screen.findByText(/hey jarvis/)).toBeInTheDocument();
  });
});
