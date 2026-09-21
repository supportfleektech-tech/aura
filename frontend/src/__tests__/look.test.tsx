/* LookPanel smoke tests — off-states only (no camera in jsdom). */
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { LangProvider } from "../i18n";
import { StoreProvider } from "../store";
import { LookPanel } from "../views2";

afterEach(() => { vi.unstubAllGlobals(); cleanup(); });

const DASH = {
  priorities: [], counts: {}, projects: [], clients: [], activity: [],
  notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {},
};

function mockApi(status: unknown) {
  const FX: Record<string, unknown> = {
    "/api/me": { name: "T", role: "R", location: "L", version: "1.15.0" },
    "/api/dashboard": DASH,
    "/api/vision/status": status,
  };
  vi.stubGlobal("fetch", (async (url: string) => {
    const body = FX[url] ?? {};
    return { ok: true, json: async () => body, text: async () => JSON.stringify(body) };
  }) as unknown as typeof fetch);
}
const wrap = () => render(<LangProvider><StoreProvider><LookPanel /></StoreProvider></LangProvider>);

describe("LookPanel", () => {
  it("shows the off-state when no vision model is reachable", async () => {
    mockApi({ ollama_model: "llava", ollama_online: false, cloud_configured: false, available: false });
    wrap();
    expect(await screen.findByText("no vision model")).toBeInTheDocument();
    expect(screen.getByText(/Start Ollama/)).toBeInTheDocument();
  });
  it("shows capture controls when vision is ready", async () => {
    mockApi({ ollama_model: "llava", ollama_online: true, cloud_configured: false, available: true });
    wrap();
    expect(await screen.findByText(/vision ready/)).toBeInTheDocument();
    expect(screen.getByText(/Camera/)).toBeInTheDocument();
    expect(screen.getByText(/Screenshot/)).toBeInTheDocument();
    expect(screen.getByText(/Upload frame/)).toBeInTheDocument();
  });
});
