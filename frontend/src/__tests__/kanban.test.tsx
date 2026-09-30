import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { KanbanView } from "../views2/kanban";
import { api } from "../api";

vi.mock("../api", () => ({
  api: { board: { get: vi.fn(), move: vi.fn() } },
  ago: (s: string) => s,
}));

const toast = vi.fn();

vi.mock("../store", () => ({
  useStore: () => ({ toast }),
}));

// No auto-cleanup is configured in vitest.config.ts, so unmount explicitly —
// otherwise cards from a previous test stay in the document and every
// getByRole/getByText below matches two elements.
afterEach(() => cleanup());

// jsdom has no DataTransfer constructor, but React's synthetic drag event only
// needs a plain object exposing setData/getData — identity is never compared,
// because onDrop reads the id out of component state, not out of the payload.
function stubDataTransfer() {
  return { setData: vi.fn(), getData: vi.fn(), types: [] as string[], effectAllowed: "", dropEffect: "" };
}

const CARD = { id: 1, goal: "Plan my week", status: "draft", steps_total: 2, steps_done: 0, next_run_at: "", created_at: "", updated_at: "" };
const COLUMNS = [
  { key: "backlog", label: "Backlog", missions: [CARD] },
  { key: "running", label: "Running", missions: [] as typeof CARD[] },
  { key: "awaiting", label: "Needs you", missions: [] as typeof CARD[] },
  { key: "done", label: "Finished", missions: [] as typeof CARD[] },
] as any;

describe("KanbanView", () => {
  beforeEach(() => {
    toast.mockClear();
    (api.board.move as any).mockClear();
    (api.board.get as any).mockResolvedValue({ columns: COLUMNS, counts: { backlog: 1, running: 0, awaiting: 0, done: 0 }, total: 1 });
    (api.board.move as any).mockResolvedValue({ ok: true, mission: { ...CARD, status: "running" } });
  });

  it("renders every column with its cards", async () => {
    render(<KanbanView />);
    await waitFor(() => expect(screen.getByText("Plan my week")).toBeTruthy());
    for (const label of ["Backlog", "Running", "Needs you", "Finished"]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
  });

  it("exposes a start control for a backlog card", async () => {
    render(<KanbanView />);
    await waitFor(() => expect(screen.getByText("Plan my week")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /start/i }));
    await waitFor(() => expect(api.board.move).toHaveBeenCalledWith(1, "running"));
  });

  it("offers no controls on a finished card", async () => {
    (api.board.get as any).mockResolvedValue({
      columns: COLUMNS.map((c: any) => (c.key === "done" ? { ...c, missions: [{ ...CARD, id: 2, goal: "Ship the release", status: "done" }] } : c)),
      counts: { backlog: 1, running: 0, awaiting: 0, done: 1 },
    });
    render(<KanbanView />);
    await waitFor(() => expect(screen.getByText("Plan my week")).toBeTruthy());
    const done = screen.getByLabelText("Finished").closest("section") as HTMLElement;
    expect(done.querySelectorAll("button").length).toBe(0);
  });

  it("surfaces a rejected move as a toast, not a silent no-op", async () => {
    (api.board.move as any).mockRejectedValue(new Error("cannot move a done mission to backlog"));
    render(<KanbanView />);
    await waitFor(() => expect(screen.getByText("Plan my week")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /start/i }));
    await waitFor(() => expect(api.board.move).toHaveBeenCalled());
    await waitFor(() => expect(toast).toHaveBeenCalledWith("cannot move a done mission to backlog", "error"));
  });

  // Regression: onDrop used to resolve the dragged card with
  // `c.missions.find(...)` where `c` is the *target* column, so a card dragged
  // to another column resolved to undefined and no move was ever issued. The
  // bug shipped because only the button path was covered.
  it("moves a card onto the column it is dropped on", async () => {
    render(<KanbanView />);
    await waitFor(() => expect(screen.getByText("Plan my week")).toBeTruthy());
    const card = screen.getByText("Plan my week").closest(".boardcard") as HTMLElement;
    const dataTransfer = stubDataTransfer();
    fireEvent.dragStart(card, { dataTransfer });
    fireEvent.drop(screen.getByLabelText("Running"), { dataTransfer });
    await waitFor(() => expect(api.board.move).toHaveBeenCalledWith(1, "running"));
    await waitFor(() => expect(toast).toHaveBeenCalledWith("Moved “Plan my week”", "success"));
  });

  it("treats a drop on the card's own column as a no-op, not a fake success", async () => {
    render(<KanbanView />);
    await waitFor(() => expect(screen.getByText("Plan my week")).toBeTruthy());
    const card = screen.getByText("Plan my week").closest(".boardcard") as HTMLElement;
    const dataTransfer = stubDataTransfer();
    fireEvent.dragStart(card, { dataTransfer });
    fireEvent.drop(screen.getByLabelText("Backlog"), { dataTransfer });
    expect(api.board.move).not.toHaveBeenCalled();
    expect(toast).not.toHaveBeenCalled();
  });

  it("reports a rejected drop with the same toast the buttons use", async () => {
    (api.board.move as any).mockRejectedValue(new Error("cannot move a done mission to backlog"));
    render(<KanbanView />);
    await waitFor(() => expect(screen.getByText("Plan my week")).toBeTruthy());
    const card = screen.getByText("Plan my week").closest(".boardcard") as HTMLElement;
    const dataTransfer = stubDataTransfer();
    fireEvent.dragStart(card, { dataTransfer });
    fireEvent.drop(screen.getByLabelText("Running"), { dataTransfer });
    await waitFor(() => expect(toast).toHaveBeenCalledWith("cannot move a done mission to backlog", "error"));
  });

  it("does not report a truncated list as the whole truth", async () => {
    (api.board.get as any).mockResolvedValue({
      columns: COLUMNS,
      counts: { backlog: 1, running: 0, awaiting: 0, done: 0 },
      total: 134,
    });
    render(<KanbanView />);
    await waitFor(() => expect(screen.getByText("Plan my week")).toBeTruthy());
    expect(screen.getByText("1 of 134 missions")).toBeTruthy();
  });
});
