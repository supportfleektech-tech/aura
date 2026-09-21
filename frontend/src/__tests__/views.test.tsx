/* Workspace smoke tests — each view must survive the loading → loaded
 * transition (a Rules-of-Hooks violation crashes exactly there). */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { LangProvider } from "../i18n";
import { StoreProvider } from "../store";
import { CareerView, ClientsView, PersonalView } from "../views1";
import { FilesView } from "../views2";

afterEach(() => vi.unstubAllGlobals());

const DASH = {
  priorities: [], counts: {}, projects: [], clients: [], activity: [],
  notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {},
};
const FIXTURES: Record<string, unknown> = {
  "/api/me": { name: "T", role: "R", location: "L", version: "1.15.0" },
  "/api/dashboard": DASH,
  "/api/health": { ok: true, services: [{ name: "Local LFM", status: "degraded", detail: "x" }] },
  "/api/approvals": { approvals: [] },
  "/api/career/overview": { resumes: [], applications: [], interviews: [], today_blocks: [], tasks: [], pipeline: {} },
  "/api/clients": { clients: [] },
  "/api/projects": { projects: [] },
  "/api/backup/history": { backups: [], files: [], litestream: { enabled: false } },
  "/api/personal/overview": { journal: [], goals: [], expenses: [], habits: [], sleep: [], spending_total: 0 },
  "/api/files": { files: [{ id: 7, name: "pic.png", mime: "image/png", size: 2048, domain: "general", created_at: "2026-09-09T00:00:00Z" },
    { id: 8, name: "doc.txt", mime: "text/plain", size: 512, domain: "general", created_at: "2026-09-09T00:00:00Z" }] },
  "/api/files/7/analyze": { description: "A test image.", model: "ollama/llava", ms: 5 },
};

function mockApi() {
  vi.stubGlobal("fetch", (async (url: string) => {
    const body = FIXTURES[url] ?? {};
    return { ok: true, json: async () => body, text: async () => JSON.stringify(body) };
  }) as unknown as typeof fetch);
}

const wrap = (c: React.ReactElement) => render(<LangProvider><StoreProvider>{c}</StoreProvider></LangProvider>);

describe("FilesView vision", () => {
  it("offers Analyze on images and renders the description", async () => {
    mockApi();
    wrap(<FilesView />);
    expect(await screen.findByText("pic.png")).toBeInTheDocument();
    expect(screen.getByText("doc.txt")).toBeInTheDocument();
    expect(screen.getAllByText("Analyze")).toHaveLength(1);
    fireEvent.click(screen.getByText("Analyze"));
    expect(await screen.findByText("A test image.")).toBeInTheDocument();
  });
});

describe("workspace views", () => {
  it("CareerView renders past loading", async () => {
    mockApi();
    wrap(<CareerView />);
    expect(await screen.findByText("Today's Priorities")).toBeInTheDocument();
    expect(screen.getByText("Applications Pipeline")).toBeInTheDocument();
  });
  it("ClientsView renders past loading", async () => {
    mockApi();
    wrap(<ClientsView />);
    expect(await screen.findByText("Project Tracker")).toBeInTheDocument();
    expect(screen.getByText("Backup Manager")).toBeInTheDocument();
  });
  it("PersonalView renders past loading", async () => {
    mockApi();
    wrap(<PersonalView />);
    expect(await screen.findByText("Journal & Reflection")).toBeInTheDocument();
    expect(screen.getByText("Sleep")).toBeInTheDocument();
  });
});
