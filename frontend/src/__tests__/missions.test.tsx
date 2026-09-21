/* MissionsPanel smoke tests. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { LangProvider } from "../i18n";
import { StoreProvider } from "../store";
import { MissionsPanel } from "../views2";

afterEach(() => { vi.unstubAllGlobals(); cleanup(); });

const DASH = {
  priorities: [], counts: {}, projects: [], clients: [], activity: [],
  notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {},
};
const MS = {
  missions: [
    { id: 1, goal: "plan my day", status: "draft", step_idx: 0, needs_review: false, result: "", created_at: "2026-09-09T10:00:00+00:00", steps: [{ kind: "tool", label: "Find overdue tasks", tool: "tasks.overdue", status: "pending" }] },
    { id: 2, goal: "follow up", status: "awaiting", step_idx: 1, needs_review: false, result: "", created_at: "2026-09-09T10:00:00+00:00", steps: [{ kind: "tool", label: "Draft follow-ups", tool: "comms.draft_followups", status: "done" }, { kind: "send_drafts", label: "Send drafts", status: "awaiting", approval_id: 7 }] },
  ],
};
const PLAN = { id: 3, goal: "backup", status: "draft", steps: [{ kind: "tool", label: "Run backup", tool: "system.backup", status: "pending" }], needs_review: false, message: "Planned 'backup_check' — 2 steps." };

function mockApi() {
  const spy = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url);
    let body: unknown = {};
    if (u === "/api/me") body = { name: "T", role: "R", location: "L", version: "1.15.0" };
    else if (u === "/api/dashboard") body = DASH;
    else if (u === "/api/missions" && init?.method === "POST") body = PLAN;
    else if (u === "/api/missions") body = MS;
    else if (/\/api\/missions\/\d+\/control/.test(u)) body = {};
    else if (/\/api\/missions\/\d+\/runs/.test(u)) body = { runs: [{ id: 9, mission_id: 1, started_at: "2026-09-09T09:00:00+00:00", finished_at: "2026-09-09T09:01:00+00:00", status: "done", summary: "2 steps done" }] };
    return { ok: true, json: async () => body, text: async () => JSON.stringify(body) };
  });
  vi.stubGlobal("fetch", spy as unknown as typeof fetch);
  return spy;
}
const wrap = () => render(<LangProvider><StoreProvider><MissionsPanel /></StoreProvider></LangProvider>);

describe("MissionsPanel", () => {
  it("renders missions with steps and status", async () => {
    mockApi();
    wrap();
    expect((await screen.findAllByText("plan my day")).length).toBeGreaterThanOrEqual(1);
    expect(await screen.findByText("1. Find overdue tasks")).toBeInTheDocument();
    expect(screen.getAllByText("follow up").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/resolve the approval/)).toBeInTheDocument();
    expect(screen.getByText("Start")).toBeInTheDocument();
  });
  it("plans a mission from the goal box", async () => {
    const spy = mockApi();
    wrap();
    await screen.findByText("plan my day");
    fireEvent.change(screen.getByPlaceholderText(/plan my day/), { target: { value: "backup" } });
    fireEvent.click(screen.getByText("Plan"));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("/api/missions", expect.objectContaining({ method: "POST" })));
  });
  it("AI plan requests the llm planner", async () => {
    const spy = mockApi();
    wrap();
    await screen.findByText("plan my day");
    fireEvent.change(screen.getByPlaceholderText(/plan my day/), { target: { value: "research rivals" } });
    fireEvent.click(screen.getByText("✨ AI plan"));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("/api/missions", expect.objectContaining({ method: "POST", body: expect.stringContaining("llm") })));
  });
  it("starts a draft mission", async () => {
    const spy = mockApi();
    const fetcher = spy.getMockImplementation()!;
    spy.mockImplementation(async (url, init) => url === "/api/tools"
      ? { ok: true, json: async () => ({ tools: [{ name: "tasks.overdue", risk: "R0", description: "Find overdue tasks", category: "tasks" }] }), text: async () => "" }
      : fetcher(url, init));
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
    wrap();
    const start = await screen.findByText("Start");
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    await waitFor(() => expect(spy).toHaveBeenCalledWith("/api/missions/1/control", expect.objectContaining({ method: "POST" })));
  });
  it("shows the last run and schedules a repeat", async () => {
    const spy = mockApi();
    wrap();
    const runs = await screen.findAllByText(/last run: done/);
    expect(runs.length).toBeGreaterThanOrEqual(1);
    fireEvent.change(screen.getAllByLabelText("repeat schedule")[0], { target: { value: "daily" } });
    await waitFor(() => expect(spy).toHaveBeenCalledWith("/api/missions/1/schedule", expect.objectContaining({ method: "POST", body: expect.stringContaining("daily") })));
  });
});
