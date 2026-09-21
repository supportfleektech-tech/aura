/* Settings + prefs tests. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LangProvider } from "../i18n";
import { StoreProvider } from "../store";
import { SettingsView } from "../views2";
import { getServer, loadUiPrefs, setServerCache } from "../prefs";

afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

describe("prefs", () => {
  it("defaults + invalid recovery + clamping", () => {
    expect(loadUiPrefs().theme).toBe("dark");
    localStorage.setItem("aura-ui-prefs", JSON.stringify({ theme: "neon", fontScale: 9 }));
    const p = loadUiPrefs();
    expect(p.theme).toBe("dark");
    expect(p.fontScale).toBeLessThanOrEqual(1.2);
    localStorage.setItem("aura-ui-prefs", "{broken");
    expect(loadUiPrefs().accent).toBe("violet");
  });
  it("server cache falls back then serves", () => {
    expect(getServer("chat_streaming", true)).toBe(true);
    setServerCache({ chat_streaming: false });
    expect(getServer("chat_streaming", true)).toBe(false);
  });
});

describe("SettingsView", () => {
  it("renders engine + appearance sections", async () => {
    const dash = { priorities: [], counts: {}, projects: [], clients: [], activity: [], notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {} };
    const fx: Record<string, unknown> = {
      "/api/me": { name: "T", role: "R", location: "L", version: "1.15.0" },
      "/api/dashboard": dash,
      "/api/health": { ok: true, services: [{ name: "SQLite", status: "online", detail: "x" }], metrics: {} },
      "/api/approvals": { approvals: [] },
      "/api/settings": {
        values: { voice_engine: "kokoro", voice_kokoro_id: "af_heart", privacy: "local-first", cloud_provider: "openrouter", openrouter_model: "m:free", cloud_temperature: 0.6, cloud_max_tokens: 900, cloud_memory_policy: "strict", chat_streaming: true, enter_to_send: true, chat_timestamps: false, voice_lang: "en-KE", voice_rate: 1, voice_autoplay: false, toast_duration_ms: 4200, quiet_start: "", quiet_end: "", retention_days: 90, memory_auto_store: true, ollama_base_url: "http://x", ollama_chat_model: "y" },
        secrets: { openrouter_key: false, openai_key: false, custom_key: false }, sources: {},
      },
      "/api/tools": { tools: [], hermes: "2.0.0" },
      "/api/push/vapid-public-key": { key: null, configured: false },
      "/api/voice/engines": {
        engines: [
          { id: "browser", label: "Browser voices", offline: true, available: true, features: ["voices"], note: "b" },
          { id: "kokoro", label: "Kokoro", offline: true, available: false, voices: [{ id: "af_heart", label: "Heart" }, { id: "bf_emma", label: "Emma" }], features: ["voices", "rate"], note: "Kokoro assets missing: run download_kokoro.py" },
          { id: "piper", label: "Piper", offline: true, available: true, voices: [{ id: "en_US-amy-medium", label: "Amy" }], features: ["voices"], note: "p" },
          { id: "edge", label: "Edge Neural", offline: false, available: false, voices: [{ id: "en-KE-ChilembaNeural", label: "Chilemba" }], features: ["voices"], note: "e" },
        ],
        emotions: [{ id: "neutral", label: "Neutral" }, { id: "cheerful", label: "Cheerful" }],
        current: {},
      },
      "/api/costs": {
        today: { calls: 2, prompt_tokens: 100, completion_tokens: 50, cost_usd: 0.0012, unknown_pricing: false },
        month: { calls: 9, prompt_tokens: 900, completion_tokens: 400, cost_usd: 0.0099, unknown_pricing: true },
        by_model: [{ provider: "openai", model: "gpt-4o-mini", calls: 9, cost_usd: 0.0099, unknown_pricing: false }],
        by_day: [], budgets: { daily_cap_usd: 0, monthly_cap_usd: 0, daily_over: false, monthly_over: false },
      },
    };
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/api/settings" && init?.method === "PATCH") {
        const settings = fx[url] as { values: Record<string, unknown> };
        settings.values = { ...settings.values, ...JSON.parse(String(init.body)) };
      }
      const body = fx[url] ?? {};
      return { ok: true, json: async () => body, text: async () => JSON.stringify(body) };
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<LangProvider><StoreProvider><SettingsView /></StoreProvider></LangProvider>);
    expect(await screen.findByText("AI Engine & Cloud")).toBeInTheDocument();
    expect(await screen.findByText("Cloud costs")).toBeInTheDocument();
    expect(screen.getByLabelText("daily cost cap")).toBeInTheDocument();
    expect(screen.getByLabelText("voice")).toBeInTheDocument();
    expect(screen.getByLabelText("emotion")).toBeInTheDocument();
    expect(screen.getByText("Test voice")).toBeInTheDocument();
    expect(screen.getByText("Appearance")).toBeInTheDocument();
    expect(screen.getByText("About & Danger Zone")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Kokoro" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("voice")).toHaveValue("af_heart"));
    fireEvent.change(screen.getByLabelText("voice"), { target: { value: "bf_emma" } });
    await waitFor(() => expect(getServer("voice_kokoro_id", "")).toBe("bf_emma"));
    expect(fetchMock).toHaveBeenCalledWith("/api/settings", expect.objectContaining({ method: "PATCH", body: JSON.stringify({ voice_kokoro_id: "bf_emma" }) }));
    expect(screen.getByText("Conversational personality")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Humour"), { target: { value: "light" } });
    await waitFor(() => expect(getServer("ai_humour", "")).toBe("light"));
    expect(fetchMock).toHaveBeenCalledWith("/api/settings", expect.objectContaining({ method: "PATCH", body: JSON.stringify({ ai_humour: "light" }) }));
  });
});
