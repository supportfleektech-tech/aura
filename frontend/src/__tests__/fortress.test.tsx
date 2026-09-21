/* v1.15 fortress tests — Scripts panel, Watch panel, call history, terminal ↑. */
import { afterEach, describe, expect, it, vi } from "vitest";
import React from "react";
import { fireEvent, render, screen, waitFor, cleanup } from "@testing-library/react";
import { LangProvider } from "../i18n";
import { StoreProvider } from "../store";
import { CallHistoryPanel, ScriptsPanel, TerminalView, WatchPanel } from "../views4";

afterEach(() => { vi.unstubAllGlobals(); cleanup(); });

type Call = { url: string; init?: RequestInit };
function mockApi(fx: Record<string, unknown>) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", (async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const key = Object.keys(fx).sort((a, b) => b.length - a.length).find((k) => url.startsWith(k));
    const body = key ? fx[key!] : {};
    if (typeof body === "string") return { ok: true, json: async () => ({}), text: async () => body };
    return { ok: true, json: async () => body, text: async () => JSON.stringify(body) };
  }) as unknown as typeof fetch);
  return calls;
}
const wrap = (c: React.ReactElement) => render(<LangProvider><StoreProvider>{c}</StoreProvider></LangProvider>);

describe("Scripts panel", () => {
  const fx = {
    "/api/scripts": { scripts: [{ id: 3, name: "nightly-sync", command: "rsync -a ~/proj /bak --progress", machine: "local", description: "backup ritual", run_count: 7, last_run: "2026-09-14T01:00:00Z", last_status: "ok", created_at: "" }] },
    "/api/terminal/machines": { machines: [{ name: "local", host: "local", kind: "local" }], ssh_available: true },
    "/api/scripts/3/run": { ok: true, exit_code: 0, duration_ms: 42, output: "sent 512 bytes", script: "nightly-sync" },
    "/api/me": { name: "T", role: "R", location: "L", version: "1.15.0" },
    "/api/dashboard": { priorities: [], counts: {}, projects: [], clients: [], activity: [], notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {} },
  };

  it("lists, runs, and saves scripts", async () => {
    const calls = mockApi(fx);
    wrap(<ScriptsPanel />);
    expect(await screen.findByTestId("script-nightly-sync")).toBeInTheDocument();
    expect(screen.getByText(/ran 7×/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Run"));
    await waitFor(() => expect(screen.getByText(/sent 512 bytes/)).toBeInTheDocument());
    expect(calls.some((c) => c.url === "/api/scripts/3/run" && c.init?.method === "POST")).toBe(true);
    fireEvent.change(screen.getByLabelText("script name"), { target: { value: "new-one" } });
    fireEvent.change(screen.getByLabelText("script command"), { target: { value: "echo hi" } });
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/scripts" && c.init?.method === "POST")).toBe(true));
  });

  it("shows the empty state", async () => {
    mockApi({ ...fx, "/api/scripts": { scripts: [] } });
    wrap(<ScriptsPanel />);
    expect(await screen.findByText("No saved scripts")).toBeInTheDocument();
  });
});

describe("Watch panel", () => {
  const state = {
    enabled: true, ingest: true, interval_s: 120, default_dir: "/data/inbox",
    paths: ["/data/inbox"],
    recent: [{ path: "/data/inbox/report.pdf", size: 120000, mtime: 0, file_id: 12, ingested: 1, last_event: "new 2026-09-14T01:02:03Z" }],
  };
  it("renders state, scans on demand, toggles settings", async () => {
    const calls = mockApi({
      "/api/watch": state,
      "/api/watch/scan": { new: 0, changed: 1, skipped_ext: 0, errors: 0 },
      "/api/watch/reset": { ok: true, cleared: 1 },
      "/api/settings": { values: {}, secrets: {}, sources: {} },
      "/api/me": { name: "T", role: "R", location: "L", version: "1.15.0" },
      "/api/dashboard": { priorities: [], counts: {}, projects: [], clients: [], activity: [], notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {} },
    });
    wrap(<WatchPanel />);
    expect(await screen.findByText(/report.pdf/)).toBeInTheDocument();
    expect(screen.getByText("active · scans every 120s")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Scan now"));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/watch/scan" && c.init?.method === "POST")).toBe(true));
    fireEvent.click(screen.getByLabelText("watch enabled"));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/settings" && c.init?.method === "PATCH")).toBe(true));
    fireEvent.click(screen.getByText("Reset state"));
    await waitFor(() => expect(calls.some((c) => c.url === "/api/watch/reset")).toBe(true));
  });
});

describe("Call history", () => {
  it("lists calls with summaries", async () => {
    mockApi({
      "/api/voice/calls": { calls: [{ id: 9, started_at: "2026-09-14T01:00:00Z", ended_at: "", mode: "browser", seconds: 95, turns: 4, summary: "Quick planning sync.", model: "builtin", source: "ui" }] },
      "/api/me": { name: "T", role: "R", location: "L", version: "1.15.0" },
      "/api/dashboard": { priorities: [], counts: {}, projects: [], clients: [], activity: [], notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {} },
    });
    wrap(<CallHistoryPanel />);
    expect(await screen.findByText(/Quick planning sync./)).toBeInTheDocument();
    expect(screen.getByText(/1:35 · 4 turn\(s\) · browser/)).toBeInTheDocument();
    expect(screen.getByText("Start a call")).toBeInTheDocument();
  });
});

describe("Terminal recall", () => {
  it("ArrowUp walks saved history", async () => {
    mockApi({
      "/api/terminal/config": { enabled: true, cwd: "/home/a", timeout_s: 30, max_out_kb: 64, allow_dangerous: false },
      "/api/terminal/machines": { machines: [{ name: "local", host: "local", kind: "local" }], ssh_available: true },
      "/api/terminal/history": { runs: [{ id: 1, created_at: "2026-09-14T01:00:00Z", source: "ui", machine: "local", command: "ollama list", cwd: "/home/a", exit_code: 0, duration_ms: 9, out_kb: 0.2, risk: "safe", status: "ok", note: "" }] },
      "/api/me": { name: "T", role: "R", location: "L", version: "1.15.0" },
      "/api/dashboard": { priorities: [], counts: {}, projects: [], clients: [], activity: [], notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {} },
    });
    wrap(<TerminalView />);
    const input = await screen.findByLabelText("terminal command");
    fireEvent.keyDown(input, { key: "ArrowUp" });
    await waitFor(() => expect((input as HTMLInputElement).value).toBe("ollama list"));
    fireEvent.keyDown(input, { key: "ArrowDown" });
    await waitFor(() => expect((input as HTMLInputElement).value).toBe(""));
  });
});
