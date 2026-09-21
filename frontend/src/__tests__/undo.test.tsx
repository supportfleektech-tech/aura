import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { LangProvider } from "../i18n";
import { StoreProvider } from "../store";
import { UndoButton } from "../ui";

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

function mockFetch(undoGets: unknown[]) {
  let n = 0;
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method || "GET"} ${url}`);
    const u = String(url);
    if (u.endsWith("/api/undo") && (!init || !init.method || init.method === "GET")) {
      return { ok: true, json: async () => undoGets[Math.min(n++, undoGets.length - 1)] } as Response;
    }
    if (u.endsWith("/api/undo") && init?.method === "POST") {
      return { ok: true, json: async () => ({ undone: [{ id: 9, summary: "tasks#3 x", result: "removed tasks#3" }], remaining: 0 }) } as Response;
    }
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

function renderBtn(watch: unknown = 0) {
  return render(<LangProvider><StoreProvider><UndoButton watch={watch} /></StoreProvider></LangProvider>);
}

describe("UndoButton", () => {
  it("appears with the last-change summary and undoes on click", async () => {
    const calls = mockFetch([
      { journal: [{ id: 9, summary: "tasks#3 Buy milk" }], undoable: true },
      { journal: [], undoable: false },
    ]);
    const { container, unmount } = renderBtn();
    const btn = await screen.findByTitle("Undo last change: tasks#3 Buy milk");
    expect(btn).toBeTruthy();
    fireEvent.click(btn);
    await waitFor(() => expect(calls.some((c) => c.startsWith("POST") && c.includes("/api/undo"))).toBe(true));
    await waitFor(() => expect(container.innerHTML).toBe(""));
    unmount();
  });

  it("stays hidden when nothing is undoable", async () => {
    mockFetch([{ journal: [], undoable: false }]);
    const { container, unmount } = renderBtn();
    await waitFor(() => expect(container.innerHTML).toBe(""));
    expect(container.innerHTML).toBe("");
    unmount();
  });
});
