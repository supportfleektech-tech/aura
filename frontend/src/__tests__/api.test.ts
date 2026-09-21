// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, chatStream } from "../api";
import viteConfig from "../../vite.config";

afterEach(() => vi.unstubAllGlobals());

const mockFetch = (ok: boolean, body: unknown, status = 200) =>
  vi.stubGlobal("fetch", vi.fn(async () => ({
    ok, status, statusText: ok ? "OK" : "ERR",
    json: async () => body,
    text: async () => JSON.stringify(body),
  })) as unknown as typeof fetch);

describe("api client", () => {
  it("throws a readable error on !ok", async () => {
    mockFetch(false, { detail: "nope" });
    await expect(api.me.get()).rejects.toThrow("API 200");
  });
  it("keeps the browser origin aligned when proxying local API requests", () => {
    const proxy = (viteConfig as {
      server: { proxy: Record<string, { changeOrigin: boolean }> };
    }).server.proxy["/api"];
    expect(proxy.changeOrigin).toBe(false);
  });
  it("patches identity via me.update", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => ({ name: "T" }), text: async () => "" }));
    vi.stubGlobal("fetch", f as unknown as typeof fetch);
    await api.me.update({ name: "T" });
    expect(f).toHaveBeenCalledWith(
      "/api/me",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ name: "T" }) })
    );
  });
  it("posts JSON bodies", async () => {
    const f = vi.fn(async () => ({ ok: true, json: async () => ({ ok: true }), text: async () => "" }));
    vi.stubGlobal("fetch", f as unknown as typeof fetch);
    await api.personal.sleep({ hours: 7 });
    expect(f).toHaveBeenCalledWith(
      "/api/personal/sleep",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ hours: 7 }) })
    );
  });
  it("gets typed resources", async () => {
    mockFetch(true, { automations: [] });
    await expect(api.automations.list()).resolves.toEqual({ automations: [] });
  });
  it("forwards speech cancellation and does not allocate a URL after abort", async () => {
    const controller = new AbortController();
    const f = vi.fn(async () => ({ ok: true, blob: async () => { controller.abort(); return new Blob(["audio"]); } }));
    vi.stubGlobal("fetch", f);
    await expect(api.voice.speakUrl("hello", {}, controller.signal)).rejects.toMatchObject({ name: "AbortError" });
    expect(f).toHaveBeenCalledWith("/api/voice/speak", expect.objectContaining({ signal: controller.signal }));
  });
  it("cancels a pending stream reader and releases its lock without callbacks", async () => {
    const controller = new AbortController();
    const cancel = vi.fn();
    const stream = new ReadableStream({ cancel });
    const f = vi.fn(async () => ({ ok: true, body: stream }));
    vi.stubGlobal("fetch", f);
    const onDone = vi.fn();
    const pending = chatStream("hi", null, { onDone }, [], controller.signal);
    await Promise.resolve();
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
    expect(cancel).toHaveBeenCalled();
    expect(stream.locked).toBe(false);
    expect(onDone).not.toHaveBeenCalled();
    expect(f).toHaveBeenCalledWith("/api/chat/stream", expect.objectContaining({ signal: controller.signal }));
  });
  it("releases the reader on normal completion", async () => {
    const stream = new ReadableStream({ start(c) { c.close(); } });
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, body: stream })));
    await chatStream("hi", null, {});
    expect(stream.locked).toBe(false);
  });
  it("parses vision SSE events", async () => {
    const sse = 'event: vision\ndata: {"file":"a.png","status":"analyzing"}\n\n'
      + 'event: vision\ndata: {"file":"a.png","status":"done","model":"ollama/llava"}\n\n'
      + 'event: done\ndata: {"session_id":"s"}\n\n';
    const stream = new ReadableStream({
      start(c) { c.enqueue(new TextEncoder().encode(sse)); c.close(); },
    });
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, body: stream })) as unknown as typeof fetch);
    const seen: unknown[] = [];
    await chatStream("hi", null, { onVision: (v) => seen.push(v) });
    expect(seen).toEqual([
      { file: "a.png", status: "analyzing" },
      { file: "a.png", status: "done", model: "ollama/llava" },
    ]);
  });
});
