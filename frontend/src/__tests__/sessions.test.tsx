import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { LangProvider } from "../i18n";
import { StoreProvider } from "../store";
import { SessionsView } from "../views3";

afterEach(() => vi.unstubAllGlobals());

const DASH = {
  priorities: [], counts: {}, projects: [], clients: [], activity: [],
  notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {},
};
const SETTINGS = {
  values: {
    onboarded: true, timezone: "Africa/Nairobi", domain_career: true,
    domain_clients: true, domain_personal: true, memory_auto_store: true,
    cloud_memory_policy: "strict", privacy: "local-first", cloud_provider: "openrouter",
    quiet_start: "", quiet_end: "",
  },
  secrets: {}, sources: {},
};
const SESS = [
  { id: "aaa", title: "Plan Q3", domain: "general", created_at: "", updated_at: "", pinned: 0, starred: 1, has_summary: 1, n: 34 },
  { id: "bbb", title: "Groceries", domain: "personal", created_at: "", updated_at: "", pinned: 0, starred: 0, has_summary: 0, n: 4 },
];

function mockFetch() {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method || "GET"} ${url}`);
    const u = String(url);
    if (u.includes("/api/sessions") && (!init || !init.method || init.method === "GET") && !u.includes("/sessions/")) {
      return { ok: true, json: async () => ({ sessions: SESS }) } as Response;
    }
    if (u.endsWith("/pin") && init?.method === "POST") return { ok: true, json: async () => ({ pinned: true }) } as Response;
    if (u.endsWith("/compact") && init?.method === "POST") {
      return { ok: true, json: async () => ({ compacted: true, chunk: 22, summary: "Topic: x" }) } as Response;
    }
    if (init?.method === "DELETE") return { ok: true, json: async () => ({ ok: true }) } as Response;
    const fx: Record<string, unknown> = {
      "/api/me": { name: "T", role: "R", location: "L", version: "1.15.0" },
      "/api/dashboard": DASH,
      "/api/health": { ok: true, services: [], metrics: {} },
      "/api/approvals": { approvals: [] },
      "/api/settings": SETTINGS,
    };
    for (const [k, v] of Object.entries(fx)) {
      if (u.endsWith(k)) return { ok: true, json: async () => v } as Response;
    }
    return { ok: true, json: async () => ({}) } as Response;
  }));
  return calls;
}

describe("SessionsView", () => {
  it("lists sessions with badges and fires pin + compact", async () => {
    const calls = mockFetch();
    const { unmount } = render(<LangProvider><StoreProvider><SessionsView /></StoreProvider></LangProvider>);
    await waitFor(() => expect(screen.getByText("★ Plan Q3")).toBeTruthy());
    expect(screen.getByText(/34 msgs · general · summarized/)).toBeTruthy();
    fireEvent.click(screen.getAllByTitle("Pin")[0]);
    await waitFor(() => expect(calls.some((c) => c.includes("/sessions/aaa/pin"))).toBe(true));
    fireEvent.click(screen.getAllByTitle("Compact now")[0]);
    await waitFor(() => expect(calls.some((c) => c.includes("/sessions/aaa/compact"))).toBe(true));
    unmount();
  });

  it("deletes after confirm", async () => {
    const calls = mockFetch();
    vi.stubGlobal("confirm", () => true);
    const { unmount } = render(<LangProvider><StoreProvider><SessionsView /></StoreProvider></LangProvider>);
    await waitFor(() => expect(screen.getByText("Groceries")).toBeTruthy());
    fireEvent.click(screen.getAllByTitle("Delete")[1]);
    await waitFor(() => expect(calls.some((c) => c.startsWith("DELETE") && c.includes("/sessions/bbb"))).toBe(true));
    unmount();
  });
});
