/* First-run onboarding wizard tests. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { LangProvider } from "../i18n";
import { StoreProvider } from "../store";
import { OnboardingGate, OnboardingWizard } from "../Onboarding";

afterEach(() => vi.unstubAllGlobals());

const DASH = {
  priorities: [], counts: {}, projects: [], clients: [], activity: [],
  notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {},
};
const SETTINGS = {
  values: {
    onboarded: false, timezone: "Africa/Nairobi", domain_career: true,
    domain_clients: true, domain_personal: true, memory_auto_store: true,
    cloud_memory_policy: "strict", privacy: "local-first", cloud_provider: "openrouter",
    quiet_start: "", quiet_end: "",
  },
  secrets: {}, sources: {},
};

function mockApi(onboarded: boolean, calls: { url: string; method: string; body: string }[], delayMs = 0) {
  const fx: Record<string, unknown> = {
    "/api/me": { name: "T", role: "R", location: "L", version: "1.15.0" },
    "/api/dashboard": DASH,
    "/api/health": { ok: true, services: [], metrics: {} },
    "/api/approvals": { approvals: [] },
    "/api/settings": { ...SETTINGS, values: { ...SETTINGS.values, onboarded } },
    "/api/gateway/status": { integrations: [], events: [] },
  };
  vi.stubGlobal("fetch", (async (url: string, init?: { method?: string; body?: string }) => {
    calls.push({ url, method: init?.method || "GET", body: init?.body || "" });
    if (delayMs) await new Promise((r) => setTimeout(r, delayMs));
    const body = fx[url] ?? {};
    return { ok: true, json: async () => body, text: async () => JSON.stringify(body) };
  }) as unknown as typeof fetch);
}
const wrap = (c: React.ReactElement) => render(<LangProvider><StoreProvider>{c}</StoreProvider></LangProvider>);

describe("onboarding", () => {
  it("gate shows wizard when onboarded=false, hides when true", async () => {
    const calls: { url: string; method: string; body: string }[] = [];
    mockApi(false, calls);
    const { unmount } = wrap(<OnboardingGate />);
    expect(await screen.findByText("Welcome to AURA")).toBeInTheDocument();
    unmount();
    const calls2: { url: string; method: string; body: string }[] = [];
    mockApi(true, calls2);
    wrap(<OnboardingGate />);
    await new Promise((r) => setTimeout(r, 150));
    expect(screen.queryByText("Welcome to AURA")).toBeNull();
  });

  it("step 1 saves identity + timezone and advances", async () => {
    const calls: { url: string; method: string; body: string }[] = [];
    mockApi(false, calls);
    const { unmount } = wrap(<OnboardingWizard onDone={() => undefined} />);
    await screen.findByDisplayValue("T");
    fireEvent.change(screen.getByPlaceholderText("Antony"), { target: { value: "Zed" } });
    fireEvent.click(screen.getByText("Continue"));
    expect(await screen.findByText("Choose your domains")).toBeInTheDocument();
    const meCall = calls.find((c) => c.url === "/api/me" && c.method === "PATCH");
    expect(meCall && JSON.parse(meCall.body).name).toBe("Zed");
    const tzCall = calls.find((c) => c.url === "/api/settings" && c.method === "PATCH");
    expect(tzCall && JSON.parse(tzCall.body).timezone).toBe("Africa/Nairobi");
    unmount();
  });

  it("keeps Continue inert until the identity fields have loaded", async () => {
    // The name field is seeded from /api/me. While that is in flight the wizard
    // used to accept a click, then throw "Name is required" and silently refuse
    // to advance — telling a user with a name that they have none.
    const calls: { url: string; method: string; body: string }[] = [];
    mockApi(false, calls, 120); // keep /api/me in flight long enough to observe
    const { unmount } = wrap(<OnboardingWizard onDone={() => undefined} />);
    expect(await screen.findByText("Who are you?")).toBeInTheDocument();
    const early = screen.getByText("Continue").closest("button") as HTMLButtonElement;
    expect(early.disabled).toBe(true);
    expect((document.querySelector('input[placeholder="Antony"]') as HTMLInputElement).value).toBe("");
    await screen.findByDisplayValue("T");
    expect((screen.getByText("Continue").closest("button") as HTMLButtonElement).disabled).toBe(false);
    unmount();
  });

  it("full walk sets onboarded=true and finishes", async () => {
    const calls: { url: string; method: string; body: string }[] = [];
    mockApi(false, calls);
    const onDone = vi.fn();
    const { unmount } = wrap(<OnboardingWizard onDone={onDone} />);
    // Wait for the identity fields to be seeded from /api/me first. They are
    // empty until that lands, and Continue is inert while they load, so clicking
    // before it resolves made the walk stall on step 1 — which is exactly what CI
    // hit, since its fetches are slower than the local ones.
    await screen.findByDisplayValue("T");
    const titles = ["Who are you?", "Choose your domains", "Memory mode", "Intelligence",
      "Connect platforms", "Notifications", "First goals & projects"];
    for (const title of titles) {
      expect(await screen.findByText(title)).toBeInTheDocument();
      const next = screen.getByText("Continue").closest("button");
      expect(next).not.toBeDisabled();
      fireEvent.click(next as HTMLButtonElement);
    }
    expect(await screen.findByText("Ask AURA anything.")).toBeInTheDocument();
    const fin = calls.filter((c) => c.url === "/api/settings" && c.method === "PATCH");
    expect(fin.length).toBeGreaterThan(0);
    expect(JSON.parse(fin[fin.length - 1].body).onboarded).toBe(true);
    expect(screen.getByText("Try it")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Start using AURA"));
    expect(onDone).toHaveBeenCalled();
    unmount();
  });
});
