import { useState } from "react";
import { ago, api, GwIntegration } from "../api";
import { useStore } from "../store";
import { useLang } from "../i18n";
import { Field, useFetch } from "../views1";
import { Btn, Dot, Empty, Icon, Panel, Pill, Row, Skel, Toggle } from "../ui";

const GW_FIELDS: Record<string, { key: string; label: string; secret?: boolean }[]> = {
  telegram: [{ key: "bot_token", label: "Bot token", secret: true }, { key: "default_chat_id", label: "Default chat ID" }, { key: "auto_reply", label: "Auto-reply text (empty = off)" }, { key: "webhook_secret", label: "Webhook secret (optional)", secret: true }],
  email: [{ key: "smtp_host", label: "SMTP host" }, { key: "smtp_port", label: "Port" }, { key: "smtp_user", label: "Username" }, { key: "smtp_pass", label: "Password", secret: true }, { key: "from_addr", label: "From address" }],
  discord: [{ key: "webhook_url", label: "Webhook URL", secret: true }],
  slack: [{ key: "webhook_url", label: "Webhook URL", secret: true }],
  whatsapp: [{ key: "webhook_url", label: "Provider webhook URL (generic)", secret: true }, { key: "wa_token", label: "Cloud API token (alt.)", secret: true }, { key: "phone_number_id", label: "Cloud phone_number_id (alt.)" }, { key: "verify_token", label: "Webhook verify token", secret: true }, { key: "default_to", label: "Default recipient" }, { key: "auto_reply", label: "Auto-reply text (empty = off)" }],
  homeassistant: [{ key: "base_url", label: "Base URL (http://ha:8123)" }, { key: "token", label: "Long-lived token", secret: true }],
};

function GwCard({ g, reload }: { g: GwIntegration; reload: () => void }) {
  const { toast } = useStore();
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState(g.mode || "sandbox");
  const [vals, setVals] = useState<Record<string, string>>({});
  const live = (g.mode || "sandbox") === "live";
  const set = (k: string, v: string) => setVals({ ...vals, [k]: v });
  return (
    <div className="entitycard">
      <header>
        <span className={`gwic ${g.status === "connected" ? "on" : "off"}`}><Icon n={g.platform === "email" ? "mail" : g.platform === "slack" ? "hash" : g.platform === "homeassistant" ? "home" : "tg"} s={20} /></span>
        <div><strong style={{ textTransform: "capitalize" }}>{g.platform}</strong><small>{g.account || "not configured"}</small></div>
        <Dot c={g.status === "connected" ? "green" : g.status === "error" ? "red" : "amber"} />
      </header>
      <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
        <Pill c={live ? "amber" : "green"}>{live ? "live" : "sandbox"}</Pill>
        {g.configured && <Pill c="green">credentials saved</Pill>}
        {g.status === "connected"
          ? <><Btn small onClick={async () => { try { const r = await api.gateway.test(g.platform); r.ok ? toast(`${g.platform} ok - ${r.latency_ms}ms${r.detail ? ` - ${r.detail}` : ""}`, "success") : toast(`${g.platform} test failed: ${r.error || ""}`, "error"); } catch (e) { toast(`Test failed: ${e instanceof Error ? e.message : e}`, "error"); } reload(); }}>Test</Btn>
            <Btn small onClick={async () => { await api.gateway.disconnect(g.platform); reload(); }}>Disconnect</Btn>
            {g.platform === "telegram" && <Btn small onClick={async () => { try { const r = await api.gateway.telegramPoll(); r.ok ? toast(r.inbound?.length ? `${r.inbound.length} new message(s)${r.replies ? ` \u00b7 ${r.replies} auto-replied` : ""}` : "No new messages", "success") : toast(`Poll: ${r.error || ""}`, "error"); } catch (e) { toast(`Poll failed: ${e instanceof Error ? e.message : e}`, "error"); } reload(); }}>Check messages</Btn>}</>
          : <Btn small kind="green" onClick={async () => { await api.gateway.connect(g.platform, { account: `aura-${g.platform}` }); toast(`${g.platform} connected (sandbox)`, "success"); reload(); }}>Connect</Btn>}
        <Btn small onClick={() => setOpen(!open)}>{open ? "Close" : "Configure"}</Btn>
      </div>
      {g.last_error ? <small className="red">last error: {g.last_error}</small> : null}
      {g.last_test && <small className="dim">last test {ago(g.last_test)}</small>}
      {open && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
          <label><small className="dim">Mode</small>
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="sandbox">sandbox - audited, no network calls</option>
              <option value="live">live - real delivery via credentials</option>
            </select>
          </label>
          {(GW_FIELDS[g.platform] || []).map((f) => (
            <Field key={f.key} type={f.secret ? "password" : "text"} value={vals[f.key] || ""}
              onChange={(e) => set(f.key, e.target.value)}
              placeholder={`${f.label}${g.fields && g.fields[f.key] ? " (saved)" : "..."}`} />
          ))}
          {mode === "live" && !g.configured && Object.keys(vals).length === 0 && <small className="amber">Live mode needs credentials above.</small>}
          {(g.platform === "telegram" || g.platform === "whatsapp") && <small className="dim">Inbound: POST /api/gateway/{g.platform}/webhook{g.platform === "whatsapp" ? " \u00b7 verify via GET with hub.mode/hub.verify_token/hub.challenge" : " \u00b7 secret header x-telegram-bot-api-secret-token"} — needs a public URL; polling needs none.</small>}
          <div style={{ display: "flex", gap: 6 }}>
            <Btn small kind="violet" onClick={async () => {
              try {
                await api.gateway.connect(g.platform, { account: g.account || `aura-${g.platform}`, mode, config: vals });
                toast(`${g.platform} saved (${mode})`, "success"); setOpen(false); setVals({}); reload();
              } catch (e) { toast(`Save failed: ${e instanceof Error ? e.message : e}`, "error"); }
            }}>Save</Btn>
            <Btn small onClick={async () => { if (!confirm(`Forget all ${g.platform} credentials?`)) return; await api.gateway.disconnect(g.platform, true); reload(); toast("Credentials forgotten", "success"); }}>Forget creds</Btn>
          </div>
        </div>
      )}
    </div>
  );
}

export function GatewayView() {
  const { t } = useLang();
  const { data, reload } = useFetch(() => api.gateway.status());
  const { toast, send } = useStore();
  const [sim, setSim] = useState("");
  const [plat, setPlat] = useState("telegram");
  const [liveSend, setLiveSend] = useState(false);
  const [to, setTo] = useState("");
  return (
    <div className="view">
      <div className="vhead"><h2><Icon n="grid" s={20} /> {t("title.gateway")}</h2><Pill c="green">canonical event bus</Pill></div>
      <div className="cards">
        {(data?.integrations || []).map((g) => <GwCard key={g.platform} g={g} reload={reload} />)}
      </div>
      <div className="grid2">
        <Panel icon="chat" title="Simulate Inbound Message" sub="All platforms normalize to one event format">
          <div style={{ display: "flex", gap: 8 }}>
            <select value={plat} onChange={(e) => setPlat(e.target.value)}>{["telegram", "discord", "slack", "whatsapp", "email"].map((p) => <option key={p} value={p}>{p}</option>)}</select>
            <Field value={sim} onChange={(e) => setSim(e.target.value)} placeholder="Message text..." />
            <Btn small kind="violet" onClick={async () => { if (!sim.trim()) return; await api.gateway.simulate(plat, sim); setSim(""); reload(); toast("Inbound event emitted", "success"); }}>Send</Btn>
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8, flexWrap: "wrap" }}>
            <label style={{ display: "flex", gap: 6, alignItems: "center" }}><input type="checkbox" checked={liveSend} onChange={(e) => setLiveSend(e.target.checked)} /><small>deliver for real (live + connected only)</small></label>
            {liveSend && <Field value={to} onChange={(e) => setTo(e.target.value)} placeholder="To (chat ID / email / phone)..." />}
            {liveSend && <Btn small kind="green" onClick={async () => { if (!sim.trim()) { toast("Type a message first", "warn"); return; } try { const r = await api.gateway.simulate(plat, sim, { send_live: true, to }); setSim(""); reload(); toast(`Delivered via ${plat} (${r.mode})`, "success"); } catch (e) { toast(`Live send failed: ${e instanceof Error ? e.message : e}`, "error"); } }}>Deliver</Btn>}
          </div>
          <Btn small onClick={() => send("draft follow-up messages for overdue tasks")}>Create approval-gated outbound &rarr;</Btn>
        </Panel>
        <Panel icon="clock" title="Event Bus" sub="Recent canonical events">
          {(data?.events || []).map((e, i) => <Row key={i} icon={e.direction === "in" ? "chat" : "send"} title={`${e.direction === "in" ? "\u2190" : "\u2192"} ${e.platform}`} sub={`${(e.text || "").slice(0, 70)} - ${ago(e.created_at)}`} />)}
          {(data?.events || []).length === 0 && <Empty title="No events yet" sub="Simulate an inbound message to see the bus." />}
        </Panel>
      </div>
    </div>
  );
}


/* ============================== SMART HOME ============================== */
const HA_ICONS: Record<string, string> = { light: "spark", switch: "zap", sensor: "chart", script: "play", climate: "wave", cover: "more" };

export function SmartHomeView() {
  const { t } = useLang();
  const { toast } = useStore();
  const { data: st, reload: reloadSt } = useFetch(() => api.home.status());
  const { data: ents, reload: reloadEnts } = useFetch(() => api.home.entities());
  const [baseUrl, setBaseUrl] = useState("");
  const [token, setToken] = useState("");
  const [mode, setMode] = useState("sandbox");
  const reload = () => { reloadSt(); reloadEnts(); };
  const connected = st?.status === "connected";
  const live = st?.mode === "live";
  const call = async (domain: string, service: string, entity_id = "") => {
    try {
      const r = await api.home.service(domain, service, entity_id);
      r.ok ? toast(`${entity_id || service} \u2192 ${r.state || r.mode || "ok"}`, "success") : toast(r.error || "failed", "error");
    } catch (e) { toast(`${e instanceof Error ? e.message : e}`, "error"); }
    reload();
  };
  return (
    <div className="view">
      <div className="vhead"><h2><Icon n="home" s={20} /> {t("title.smarthome")}</h2>
        <Pill c={connected ? "green" : "amber"}>{st ? st.status : "\u2026"}</Pill>
        {st && <Pill c={live ? "amber" : "blue"}>{live ? "live" : "sandbox"}</Pill>}</div>
      <div className="grid2">
        <Panel icon="home" title="Connection" sub="Home Assistant REST API">
          {!st && <Skel />}
          {st && !connected && (
            <>
              <Field value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="http://homeassistant.local:8123" />
              <div style={{ height: 8 }} />
              <Field type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder="Long-lived access token" />
              <div style={{ height: 8 }} />
              <label><small className="dim">Mode</small>
                <select value={mode} onChange={(e) => setMode(e.target.value)}>
                  <option value="sandbox">sandbox — demo entities, nothing physical</option>
                  <option value="live">live — real Home Assistant</option>
                </select>
              </label>
              {mode === "live" && <small className="dim">HA \u2192 your profile \u2192 Long-Lived Access Tokens. Token never leaves the server.</small>}
              <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                <Btn small kind="green" onClick={async () => {
                  try {
                    await api.gateway.connect("homeassistant", { account: baseUrl || "home-assistant", mode, config: { base_url: baseUrl, token } });
                    setToken(""); reload(); toast(`Home Assistant connected (${mode})`, "success");
                  } catch (e) { toast(`Connect failed: ${e instanceof Error ? e.message : e}`, "error"); }
                }}>Connect</Btn>
              </div>
            </>
          )}
          {st && connected && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              <Btn small onClick={async () => {
                try { const r = await api.gateway.test("homeassistant"); r.ok ? toast(`HA ok — ${r.latency_ms}ms${r.detail ? ` \u00b7 ${r.detail}` : ""}`, "success") : toast(r.error || "test failed", "error"); }
                catch (e) { toast(`${e instanceof Error ? e.message : e}`, "error"); }
                reload();
              }}>Test</Btn>
              <Btn small onClick={async () => { await api.gateway.disconnect("homeassistant"); reload(); }}>Disconnect</Btn>
              <Btn small onClick={async () => { if (!confirm("Forget Home Assistant credentials?")) return; await api.gateway.disconnect("homeassistant", true); reload(); }}>Forget creds</Btn>
            </div>
          )}
          {st?.last_error ? <small className="red">last error: {st.last_error}</small> : null}
        </Panel>
        <Panel icon="grid" title="Entities" sub={ents?.mode === "sandbox" ? "sandbox — demo entities" : live ? "live" : ""}>
          {!ents && <><Skel /><Skel /></>}
          {ents?.error && <Empty title="No entities" sub={ents.error} />}
          {(ents?.entities || []).map((e) => {
            const domain = e.entity_id.split(".")[0];
            const name = (e.attributes?.friendly_name as string) || e.entity_id;
            const unit = (e.attributes?.unit_of_measurement as string) || "";
            const on = e.state === "on";
            return (
              <div key={e.entity_id} className="entitycard">
                <header><span className={`gwic ${on ? "on" : "off"}`}><Icon n={HA_ICONS[domain] || "circle"} s={20} /></span>
                  <div><strong>{name}</strong><small>{e.entity_id}</small></div>
                  <Dot c={on ? "green" : "amber"} /></header>
                <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  {(domain === "light" || domain === "switch") && <Toggle on={on} onFlip={() => void call(domain, "toggle", e.entity_id)} label={e.entity_id} />}
                  {domain === "script" && <Btn small kind="violet" onClick={() => void call(domain, "turn_on", e.entity_id)}>Run</Btn>}
                  <small className="dim">{e.state}{unit ? ` ${unit}` : ""}</small>
                </div>
              </div>
            );
          })}
          {ents && !ents.error && (ents.entities || []).length === 0 && <Empty title="No entities" sub="Home Assistant returned an empty state list." />}
        </Panel>
      </div>
    </div>
  );
}
