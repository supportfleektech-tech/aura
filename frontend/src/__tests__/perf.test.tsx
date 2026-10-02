import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";
import { PerfView } from "../views2/perf";
import { api } from "../api";

// `ago` is re-exported through the api module by views1 (which owns useFetch), so
// a mock without it makes the named import fail at module load. `Project`/`Task`
// are type-only imports and are erased by the transform.
vi.mock("../api", () => ({
  api: {
    workers: { status: vi.fn(), dead: vi.fn(), drain: vi.fn() },
    consolidation: { status: vi.fn(), run: vi.fn() },
  },
  ago: (s: string) => s,
}));

const toast = vi.fn();

vi.mock("../store", () => ({ useStore: () => ({ toast }) }));

// vitest.config.ts sets no auto-cleanup, so unmount explicitly — otherwise the
// pills and rows from a previous test stay mounted and getByText matches two.
afterEach(() => cleanup());

const STATS = {
  stats: { queued: 2, running: 1, done: 40, dead: 1, throughput_per_min: 12, error_rate: 0.024, by_kind: { mission_tick: 40 } },
  pool_size: 3,
};

describe("PerfView", () => {
  beforeEach(() => {
    toast.mockClear();
    (api.workers.status as any).mockResolvedValue(STATS);
    (api.workers.dead as any).mockResolvedValue({ dead: [{ id: 7, kind: "custom", attempts: 4, max_retries: 3, last_error: "boom", updated_at: "" }] });
    (api.workers.drain as any).mockResolvedValue({ ran: 2, done: 2, retried: 0, dead: 0 });
    (api.consolidation.status as any).mockResolvedValue({ enabled: true, due: false, last_run: null });
  });

  it("shows queue depth, throughput and error rate — FR-WRK-004", async () => {
    render(<PerfView />);
    // Gate on a value, not the static label: the labels render before the fetch
    // resolves, so waiting on one proves nothing about the numbers.
    await waitFor(() => expect(screen.getByText("2")).toBeTruthy());
    expect(screen.getByText("Queued")).toBeTruthy();
    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.getByText("2.4%")).toBeTruthy();
    expect(screen.getByText(/Pool/)).toBeTruthy();
  });

  it("lists dead letters with their error — FR-WRK-003", async () => {
    render(<PerfView />);
    // The error rides in Row's `sub`, whose own text is "4/3 attempts — boom",
    // so an exact "boom" query can never match — only a substring pattern can.
    await waitFor(() => expect(screen.getByText(/boom/)).toBeTruthy());
    expect(screen.getByText("#7 custom")).toBeTruthy();
    expect(screen.getByText(/4\/3 attempts/)).toBeTruthy();
  });

  it("says so when the dead-letter queue is empty", async () => {
    (api.workers.dead as any).mockResolvedValue({ dead: [] });
    render(<PerfView />);
    await waitFor(() => expect(screen.getByText(/No dead/)).toBeTruthy());
  });

  it("drains the queue and reports what ran", async () => {
    render(<PerfView />);
    await waitFor(() => expect(screen.getByText("2")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Drain queue/ }));
    await waitFor(() => expect(api.workers.drain).toHaveBeenCalled());
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringContaining("Ran 2 job"), "success"));
  });

  it("does not claim throughput it does not have", async () => {
    (api.workers.status as any).mockResolvedValue({
      stats: { queued: 0, running: 0, done: 0, dead: 0, throughput_per_min: 0, error_rate: 0, by_kind: {} },
      pool_size: 3,
    });
    render(<PerfView />);
    await waitFor(() => expect(screen.getByText(/No jobs yet/)).toBeTruthy());
    expect(screen.getByText("0.0%")).toBeTruthy();
  });

  it("warns, not celebrates, when a drain dead-letters a job", async () => {
    (api.workers.drain as any).mockResolvedValue({ ran: 1, done: 0, retried: 0, dead: 1 });
    render(<PerfView />);
    await waitFor(() => expect(screen.getByText("2")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Drain queue/ }));
    await waitFor(() => expect(toast).toHaveBeenCalledWith(expect.stringContaining("1 dead"), "warn"));
  });

  it("runs a consolidation pass and reports the counts", async () => {
    (api.consolidation.run as any).mockResolvedValue({ scanned: 12, merged: 1, archived: 2, rescored: 3, duration_ms: 40 });
    render(<PerfView />);
    await waitFor(() => expect(screen.getByText("true")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Run now/ }));
    await waitFor(() => expect(api.consolidation.run).toHaveBeenCalled());
    await waitFor(() => expect(toast).toHaveBeenCalledWith(
      expect.stringContaining("1 merged, 2 archived, 3 re-scored"), "success"));
  });
});