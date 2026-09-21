/* AnalyticsView smoke tests. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { LangProvider } from "../i18n";
import { StoreProvider } from "../store";
import { AnalyticsView } from "../views3";

afterEach(() => { vi.unstubAllGlobals(); cleanup(); });

const DASH = {
  priorities: [], counts: {}, projects: [], clients: [], activity: [],
  notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {},
};
const FULL = {
  spending: {
    by_currency: [{ currency: "KES", month: 12500, last_month: 10000, delta_pct: 25 }],
    by_day: [{ day: "2026-09-08", currency: "KES", total: 500 }],
    by_category: [{ category: "groceries", currency: "KES", total: 3000 }],
  },
  tasks: {
    done_14d: [{ day: "2026-09-08", n: 3 }], created_30: 10, done_30: 7,
    completion_rate: 0.7, overdue_now: 2, by_status: { done: 7, pending: 3 },
  },
  habits: [{ name: "Gym", streak: 5, last_done: "2026-09-08", done_today: true }],
  sleep: { avg_7d: 7.5, nights: [{ date: "2026-09-08", hours: 7.5 }] },
  mood: { avg_14d: 8, points: [{ day: "2026-09-08", score: 8 }] },
  activity: { runs_14d: [{ day: "2026-09-08", n: 2 }], messages_14d: [{ day: "2026-09-08", n: 4 }] },
  forecast: { spending_next_7d: { currency: "KES", amount: 4200, basis: "7d average" }, task_velocity_per_day: 0.5, tasks_next_7d: 4, sleep_trend: 0.2, mood_trend: -0.1 },
};
const EMPTY_A = {
  spending: { by_currency: [], by_day: [], by_category: [] },
  tasks: { done_14d: [], created_30: 0, done_30: 0, completion_rate: null, overdue_now: 0, by_status: {} },
  habits: [],
  sleep: { avg_7d: null, nights: [] },
  mood: { avg_14d: null, points: [] },
  activity: { runs_14d: [], messages_14d: [] },
};

function mockApi(overview: unknown) {
  const FX: Record<string, unknown> = {
    "/api/me": { name: "T", role: "R", location: "L", version: "1.15.0" },
    "/api/dashboard": DASH,
    "/api/analytics/overview": overview,
  };
  vi.stubGlobal("fetch", (async (url: string) => {
    const body = FX[url] ?? {};
    return { ok: true, json: async () => body, text: async () => JSON.stringify(body) };
  }) as unknown as typeof fetch);
}
const wrap = (c: React.ReactElement) => render(<LangProvider><StoreProvider>{c}</StoreProvider></LangProvider>);

describe("AnalyticsView", () => {
  it("renders spending, tasks, habits, mood panels with data", async () => {
    mockApi(FULL);
    wrap(<AnalyticsView />);
    expect(await screen.findByText("Spending")).toBeInTheDocument();
    expect(screen.getByText("KES 12,500", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("70% done", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("2 overdue")).toBeInTheDocument();
    expect(screen.getByText("Gym")).toBeInTheDocument();
    expect(screen.getByText(/5-day streak/)).toBeInTheDocument();
    expect(screen.getByText("Forecast")).toBeInTheDocument();
    expect(screen.getByText(/Next 7d spend/)).toBeInTheDocument();
  });
  it("shows honest empty states when there is no data", async () => {
    mockApi(EMPTY_A);
    wrap(<AnalyticsView />);
    expect(await screen.findByText("No spending data")).toBeInTheDocument();
    expect(screen.getByText("No task activity")).toBeInTheDocument();
    expect(screen.getByText("No habits")).toBeInTheDocument();
    expect(screen.getByText("No mood data")).toBeInTheDocument();
  });
});
