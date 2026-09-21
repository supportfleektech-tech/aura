/* SmartHomeView smoke tests. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { LangProvider } from "../i18n";
import { StoreProvider } from "../store";
import { SmartHomeView } from "../views2";

afterEach(() => { vi.unstubAllGlobals(); cleanup(); });

const DASH = {
  priorities: [], counts: {}, projects: [], clients: [], activity: [],
  notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {},
};
const OFF = { platform: "homeassistant", status: "disconnected", account: "", last_test: null, mode: "sandbox", configured: false, missing: ["base_url", "token"], fields: {}, last_error: "", last_ok: "" };
const ON = { ...OFF, status: "connected", account: "ha" };
const ENTS = { mode: "sandbox", entities: [
  { entity_id: "light.demo_lamp", state: "on", attributes: { friendly_name: "Demo Lamp (sandbox)" } },
  { entity_id: "sensor.demo_temperature", state: "21.5", attributes: { friendly_name: "Demo Temperature (sandbox)", unit_of_measurement: "°C" } },
] };

function mockApi(status: unknown, ents: unknown) {
  const spy = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url);
    let body: unknown = {};
    if (u === "/api/me") body = { name: "T", role: "R", location: "L", version: "1.15.0" };
    else if (u === "/api/dashboard") body = DASH;
    else if (u === "/api/home/status") body = status;
    else if (u === "/api/home/entities") body = ents;
    else if (u === "/api/home/service" && init?.method === "POST") body = { ok: true, mode: "sandbox", state: "off" };
    else if (u === "/api/gateway/homeassistant/connect") body = { ok: true, mode: "sandbox" };
    return { ok: true, json: async () => body, text: async () => JSON.stringify(body) };
  });
  vi.stubGlobal("fetch", spy as unknown as typeof fetch);
  return spy;
}
const wrap = () => render(<LangProvider><StoreProvider><SmartHomeView /></StoreProvider></LangProvider>);

describe("SmartHomeView", () => {
  it("shows the connect form when disconnected", async () => {
    mockApi(OFF, { mode: "sandbox", entities: [], error: "homeassistant not connected" });
    wrap();
    expect(await screen.findByPlaceholderText(/homeassistant.local/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Long-lived access token/)).toBeInTheDocument();
  });
  it("renders entities with toggles when connected", async () => {
    mockApi(ON, ENTS);
    wrap();
    expect(await screen.findByText("Demo Lamp (sandbox)")).toBeInTheDocument();
    expect(screen.getByText(/21.5/)).toBeInTheDocument();
    expect(screen.getByText(/demo entities/)).toBeInTheDocument();
  });
  it("toggling a light calls the service API", async () => {
    const spy = mockApi(ON, ENTS);
    wrap();
    await screen.findByText("Demo Lamp (sandbox)");
    const toggle = document.querySelector(`[aria-label="light.demo_lamp"], input[type="checkbox"]`);
    expect(toggle).toBeTruthy();
    if (toggle) fireEvent.click(toggle);
    await waitFor(() => expect(spy).toHaveBeenCalledWith("/api/home/service", expect.objectContaining({ method: "POST" })));
  });
});
