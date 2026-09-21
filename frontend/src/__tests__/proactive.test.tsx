import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { LangProvider } from "../i18n";
import { StoreProvider } from "../store";
import { OpportunitiesCard } from "../home";

const OPPS = {
  opportunities: [
    { key: "stale_client:1", type: "stale_client", title: "Acme hasn't been touched in 30 days", detail: "d", reasons: ["No contact in 30 days"], importance: 0.6, urgency: 0.4, confidence: 0.7, disruption: 0.15, score: 0.16, ref: "client:1", action: { kind: "create_task", label: "Add check-in task" } },
    { key: "deadline_risk:2", type: "deadline_risk", title: "Task due soon", detail: "d", reasons: ["Due within 2 days"], importance: 0.85, urgency: 0.7, confidence: 0.95, disruption: 0.15, score: 0.52, ref: "task:2", action: { kind: "draft", label: "Draft nudge", text: "Hi there — following up!" } },
  ],
};
const DASH = {
  priorities: [], counts: {}, projects: [], clients: [], activity: [],
  notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {},
};

describe("OpportunitiesCard", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const u = String(url);
      if (u === "/api/me") return { ok: true, json: async () => ({ name: "T", role: "R", location: "L", version: "1.15.0" }) } as Response;
      if (u === "/api/dashboard") return { ok: true, json: async () => DASH } as Response;
      if (u === "/api/settings") return { ok: true, json: async () => ({ values: {}, secrets: {}, sources: {} }) } as Response;
      if (u.startsWith("/api/proactive/resolved")) return { ok: true, json: async () => ({ resolved: [] }) } as Response;
      if (u.includes("/proactive/") && u.endsWith("/act") && init?.method === "POST")
        return { ok: true, json: async () => ({ ok: true, kind: "draft", action: { kind: "draft", text: "Hi there — following up!" } }) } as Response;
      if (u.includes("/proactive/") && u.endsWith("/snooze")) return { ok: true, json: async () => ({ ok: true }) } as Response;
      if (u.includes("/proactive") && (!init || !init.method || init.method === "GET"))
        return { ok: true, json: async () => OPPS } as Response;
      if (init?.method === "PATCH") return { ok: true, json: async () => ({ ok: true }) } as Response;
      return { ok: true, json: async () => ({}) } as Response;
    }));
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const wrap = () => render(<LangProvider><StoreProvider><OpportunitiesCard /></StoreProvider></LangProvider>);

  it("renders opportunities with reasons", async () => {
    const { unmount } = wrap();
    await waitFor(() => expect(screen.getByText("Worth a look")).toBeTruthy());
    expect(screen.getByText("Acme hasn't been touched in 30 days")).toBeTruthy();
    expect(screen.getByText("No contact in 30 days")).toBeTruthy();
    expect(screen.getByText("Task due soon")).toBeTruthy();
    unmount();
  });

  it("dismissing removes the card row and PATCHes the backend", async () => {
    const { unmount } = wrap();
    await waitFor(() => expect(screen.getByText("Task due soon")).toBeTruthy());
    const btns = screen.getAllByTitle("Dismiss");
    fireEvent.click(btns[0]);
    await waitFor(() => expect(screen.queryByText("Acme hasn't been touched in 30 days")).toBeNull());
    expect(screen.getByText("Task due soon")).toBeTruthy();
    const patched = (fetch as ReturnType<typeof vi.fn>).mock.calls.some(
      ([u, i]: [string, RequestInit]) => String(u).includes("/proactive/stale_client") && i?.method === "PATCH"
    );
    expect(patched).toBe(true);
    unmount();
  });

  it("renders nothing when there are no opportunities", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string, init?: RequestInit) => {
      if (String(url).includes("/proactive") && (!init || !init.method || init.method === "GET"))
        return { ok: true, json: async () => ({ opportunities: [] }) } as Response;
      return { ok: true, json: async () => ({}) } as Response;
    });
    const { container, unmount } = wrap();
    await waitFor(() => expect((fetch as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(0));
    await new Promise((r) => setTimeout(r, 50));
    expect(container.innerHTML).toBe("");
    unmount();
  });

  it("act shows the draft, snooze removes the row", async () => {
    const { unmount } = wrap();
    await waitFor(() => expect(screen.getByText("Task due soon")).toBeTruthy());
    fireEvent.click(screen.getByTitle("Draft nudge"));
    await waitFor(() => expect(screen.getByText("Hi there — following up!")).toBeTruthy());
    expect(screen.getByText("Copy")).toBeTruthy();
    const snoozes = screen.getAllByTitle("Snooze 24h");
    fireEvent.click(snoozes[0]);
    await waitFor(() => expect(screen.queryByText("Acme hasn't been touched in 30 days")).toBeNull());
    const snoozed = (fetch as ReturnType<typeof vi.fn>).mock.calls.some(
      ([u, i]: [string, RequestInit]) => String(u).includes("/snooze") && i?.method === "POST"
    );
    expect(snoozed).toBe(true);
    unmount();
  });

  it("mission action creates a scheduled mission and resolves the row", async () => {
    const opp = {
      opportunities: [
        { key: "repeat:9", type: "repeated_manual", title: "Repeated chore", detail: "d", reasons: ["Created 3× in 30 days"], importance: 0.5, urgency: 0.3, confidence: 0.7, disruption: 0.1, score: 0.11, ref: "task:9", action: { kind: "mission", label: "Automate as mission", goal: "Automate chore", every: "weekly" } },
      ],
    };
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string, init?: RequestInit) => {
      const u = String(url);
      if (u === "/api/me") return { ok: true, json: async () => ({ name: "T", role: "R", location: "L", version: "1.15.0" }) } as Response;
      if (u === "/api/dashboard") return { ok: true, json: async () => DASH } as Response;
      if (u === "/api/settings") return { ok: true, json: async () => ({ values: {}, secrets: {}, sources: {} }) } as Response;
      if (u.includes("/proactive/") && u.endsWith("/act"))
        return { ok: true, json: async () => ({ ok: true, kind: "mission", mission: { id: 5, goal: "Automate chore", status: "running" } }) } as Response;
      if (u.includes("/proactive") && (!init || !init.method || init.method === "GET"))
        return { ok: true, json: async () => opp } as Response;
      return { ok: true, json: async () => ({}) } as Response;
    });
    const { unmount } = wrap();
    await waitFor(() => expect(screen.getByText("Repeated chore")).toBeTruthy());
    fireEvent.click(screen.getByTitle("Automate as mission"));
    await waitFor(() => expect(screen.queryByText("Repeated chore")).toBeNull());
    unmount();
  });
});
