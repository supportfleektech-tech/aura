import { readFileSync } from "fs";
import { join } from "path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api";
import { pushSupported, urlBase64ToUint8Array } from "../push";

afterEach(() => vi.unstubAllGlobals());

describe("push helpers", () => {
  it("decodes urlsafe base64", () => {
    expect(Array.from(urlBase64ToUint8Array("SGVsbG8"))).toEqual([72, 101, 108, 108, 111]);
  });
  it("detects support without throwing", () => {
    expect(typeof pushSupported()).toBe("boolean");
  });
  it("calls push endpoints", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => ({ key: null, configured: false }), text: async () => "" }));
    vi.stubGlobal("fetch", f as unknown as typeof fetch);
    await api.push.vapidKey();
    expect(f).toHaveBeenCalledWith("/api/push/vapid-public-key", expect.anything());
    await api.push.test({ title: "t" });
    expect(f).toHaveBeenCalledWith("/api/push/test", expect.objectContaining({ method: "POST" }));
  });
});

describe("PWA assets", () => {
  it("manifest is valid with maskable icon", () => {
    const m = JSON.parse(readFileSync(join(__dirname, "..", "..", "public", "manifest.webmanifest"), "utf8"));
    expect(m.short_name).toBe("AURA");
    expect(m.start_url).toBe("/");
    expect(m.display).toBe("standalone");
    expect(m.icons.some((i: { purpose: string }) => String(i.purpose).includes("maskable"))).toBe(true);
    for (const i of m.icons) expect(i.src).toMatch(/^\/icons\/icon-\d+\.png$/);
  });
  it("icons exist", () => {
    for (const n of [192, 512]) {
      const p = join(__dirname, "..", "..", "public", "icons", `icon-${n}.png`);
      expect(readFileSync(p).length).toBeGreaterThan(500);
    }
  });
  it("service worker handles push + fetch", () => {
    const sw = readFileSync(join(__dirname, "..", "..", "public", "sw.js"), "utf8");
    for (const s of ['addEventListener("push"', 'addEventListener("fetch"', 'addEventListener("notificationclick"', "/api/"]) {
      expect(sw).toContain(s);
    }
  });
});
