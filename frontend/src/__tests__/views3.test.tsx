/* Connections views smoke tests. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { LangProvider } from "../i18n";
import { StoreProvider } from "../store";
import { BriefingsPanel, CalendarView, InboxView } from "../views3";

afterEach(() => vi.unstubAllGlobals());

const DASH = {
  priorities: [], counts: {}, projects: [], clients: [], activity: [],
  notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {},
};
const FX: Record<string, unknown> = {
  "/api/me": { name: "T", role: "R", location: "L", version: "1.15.0" },
  "/api/dashboard": DASH,
  "/api/health": { ok: true, services: [], metrics: {} },
  "/api/approvals": { approvals: [] },
  "/api/mail/accounts": { accounts: [{ id: 1, name: "Box", host: "", port: 993, username: "", mode: "sandbox", status: "active", has_password: false, unseen: 2, last_sync: null, last_error: "" }] },
  "/api/mail/emails?x=1": { emails: [{ id: 1, account_id: 1, sender: "a@b.c", subject: "Q3 planning notes", snippet: "hello", mail_date: "", seen: 0, triage: "action", triage_reason: "" }], unread: 1 },
  "/api/calendar/week": { events: [{ id: 1, calendar_id: 1, calendar_name: "Personal", uid: "u", title: "Standup", description: "", location: "", starts_at: "2026-09-10T06:00:00+00:00", ends_at: "2026-09-10T06:30:00+00:00", all_day: 0 }] },
  "/api/calendar/calendars": { calendars: [{ id: 1, name: "Personal", source: "local", color: "blue", status: "active", fields: {}, secrets_set: {}, last_sync: null, last_error: "" }] },
  "/api/briefings": { briefings: [{ id: 1, name: "Morn", kind: "morning", prompt: "", enabled: 1, last_run: null, last_model: "" }] },
  "/api/briefings/runs/list": { runs: [] },
};

function mockApi() {
  vi.stubGlobal("fetch", (async (url: string) => {
    const body = FX[url] ?? {};
    return { ok: true, json: async () => body, text: async () => JSON.stringify(body) };
  }) as unknown as typeof fetch);
}
const wrap = (c: React.ReactElement) => render(<LangProvider><StoreProvider>{c}</StoreProvider></LangProvider>);

describe("connections views", () => {
  it("InboxView renders accounts + messages", async () => {
    mockApi();
    wrap(<InboxView />);
    expect(await screen.findByText("Box")).toBeInTheDocument();
    expect(screen.getByText("Q3 planning", { exact: false })).toBeInTheDocument();
  });
  it("CalendarView renders week agenda", async () => {
    mockApi();
    wrap(<CalendarView />);
    expect(await screen.findByText("Standup", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("New Event")).toBeInTheDocument();
  });
  it("BriefingsPanel renders saved + run buttons", async () => {
    mockApi();
    wrap(<BriefingsPanel />);
    expect(await screen.findByText("Morn")).toBeInTheDocument();
    expect(screen.getByText("☀️ Morning now")).toBeInTheDocument();
  });
});
