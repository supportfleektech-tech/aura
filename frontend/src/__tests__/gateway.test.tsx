/* GatewayView messaging-bot controls smoke tests. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { LangProvider } from "../i18n";
import { StoreProvider } from "../store";
import { GatewayView } from "../views2";

afterEach(() => { vi.unstubAllGlobals(); cleanup(); });

const DASH = {
  priorities: [], counts: {}, projects: [], clients: [], activity: [],
  notifications: [], gateway: [], timeblocks: [], insights: {}, memory_by_domain: {},
};
const STATUS = {
  integrations: [
    { platform: "telegram", status: "connected", account: "aura-tg", mode: "live", configured: true, fields: { default_chat_id: "42" }, last_error: "", last_test: null },
    { platform: "whatsapp", status: "disconnected", account: "", mode: "sandbox", configured: false, missing: ["webhook_url or wa_token+phone_number_id"], fields: {}, last_error: "", last_test: null },
  ],
  events: [],
};
const POLL = { ok: true, fetched: 1, inbound: [{ chat_id: "42", text: "hi" }], replies: 0 };

function mockApi() {
  const spy = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url);
    let body: unknown = {};
    if (u === "/api/me") body = { name: "T", role: "R", location: "L", version: "1.15.0" };
    else if (u === "/api/dashboard") body = DASH;
    else if (u === "/api/gateway/status") body = STATUS;
    else if (u === "/api/gateway/telegram/poll" && init?.method === "POST") body = POLL;
    return { ok: true, json: async () => body, text: async () => JSON.stringify(body) };
  });
  vi.stubGlobal("fetch", spy as unknown as typeof fetch);
  return spy;
}
const wrap = () => render(<LangProvider><StoreProvider><GatewayView /></StoreProvider></LangProvider>);

describe("GatewayView messaging", () => {
  it("shows Check messages on connected telegram, polls on click", async () => {
    const spy = mockApi();
    wrap();
    const btn = await screen.findByText("Check messages");
    fireEvent.click(btn);
    await waitFor(() => expect(spy).toHaveBeenCalledWith("/api/gateway/telegram/poll", expect.objectContaining({ method: "POST" })));
  });
  it("configure reveals bot fields + webhook hint", async () => {
    mockApi();
    wrap();
    const confs = await screen.findAllByText("Configure");
    fireEvent.click(confs[0]);
    expect(await screen.findByPlaceholderText(/Auto-reply text/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Webhook secret/)).toBeInTheDocument();
    expect(screen.getByText(/POST \/api\/gateway\/telegram\/webhook/)).toBeInTheDocument();
  });
  it("whatsapp card offers Cloud API + generic credential fields", async () => {
    mockApi();
    wrap();
    const confs = await screen.findAllByText("Configure");
    fireEvent.click(confs[1]);
    expect(await screen.findByPlaceholderText(/Cloud API token/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/phone_number_id/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/verify token/i)).toBeInTheDocument();
  });
});
