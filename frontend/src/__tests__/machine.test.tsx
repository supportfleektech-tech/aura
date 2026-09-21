/* v1.14 machine-room tests — Model Room, Terminal, Feeds, Voice Call overlay. */
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { act, fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { LangProvider } from "../i18n";
import { StoreProvider, useStore } from "../store";
import { CallOverlay, FeedsView, ModelsView, TerminalView, makeRecognizer } from "../views4";

afterEach(() => { vi.unstubAllGlobals(); cleanup(); });

type Call = { url: string; init?: RequestInit };
function mockApi(fx: Record<string, unknown>, opts: { respond?: (c: Call) => unknown | undefined } = {}) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", (async (url: string, init?: RequestInit) => {
    const c: Call = { url, init };
    calls.push(c);
    const key = Object.keys(fx).find((k) => url.startsWith(k));
    let body = key ? fx[key!] : {};
    if (init?.method === "POST" || init?.method === "PUT" || init?.method === "PATCH" || init?.method === "DELETE") {
      body = opts.respond?.(c) ?? body;
    }
    if (typeof body === "string") {
      return { ok: true, json: async () => ({}), text: async () => body };
    }
    return { ok: true, json: async () => body, text: async () => JSON.stringify(body) };
  }) as unknown as typeof fetch);
  return calls;
}

const wrap = (c: React.ReactElement) => render(<LangProvider><StoreProvider>{c}</StoreProvider></LangProvider>);

describe("Model Room", () => {
  it("renders synced models, sets defaults, syncs", async () => {
    const status = { reachable: true, base_url: "http://localhost:11434", model_count: 2, synced_at: "2026-09-14T09:00:00Z", stale: false, error: "", chat_model: "llama3.1:8b", vision_model: "llava", embed_model: "", auto_sync: true };
    const models = { reachable: true, base_url: "http://localhost:11434", models: [
      { name: "llama3.1:8b", family: "llama", size_bytes: 4.7e9, size: "4.7 GB", parameter_size: "8B", quantization: "Q4_K_M", modified_at: "", capabilities: ["chat", "tools"], synced_at: "" },
      { name: "nomic-embed-text:latest", family: "nomic-bert", size_bytes: 2.7e8, size: "274 MB", parameter_size: "0.1B", quantization: "", modified_at: "", capabilities: ["embed"], synced_at: "" },
    ] };
    const calls = mockApi({
      "/api/ollama/status": status, "/api/ollama/models": models,
      "/api/cloud/models": { models: [{ id: "free/x", name: "Free X", context_length: 32000, free: true }], cached: true, stale: false, count: 1 },
      "/api/settings": { values: {}, secrets: {}, sources: {} },
      "/api/me": { name: "T", role: "R", location: "L", version: "1.15.0" },
      "/api/dashboard": { priorities: [], counts: {}, projects: [], clients: [], activity: [], notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {} },
      "/api/ollama/sync": { ok: true, models: 2, base_url: "http://localhost:11434" },
      "/api/ollama/default": { ok: true, role: "embed", model: "nomic-embed-text:latest" },
    });
    wrap(<ModelsView />);
    expect(await screen.findByText("llama3.1:8b")).toBeInTheDocument();
    expect(screen.getByText("4.7 GB · 8B Q4_K_M")).toBeInTheDocument();
    expect(screen.getByText("✓ chat")).toBeInTheDocument();
    fireEvent.click(screen.getByText("use for embeddings"));
    await waitFor(() => {
      const post = calls.find((c) => c.url.startsWith("/api/ollama/default"));
      expect(post?.init?.method).toBe("POST");
      expect(JSON.parse(String(post?.init?.body))).toEqual({ role: "embed", model: "nomic-embed-text:latest" });
    });
    fireEvent.click(screen.getByText("Sync models"));
    await waitFor(() => expect(calls.some((c) => c.url.startsWith("/api/ollama/sync"))).toBe(true));
    expect(screen.getByText(/Inventory, not install/)).toBeInTheDocument();
  });

  it("honest empty state when ollama is offline", async () => {
    mockApi({
      "/api/ollama/status": { reachable: false, base_url: "http://localhost:11434", model_count: 0, synced_at: "", stale: false, error: "ConnectError", chat_model: "llama3.1", vision_model: "llava", embed_model: "", auto_sync: true },
      "/api/ollama/models": { reachable: false, base_url: "http://localhost:11434", error: "ConnectError", models: [] },
      "/api/cloud/models": { models: [], cached: false, stale: false, count: 0, error: "offline" },
    });
    wrap(<ModelsView />);
    expect(await screen.findByText("No Ollama reachable")).toBeInTheDocument();
    expect(screen.getByText("ollama offline")).toBeInTheDocument();
  });
});

describe("Terminal", () => {
  const baseFx = (enabled = true) => ({
    "/api/terminal/config": { enabled, cwd: "/home/antony", timeout_s: 30, max_out_kb: 64, allow_dangerous: false },
    "/api/terminal/machines": { machines: [{ name: "local", host: "local", kind: "local" }, { name: "build", host: "ant@10.0.0.5", kind: "ssh", ssh_ready: true }], ssh_available: true },
    "/api/terminal/history": { runs: [
      { id: 3, created_at: "2026-09-14T09:00:00Z", source: "ui", machine: "local", command: "ollama list", cwd: "/home/antony", exit_code: 0, duration_ms: 120, out_kb: 1.2, risk: "safe", status: "ok", note: "" },
      { id: 2, created_at: "2026-09-13T09:00:00Z", source: "chat", machine: "local", command: "rm -rf /", cwd: "/home/antony", exit_code: null, duration_ms: 0, out_kb: 0, risk: "dangerous", status: "denied", note: "footgun" },
    ] },
    "/api/me": { name: "T", role: "R", location: "L", version: "1.15.0" },
    "/api/dashboard": { priorities: [], counts: {}, projects: [], clients: [], activity: [], notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {} },
  });

  it("runs a command and shows output + audit trail", async () => {
    const calls = mockApi({
      ...baseFx(),
      "/api/terminal/exec": { ok: true, exit_code: 0, duration_ms: 8, output: "nothing to commit, working tree clean", machine: "local", cwd: "/home/antony", risk: "safe", truncated: false },
    });
    wrap(<TerminalView />);
    const input = await screen.findByLabelText("terminal command");
    fireEvent.change(input, { target: { value: "git status" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(screen.getByText(/nothing to commit/)).toBeInTheDocument());
    expect(screen.getByTestId("term-meta").textContent).toContain("exit 0");
    const post = calls.find((c) => c.url.startsWith("/api/terminal/exec"));
    expect(JSON.parse(String(post?.init?.body)).command).toBe("git status");
    expect(screen.getAllByText(/ollama list/).length).toBeGreaterThan(0); // audit log row
  });

  it("surfaces refusals loudly", async () => {
    mockApi({
      ...baseFx(),
      "/api/terminal/exec": { ok: false, denied: true, error: "refused — recursive delete of a root/home path" },
    });
    wrap(<TerminalView />);
    const input = await screen.findByLabelText("terminal command");
    fireEvent.change(input, { target: { value: "rm -rf /" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect((await screen.findByTestId("term-meta")).textContent).toContain("refused by safety policy");
  });

  it("respects the disabled switch", async () => {
    mockApi(baseFx(false));
    wrap(<TerminalView />);
    expect(await screen.findByText("Terminal is off")).toBeInTheDocument();
    expect(screen.queryByLabelText("terminal command")).not.toBeInTheDocument();
  });
});

describe("Feeds", () => {
  it("lists feeds + items, follows suggestions, unfollows", async () => {
    const calls = mockApi({
      "/api/feeds": {
        feeds: [{ id: 1, url: "https://hnrss.org/frontpage", title: "Hacker News", last_fetched: "2026-09-14T09:00:00Z", error: "", n_items: 2, n_unread: 1 }],
        items: [
          { id: 10, feed_id: 1, guid: "a", title: "Show AURA: voice fortress", link: "https://x/1", published: "2026-09-14T08:00:00Z", fetched_at: "", read: 0, feed_title: "Hacker News" },
          { id: 9, feed_id: 1, guid: "b", title: "Old item", link: "https://x/2", published: "", fetched_at: "2026-09-13T08:00:00Z", read: 1, feed_title: "Hacker News" },
        ],
      },
      "/api/me": { name: "T", role: "R", location: "L", version: "1.15.0" },
      "/api/dashboard": { priorities: [], counts: {}, projects: [], clients: [], activity: [], notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {} },
    });
    wrap(<FeedsView />);
    expect(await screen.findByText("Show AURA: voice fortress")).toBeInTheDocument();
    expect(screen.getByText("1 unread")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("https://lobste.rs/rss"));
    await waitFor(() => {
      const add = calls.find((c) => c.url.startsWith("/api/feeds") && c.init?.method === "POST");
      expect(JSON.parse(String(add?.init?.body)).url).toBe("https://lobste.rs/rss");
    });
    fireEvent.click(screen.getByText("Unfollow"));
    await waitFor(() => expect(calls.some((c) => c.init?.method === "DELETE")).toBe(true));
  });
});

/* ---------------- voice call overlay ---------------- */
class FakeSR {
  static last: FakeSR | null = null;
  lang = ""; interimResults = false; continuous = false;
  onresult: ((e: { resultIndex: number; results: { length: number; [i: number]: { isFinal: boolean; 0: { transcript: string } } } }) => void) | null = null;
  onerror: ((e: { error: string }) => void) | null = null;
  onend: (() => void) | null = null;
  starts = 0;
  start() { this.starts++; FakeSR.last = this; }
  stop() { this.onend?.(); }
  abort() { /* noop */ }
}

describe("Voice call", () => {
  it("falls back to tap mode without Web Speech", () => {
    expect(makeRecognizer().kind).toBe("tap");
  });

  it("listens, answers via chat stream, and saves the call on hangup", async () => {
    vi.stubGlobal("webkitSpeechRecognition", FakeSR);
    const sse = ["event: plan", 'data: {"intent":"general_ask","domain":"general","steps":[],"session_id":"s9"}', "",
      'event: token\ndata: {"text":"Two priorities today. "}'.replace("\n", "\n"), "",
      "event: result", 'data: {"text":"Two priorities today.","model":"builtin","memories_used":[]}', "",
      "event: done", 'data: {"session_id":"s9"}', "", ""].join("\n");
    let savedBody = "";
    const calls = mockApi({
      "/api/voice/calls": {},
    }, {
      respond: (c) => {
        if (c.url.startsWith("/api/chat/stream")) return "__sse__";
        if (c.url.startsWith("/api/voice/calls")) { savedBody = String(c.init?.body); return { ok: true, id: 5, summary: "Quick sync on priorities.", model: "builtin", call: {} }; }
        return undefined;
      },
    });
    // patch fetch to return the SSE string for chat/stream
    const realFetch = (globalThis as unknown as { fetch: typeof fetch }).fetch;
    vi.stubGlobal("fetch", (async (url: string, init?: RequestInit) => {
      if (url.startsWith("/api/chat/stream")) return { ok: true, body: { getReader: () => { let done = false; return { read: async () => done ? { done: true } : (done = true, { done: false, value: new TextEncoder().encode(sse) }) }; } } };
      return realFetch(url as string, init);
    }) as unknown as typeof fetch);
    void calls;

    function Caller() {
      const { setCall } = useStore();
      return (<>
        <CallOverlay />
        <button onClick={() => setCall(false)} data-testid="close-host">host close</button>
      </>);
    }
    wrap(<Caller />);
    await waitFor(() => expect(FakeSR.last).not.toBeNull());
    expect(screen.getByTestId("call-orb").className).toContain("listening");
    act(() => {
      FakeSR.last!.onresult!({ resultIndex: 0, results: Object.assign([{ isFinal: true, 0: { transcript: "how is my day looking" } }], { length: 1 }) });
    });
    await new Promise((r) => setTimeout(r, 300));
    console.log("CAPTION::", screen.getByTestId("call-caption").textContent, "CALLS::", JSON.stringify(calls.map((c) => c.url)));
    await waitFor(() => expect(screen.getByTestId("call-caption").textContent).toContain("Two priorities today."), { timeout: 2500 });
    fireEvent.click(screen.getByTestId("hangup"));
    await waitFor(() => expect(savedBody).toContain("how is my day looking"));
    expect(savedBody).toContain("Two priorities today.");
    expect(screen.getByTestId("call-summary").textContent).toContain("Quick sync on priorities.");
  });
});
