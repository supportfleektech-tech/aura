import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LangProvider } from "../i18n";
import { StoreProvider } from "../store";
import { MemoryView, MissionsPanel } from "../views2";

const memory = { id: 1, title: "Delivery", content: "BlueKite arrives Monday", source: "conversation", domain: "general", mtype: "semantic", sensitivity: "normal", confidence: 0.8, importance: 0.6, created_at: "2026-09-09T10:00:00Z" };
const mission = { id: 2, goal: "Review delivery", status: "draft", steps: [{ kind: "tool", label: "Read tasks", tool: "tasks.list", args: { status: "open", limit: 17 }, status: "pending" }], step_idx: 0, needs_review: true, result: "", created_at: "2026-09-09T10:00:00Z" };
function setup(options: { failSave?: boolean; awaiting?: boolean; noTools?: boolean } = {}) {
  let current = { ...memory };
  const writes: { url: string; body: unknown }[] = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method && init.method !== "GET") {
      writes.push({ url, body: JSON.parse(String(init.body || "{}")) });
      if (url === "/api/memories/1") {
        if (options.failSave) return { ok: false, status: 503, text: async () => "Unavailable" };
        current = { ...current, content: JSON.parse(String(init.body)).content, source: "user-corrected:conversation" };
      }
    }
    const fixtures: Record<string, unknown> = {
      "/api/me": { name: "T", role: "R", location: "L", version: "1.15.0" },
      "/api/dashboard": { priorities: [], counts: {}, projects: [], clients: [], activity: [], notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {} },
      "/api/health": { ok: true, services: [] },
      "/api/approvals": { approvals: options.awaiting ? [{ id: 7, status: "pending", risk: "R2", title: "Send delivery", created_at: "", detail: { mission_id: 2, kind: "tool", tool: "comms.send", args: { to: "eval@example.test", text: "Delivery confirmed" } } }] : [] },
      "/api/memories?q=": { memories: [current], stats: { total: 1, by_domain: { general: 1 } } },
      "/api/missions": { missions: [options.awaiting ? { ...mission, status: "awaiting", steps: [{ ...mission.steps[0], tool: "comms.send", status: "awaiting", approval_id: 7 }] } : mission] },
      "/api/missions/2/runs": { runs: [] },
      "/api/tools": { tools: options.noTools ? [] : [{ name: "tasks.list", risk: "R0", description: "Read tasks", category: "tasks" }, { name: "comms.send", risk: "R2", description: "Send a message", category: "comms" }] },
    };
    const body = fixtures[url] || {};
    return { ok: true, json: async () => body, text: async () => JSON.stringify(body) };
  });
  vi.stubGlobal("fetch", fetcher);
  return writes;
}
const wrap = (c: React.ReactElement) => render(<LangProvider><StoreProvider>{c}</StoreProvider></LangProvider>);
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("saves a correction through PATCH and shows its retained source", async () => {
  const writes = setup();
  wrap(<MemoryView />);
  fireEvent.click(await screen.findByRole("button", { name: "Correct Delivery" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Corrected content" }), { target: { value: "  RedFinch arrives Friday  " } });
  fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
  await waitFor(() => expect(screen.getByText("RedFinch arrives Friday", { selector: "p" })).toBeInTheDocument());
  expect(screen.getByText(/Corrected by you.*conversation/)).toBeInTheDocument();
  expect(writes).toEqual([{ url: "/api/memories/1", body: { content: "RedFinch arrives Friday" } }]);
});

it("discards cancelled drafts and prevents blank corrections", async () => {
  const writes = setup();
  wrap(<MemoryView />);
  fireEvent.click(await screen.findByRole("button", { name: "Correct Delivery" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Corrected content" }), { target: { value: "Wrong draft" } });
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  fireEvent.click(screen.getByRole("button", { name: "Correct Delivery" }));
  expect(screen.getByRole("textbox", { name: "Corrected content" })).toHaveValue(memory.content);
  fireEvent.change(screen.getByRole("textbox", { name: "Corrected content" }), { target: { value: "   " } });
  expect(screen.getByRole("button", { name: "Save correction" })).toBeDisabled();
  expect(writes).toEqual([]);
});

it("keeps failed corrections editable with an announced error", async () => {
  setup({ failSave: true });
  wrap(<MemoryView />);
  fireEvent.click(await screen.findByRole("button", { name: "Correct Delivery" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Corrected content" }), { target: { value: "RedFinch arrives Friday" } });
  fireEvent.click(screen.getByRole("button", { name: "Save correction" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/Correction failed/);
  expect(screen.getByRole("textbox", { name: "Corrected content" })).toHaveValue("RedFinch arrives Friday");
});

it("shows exact arguments and risk before an explicit mission start confirmation", async () => {
  const writes = setup();
  const confirm = vi.fn().mockReturnValue(false);
  vi.stubGlobal("confirm", confirm);
  wrap(<MissionsPanel />);
  const start = await screen.findByRole("button", { name: "Start" });
  await waitFor(() => expect(start).toBeEnabled());
  expect(screen.getByText(/"limit": 17/)).toHaveTextContent('"status": "open"');
  expect(screen.getByText(/R0.*read-only/)).toBeInTheDocument();
  expect(writes).toEqual([]);
  fireEvent.click(start);
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining('"limit": 17'));
  expect(writes).toEqual([]);
  confirm.mockReturnValue(true);
  fireEvent.click(start);
  await waitFor(() => expect(writes).toEqual([{ url: "/api/missions/2/control", body: { action: "start" } }]));
});

it("does not enable starting when tool risk is unavailable", async () => {
  const writes = setup({ noTools: true });
  wrap(<MissionsPanel />);
  expect(await screen.findByRole("button", { name: "Start" })).toBeDisabled();
  expect(screen.getByText(/Risk unavailable/)).toBeInTheDocument();
  expect(writes).toEqual([]);
});

it("shows the actual pending approval payload without auto-approving", async () => {
  const writes = setup({ awaiting: true });
  wrap(<MissionsPanel />);
  expect(await screen.findByText(/eval@example.test/)).toHaveTextContent("Delivery confirmed");
  expect(screen.getByText(/Approval #7.*R2/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Start" })).not.toBeInTheDocument();
  expect(writes).toEqual([]);
});
