import { useEffect, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { useLang } from "../i18n";
import { useFetch } from "../views1";
import { ONBOARD_ZONES } from "../Onboarding";
import { Btn, Empty, Icon, Panel, Pill, Row, SetRow, Seg, Skel, Slider, Toggle } from "../ui";
import { Accent, getServer, loadUiPrefs, saveUiPrefs, setServerCache, UiPrefs, voicePreferenceKey } from "../prefs";
import { PersonalitySettings } from "../PersonalitySettings";
import { playAlertSound } from "../alerts";
import { Field } from "../views1";
import { currentSubscription, pushSupported, subscribePush, unsubscribePush } from "../push";
import { CommandsView } from "./commands";

const FREE_PRESETS = [
  { id: "nvidia/nemotron-3-ultra-550b-a55b:free", name: "Nemotron 3 Ultra \u00b7 1M reasoning" },
  { id: "nvidia/nemotron-3.5-lightning:free", name: "Nemotron 3.5 Lightning \u00b7 1M fast" },
  { id: "nvidia/nemotron-3-super-120b-a12b:free", name: "Nemotron 3 Super \u00b7 reasoning" },
  { id: "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", name: "Nemotron 3 Omni \u00b7 multimodal reasoning" },
  { id: "google/gemma-4-31b-it:free", name: "Gemma 4 31B \u00b7 multimodal reasoning" },
  { id: "google/gemma-4-26b-a4b-it:free", name: "Gemma 4 26B \u00b7 fast multimodal" },
  { id: "qwen/qwen3.8-27b:free", name: "Qwen 3.8 27B \u00b7 multimodal reasoning" },
  { id: "thinkingmachines/inkling:free", name: "Inkling \u00b7 1M multimodal" },
  { id: "thinkingmachines/inkling-small:free", name: "Inkling Small \u00b7 1M multimodal" },
  { id: "openrouter/free", name: "Free Models Router \u00b7 auto-picks a free model" },
  { id: "cohere/north-mini-code:free", name: "North Mini Code \u00b7 coding" },
  { id: "poolside/laguna-s-2.1:free", name: "Laguna S 2.1 \u00b7 coding agent" },
  { id: "poolside/laguna-xs-2.1:free", name: "Laguna XS 2.1 \u00b7 fast coding" },
  { id: "inclusionai/ling-3.0-flash-vl:free", name: "Ling 3.0 VL \u00b7 vision reasoning" },
  { id: "liquid/lfm-2.5-2.6b:free", name: "LFM 2.5 2.6B \u00b7 tiny + fast" },
  { id: "z-ai/glm-5.2:free", name: "GLM 5.2 \u00b7 reasoning" },
];

interface SetCtx {
  draft: Record<string, any>;
  set: (k: string, v: unknown) => void;
  secrets: Record<string, boolean>;
  sources: Record<string, string>;
  save: (body: Record<string, unknown>, msg?: string) => Promise<void>;
}
const Src = ({ k, sources }: { k: string; sources: Record<string, string> }) =>
  sources[k] && sources[k] !== "default" ? <span className="kvsrc">{sources[k]}</span> : null;

function CloudAISettings({ ctx }: { ctx: SetCtx }) {
  const { toast } = useStore();
  const { draft, set, secrets, sources, save } = ctx;
  const provider = (draft.cloud_provider || "openrouter") as string;
  const modelKey = provider === "openai" ? "openai_model" : provider === "custom" ? "custom_model" : "openrouter_model";
  const keyKey = provider === "openai" ? "openai_key" : provider === "custom" ? "custom_key" : "openrouter_key";
  const [tkey, setTkey] = useState("");
  const [models, setModels] = useState(FREE_PRESETS);
  const [loadingModels, setLoadingModels] = useState(false);
  const [listNote, setListNote] = useState("curated free presets");
  const [customMode, setCustomMode] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testRes, setTestRes] = useState<{ ok: boolean; latency_ms?: number; error?: string; reply?: string } | null>(null);
  const keySet = !!secrets[keyKey];
  const model = (draft[modelKey] || "") as string;
  const opts = models.some((m) => m.id === model) || !model ? models : [{ id: model, name: `${model} (current)` }, ...models];

  const loadLive = async () => {
    setLoadingModels(true);
    try {
      const r = await api.cloud.models(true);
      const free = r.models.filter((m) => m.free);
      const list = (free.length ? free : r.models).slice(0, 120).map((m) => {
        const tags: string[] = [];
        if (m.reasoning) tags.push("think");
        if (m.vision) tags.push("vision");
        if (m.multimodal) tags.push("multi");
        const tag = tags.length ? ` [${tags.join(" ")}]` : "";
        return { id: m.id, name: `${m.name}${tag} \u00b7 ${m.free ? "free" : "paid"} \u00b7 ${(m.context_length / 1024).toFixed(0)}k` };
      });
      if (list.length) { setModels(list); setListNote(r.stale ? `live list unavailable — ${r.count} cached` : `${free.length} free of ${r.count} live models`); }
      else setListNote("no models returned");
    } catch { setListNote("could not reach OpenRouter — presets kept"); }
    finally { setLoadingModels(false); }
  };
  const doTest = async () => {
    setTesting(true); setTestRes(null);
    try {
      const r = await api.cloud.test({ provider, model: model || undefined, api_key: tkey.trim() || undefined });
      setTestRes(r);
      toast(r.ok ? `Cloud OK — ${r.model} \u00b7 ${r.latency_ms}ms` : `Cloud test failed: ${r.error || "no reply"}`, r.ok ? "success" : "error");
    } catch (e) { toast(`Test failed: ${e instanceof Error ? e.message : e}`, "error"); }
    finally { setTesting(false); }
  };
  const doSave = async () => {
    const body: Record<string, unknown> = {
      cloud_provider: provider, privacy: draft.privacy, cloud_temperature: draft.cloud_temperature,
      cloud_max_tokens: draft.cloud_max_tokens, cloud_memory_policy: draft.cloud_memory_policy,
      cloud_reasoning: draft.cloud_reasoning,
      [modelKey]: model,
    };
    if (provider === "custom") body.custom_base_url = draft.custom_base_url;
    if (tkey.trim()) body[keyKey] = tkey.trim();
    await save(body, "AI engine saved");
    setTkey("");
  };
  return (
    <Panel icon="cpu" title="AI Engine & Cloud" sub="Local LFM \u2192 cloud \u2192 builtin composer chain"
      right={keySet ? <Pill c="green">key saved</Pill> : <Pill c="amber">no cloud key</Pill>}>
      <small className="secttl2">Cloud provider</small>
      <Seg options={[{ v: "openrouter", label: "OpenRouter" }, { v: "openai", label: "OpenAI" }, { v: "custom", label: "Custom endpoint" }]}
        value={provider} onPick={(v) => set("cloud_provider", v)} />
      <small className="dim"> OpenRouter serves free models (IDs ending in <code>:free</code>) behind one API key from openrouter.ai/keys. Free-model prompts may be used for training — see their policy.</small>
      <SetRow title="Privacy mode" sub={draft.privacy === "local-first" ? "Cloud is never called — local LFM + builtin only." : draft.privacy === "hybrid" ? "Local first, cloud as fallback." : "Cloud first, local as fallback."}
        control={<><Seg options={[{ v: "local-first", label: "Local-first" }, { v: "hybrid", label: "Hybrid" }, { v: "cloud", label: "Cloud" }]}
          value={(draft.privacy || "local-first") as string} onPick={(v) => set("privacy", v)} /><Src k="privacy" sources={sources} /></>} />
      {draft.privacy === "local-first" && <small className="amber">Heads-up: with Local-first the cloud key below is stored but never used. Switch to Hybrid to actually call {provider}.</small>}
      {provider === "custom" && (
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <Field value={(draft.custom_base_url || "") as string} onChange={(e) => set("custom_base_url", e.target.value)} placeholder="https://host:port/v1 (OpenAI-compatible)" />
        </div>
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
        <Field type="password" value={tkey} onChange={(e) => setTkey(e.target.value)}
          placeholder={keySet ? `API key saved ${sources[keyKey] === "env" ? "(from env)" : ""} — type a new one to replace` : "Paste API key\u2026"} />
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
        {provider === "openrouter" && !customMode ? (
          <select value={model} onChange={(e) => set(modelKey, e.target.value)} style={{ flex: 1, minWidth: 220 }}>
            {!model && <option value="">select a model\u2026</option>}
            {opts.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        ) : (
          <Field value={model} onChange={(e) => set(modelKey, e.target.value)} placeholder="model id, e.g. google/gemma-4-31b-it:free" />
        )}
        {provider === "openrouter" && <>
          <Btn small onClick={() => setCustomMode(!customMode)}>{customMode ? "Presets" : "Custom"}</Btn>
          <Btn small onClick={loadLive} disabled={loadingModels}>{loadingModels ? "Loading\u2026" : "\u21bb Live list"}</Btn>
        </>}
      </div>
      {provider === "openrouter" && <small className="dim">{listNote} — free models rotate; the live list is authoritative.</small>}
      <SetRow title="Reasoning / thinking" sub="Send chain-of-thought to models that support it (Nemotron, Gemma 4, Qwen, Inkling, etc). Slightly slower but more accurate."
        control={<Toggle on={!!draft.cloud_reasoning} onFlip={() => set("cloud_reasoning", !draft.cloud_reasoning)} label="reasoning" />} />
      <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap", alignItems: "center" }}>
        <Btn small kind="violet" onClick={doSave}>Save engine</Btn>
        <Btn small onClick={doTest} disabled={testing}>{testing ? "Testing\u2026" : "Test connection"}</Btn>
        {keySet && <Btn small onClick={async () => { if (!confirm("Forget the saved key?")) return; await save({ [keyKey]: "" }, "Key forgotten"); }}>Forget key</Btn>}
        {testRes && (testRes.ok
          ? <Pill c="green">ok \u00b7 {testRes.latency_ms}ms{testRes.reply ? ` \u00b7 \u201c${testRes.reply}\u201d` : ""}</Pill>
          : <Pill c="red">failed \u00b7 {(testRes.error || "").slice(0, 90)}</Pill>)}
      </div>
      <small className="secttl2">Generation</small>
      <SetRow title="Temperature" sub="Lower = focused, higher = creative."
        control={<Slider value={Number(draft.cloud_temperature ?? 0.6)} min={0} max={2} step={0.1} onPick={(v) => set("cloud_temperature", v)} format={(v) => v.toFixed(1)} />} />
      <SetRow title="Max tokens" sub="Cap per cloud reply."
        control={<Slider value={Number(draft.cloud_max_tokens ?? 900)} min={128} max={4000} step={64} onPick={(v) => set("cloud_max_tokens", v)} />} />
      <SetRow title="Cloud memory policy" sub="Strict withholds sensitive + private memories; relaxed withholds private only."
        control={<Seg options={[{ v: "strict", label: "Strict" }, { v: "relaxed", label: "Relaxed" }]}
          value={(draft.cloud_memory_policy || "strict") as string} onPick={(v) => set("cloud_memory_policy", v)} />} />
    </Panel>
  );
}

function AppearanceSettings() {
  const [ui, setUiState] = useState<UiPrefs>(loadUiPrefs());
  const setUi = (p: UiPrefs) => { setUiState(p); saveUiPrefs(p); };
  const ACCENTS: { v: Accent; c: string }[] = [
    { v: "violet", c: "#a855f7" }, { v: "blue", c: "#38bdf8" }, { v: "green", c: "#34d399" },
    { v: "amber", c: "#fbbf24" }, { v: "rose", c: "#f472b6" },
  ];
  return (
    <Panel icon="spark" title="Appearance" sub="Instant preview \u00b7 stored in this browser">
      <SetRow title="Theme" control={<Seg options={[{ v: "dark", label: "Dark" }, { v: "darker", label: "Darker" }, { v: "light", label: "Light" }]}
        value={ui.theme} onPick={(v) => setUi({ ...ui, theme: v })} />} />
      <SetRow title="Accent" control={<span className="swatches">{ACCENTS.map((a) => (
        <button key={a.v} className={`swatch ${ui.accent === a.v ? "on" : ""}`} style={{ background: a.c }}
          onClick={() => setUi({ ...ui, accent: a.v })} title={a.v} aria-label={`${a.v} accent`} />))}</span>} />
      <SetRow title="Density" control={<Seg options={[{ v: "comfortable", label: "Comfortable" }, { v: "compact", label: "Compact" }]}
        value={ui.density} onPick={(v) => setUi({ ...ui, density: v })} />} />
      <SetRow title="Font size" control={<Slider value={ui.fontScale} min={0.85} max={1.2} step={0.05}
        onPick={(v) => setUi({ ...ui, fontScale: v })} format={(v) => `${Math.round(v * 100)}%`} />} />
    </Panel>
  );
}

function CloudCostSettings({ ctx }: { ctx: SetCtx }) {
  const { draft, set, save } = ctx;
  const [costs, setCosts] = useState<any>(null);
  const load = () => api.costs().then(setCosts).catch(() => setCosts(null));
  useEffect(() => { load(); }, []);
  const money = (v: number) => `$${(Number(v) || 0).toFixed(4)}`;
  const toks = (b: any) => `${b.calls} call${b.calls === 1 ? "" : "s"} \u00b7 ${(b.prompt_tokens + b.completion_tokens).toLocaleString()} tokens`;
  return (
    <Panel icon="zap" title="Cloud costs" sub="Spend \u00b7 budgets \u00b7 per-model" right={<Btn small onClick={load}>Refresh</Btn>}>
      <SetRow title="Today" sub={costs?.today ? toks(costs.today) + (costs.today.unknown_pricing ? " \u00b7 some calls have unknown pricing" : "") : "\u2026"}
        control={<b style={{ color: costs?.budgets?.daily_over ? "var(--danger)" : "inherit" }}>{costs?.today ? money(costs.today.cost_usd) : "\u2026"}</b>} />
      <SetRow title="This month" sub={costs?.month ? toks(costs.month) + (costs.month.unknown_pricing ? " \u00b7 some calls have unknown pricing" : "") : "\u2026"}
        control={<b style={{ color: costs?.budgets?.monthly_over ? "var(--danger)" : "inherit" }}>{costs?.month ? money(costs.month.cost_usd) : "\u2026"}</b>} />
      <SetRow title="Daily cap (USD)" sub="Cloud calls stop when today's spend hits this. 0 = unlimited."
        control={<input type="number" min={0} step={0.5} style={{ width: 110 }} value={Number(draft.cost_daily_cap_usd ?? 0)}
          onChange={(e) => set("cost_daily_cap_usd", Math.max(0, Number(e.target.value) || 0))} aria-label="daily cost cap" />} />
      <SetRow title="Monthly cap (USD)" sub="Same gate for the calendar month (UTC)."
        control={<input type="number" min={0} step={1} style={{ width: 110 }} value={Number(draft.cost_monthly_cap_usd ?? 0)}
          onChange={(e) => set("cost_monthly_cap_usd", Math.max(0, Number(e.target.value) || 0))} aria-label="monthly cost cap" />} />
      <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
        <Btn small kind="violet" onClick={() => save({ cost_daily_cap_usd: draft.cost_daily_cap_usd ?? 0, cost_monthly_cap_usd: draft.cost_monthly_cap_usd ?? 0 }, "Budgets saved")}>Save caps</Btn>
      </div>
      {costs?.by_model?.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>Top models</div>
          {costs.by_model.slice(0, 6).map((m: any) => (
            <div key={`${m.provider}:${m.model}`} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "2px 0" }}>
              <span className="muted" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "70%" }}>
                {m.model} <span style={{ opacity: 0.6 }}>({m.provider} \u00b7 {m.calls})</span>
              </span>
              <span>{m.unknown_pricing && m.cost_usd === 0 ? "unknown" : money(m.cost_usd)}</span>
            </div>))}
        </div>)}
    </Panel>
  );
}

const VOICE_SAMPLE = "Jambo! This is AURA \u2014 warm, human, and full of feeling. How does this voice sound to you?";

function VoiceSettings({ ctx }: { ctx: SetCtx }) {
  const { draft, set, save } = ctx;
  const { data: veng } = useFetch(() => api.voice.engines());
  const { speak, toast } = useStore();
  const [sysVoices, setSysVoices] = useState<SpeechSynthesisVoice[]>([]);
  useEffect(() => {
    const load = () => { try { setSysVoices(speechSynthesis.getVoices()); } catch { /* noop */ } };
    load();
    try { speechSynthesis.onvoiceschanged = load; } catch { /* noop */ }
  }, []);
  const engine = (draft.voice_engine || "browser") as string;
  const engInfo = (veng?.engines || []).find((e) => e.id === engine);
  const vkey = voicePreferenceKey(engine);
  const opts = engine === "browser"
    ? sysVoices.map((v) => ({ id: v.name, label: `${v.name} (${v.lang})` }))
    : (engInfo?.voices || []).map((v) => ({ id: v.id, label: v.label }));
  const blocked = engine === "edge" && (draft.privacy || "local-first") === "local-first";
  return (
    <Panel icon="mic" title="Voice" sub="Engines \u00b7 voices \u00b7 emotions">
      <SetRow title="Engine" sub={engInfo?.note || "\u2026"}
        control={<Seg options={[{ v: "browser", label: "Browser" }, { v: "piper", label: "Piper" }, { v: "kokoro", label: "Kokoro" }, { v: "edge", label: "Edge Neural" }]}
          value={engine} onPick={(v) => save({ voice_engine: v }, "Voice engine saved")} />} />
      {blocked && <Row icon="shield" title="Edge needs Hybrid or Cloud privacy"
        sub="Local-first never sends your text to Microsoft. Switch privacy in AI Engine & Cloud." />}
      {engInfo && !engInfo.available && engine !== "browser" && !blocked &&
        <Row icon="x" title="Engine unavailable"
          sub={engInfo.note || "Install the optional server voice dependencies."} />}
      <SetRow title="Voice" control={<select aria-label="voice" value={(draft[vkey] || "") as string}
        onChange={(e) => save({ [vkey]: e.target.value }, "Voice saved")}>
        {engine === "browser" && <option value="">System default</option>}
        {opts.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>} />
      <SetRow title="Emotion" sub="Full acting on Edge Neural US voices \u00b7 tone everywhere else."
        control={<select aria-label="emotion" value={(draft.voice_emotion || "neutral") as string}
          onChange={(e) => save({ voice_emotion: e.target.value }, "Emotion saved")}>
          {(veng?.emotions || [{ id: "neutral", label: "Neutral" }]).map((e) => <option key={e.id} value={e.id}>{e.label}</option>)}
        </select>} />
      <SetRow title="Recognition language" control={<select value={(draft.voice_lang || "en-KE") as string}
        onChange={(e) => save({ voice_lang: e.target.value })}>{["en-KE", "sw-KE", "en-US", "en-GB"].map((l) => <option key={l} value={l}>{l}</option>)}</select>} />
      <SetRow title="Speech rate" control={<Slider value={Number(draft.voice_rate ?? 1)} min={0.5} max={2} step={0.05}
        onPick={(v) => set("voice_rate", v)} format={(v) => `${v.toFixed(2)}\u00d7`} />} />
      <SetRow title="Pitch" control={<Slider value={Number(draft.voice_pitch ?? 1)} min={0.5} max={2} step={0.05}
        onPick={(v) => set("voice_pitch", v)} format={(v) => `${v.toFixed(2)}\u00d7`} />} />
      <SetRow title="Smart breaks" sub="Natural pauses between sentences and paragraphs."
        control={<Toggle on={draft.voice_breaks !== false} onFlip={() => save({ voice_breaks: draft.voice_breaks === false })} label="breaks" />} />
      <SetRow title="Autoplay replies" sub="Read every answer aloud."
        control={<Toggle on={!!draft.voice_autoplay} onFlip={() => save({ voice_autoplay: !draft.voice_autoplay })} label="autoplay" />} />
      <SetRow title="Wake word" sub="\u201chey jarvis\u201d starts listening in Live Conversation. Off = tap Talk."
        control={<Toggle on={!!draft.wake_enabled} onFlip={() => save({ wake_enabled: !draft.wake_enabled })} label="wake" />} />
      {!!draft.wake_enabled && (
        <SetRow title="Wake sensitivity" control={<Slider value={Number(draft.wake_threshold ?? 0.5)} min={0.1} max={0.95} step={0.05}
          onPick={(v) => set("wake_threshold", v)} format={(v) => v.toFixed(2)} />} />
      )}
      <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
        <Btn small kind="violet" onClick={() => save({ voice_rate: draft.voice_rate ?? 1, voice_pitch: draft.voice_pitch ?? 1 }, "Voice saved")}>Save rate + pitch</Btn>
        <Btn small onClick={() => { try { speak(VOICE_SAMPLE); } catch (e) { toast(`Test failed: ${e instanceof Error ? e.message : e}`, "error"); } }}>Test voice</Btn>
      </div>
    </Panel>
  );
}

export function BrowserAlertSettings() {
  const [ui, setUiState] = useState<UiPrefs>(loadUiPrefs());
  const setUi = (p: UiPrefs) => { setUiState(p); saveUiPrefs(p); };
  return (
    <Panel icon="bell" title="Browser alerts" sub="Stored in this browser only">
      <SetRow title="Alert sound" sub="Play a chime when a toast or approval arrives (skips quiet hours)."
        control={<Toggle on={ui.alertSound} onFlip={() => setUi({ ...ui, alertSound: !ui.alertSound })} label="Alert sound" />} />
      <SetRow title="Desktop approval alerts" sub="System notification for new approvals while AURA is in the background. Uses the browser's existing permission."
        control={<Toggle on={ui.desktopApprovalAlerts} onFlip={() => setUi({ ...ui, desktopApprovalAlerts: !ui.desktopApprovalAlerts })} label="Desktop approval alerts" />} />
      <div style={{ marginTop: 8, display: "flex", gap: 8, alignItems: "center" }}>
        <Btn small kind="violet" onClick={() => void playAlertSound(true)}>Test sound</Btn>
      </div>
    </Panel>
  );
}

export function SettingsView() {
  const { t, lang, setLang } = useLang();
  const { me, refresh, toast } = useStore();
  const { data: health } = useFetch(() => api.health());
  const { data: tools } = useFetch(() => api.tools());
  const { data: preset } = useFetch(() => api.settings.get());
  const [draft, setDraft] = useState<Record<string, any>>({});
  const [secrets, setSecrets] = useState<Record<string, boolean>>({});
  const [sources, setSources] = useState<Record<string, string>>({});
  const [pushOn, setPushOn] = useState<string | null>(null);
  const [pushCfg, setPushCfg] = useState<boolean | null>(null);
  useEffect(() => {
    currentSubscription().then((s) => setPushOn(s ? s.endpoint.slice(-12) : "")).catch(() => setPushOn(""));
    api.push.vapidKey().then((r) => setPushCfg(r.configured)).catch(() => setPushCfg(false));
  }, []);
  useEffect(() => {
    if (preset) { setDraft({ ...preset.values }); setSecrets({ ...preset.secrets }); setSources({ ...preset.sources }); setServerCache(preset.values); }
  }, [preset]);
  const set = (k: string, v: unknown) => setDraft((d) => ({ ...d, [k]: v }));
  const save = async (body: Record<string, unknown>, msg = "Saved") => {
    try {
      const r = await api.settings.update(body);
      setDraft({ ...r.values }); setSecrets({ ...r.secrets }); setSources({ ...r.sources });
      setServerCache(r.values);
      toast(msg, "success"); refresh();
    } catch (e) { toast(`Save failed: ${e instanceof Error ? e.message : e}`, "error"); }
  };
  const ctx: SetCtx = { draft, set, secrets, sources, save };
  if (!preset) return (<div className="view"><div className="vhead"><h2><Icon n="gear" s={20} /> {t("title.settings")}</h2></div><Skel /><Skel /></div>);
  return (
    <div className="view">
      <div className="vhead"><h2><Icon n="gear" s={20} /> {t("title.settings")}</h2><Pill c="violet">v{me?.version || ""}</Pill></div>
      <CloudAISettings ctx={ctx} />
      <CloudCostSettings ctx={ctx} />
      <div className="grid2">
        <AppearanceSettings />
        <Panel icon="chat" title="Language & Chat" sub="Locale \u00b7 composer behavior">
          <SetRow title={t("set.language")} sub={t("set.languagesub")}
            control={<select value={lang} onChange={(e) => setLang(e.target.value as "en" | "sw")}><option value="en">English</option><option value="sw">Kiswahili</option></select>} />
          <SetRow title="Streaming replies" sub="Typewriter effect while AURA answers."
            control={<Toggle on={!!draft.chat_streaming} onFlip={() => save({ chat_streaming: !draft.chat_streaming })} label="streaming" />} />
          <SetRow title="SSE batching" sub="Coalesce streamed tokens to cut render churn (0 = every token)."
            control={<Slider value={Number(draft.sse_batch_ms ?? 40)} min={0} max={200} step={10}
              onPick={(v) => set("sse_batch_ms", v)} format={(v) => (v === 0 ? "off" : `${v}ms`)} />} />
          <SetRow title="Enter sends" sub="Off: Enter adds a line, Ctrl+Enter sends."
            control={<Toggle on={draft.enter_to_send !== false} onFlip={() => save({ enter_to_send: draft.enter_to_send === false })} label="enter to send" />} />
          <SetRow title="Message timestamps" sub="Show time under each message."
            control={<Toggle on={!!draft.chat_timestamps} onFlip={() => { save({ chat_timestamps: !draft.chat_timestamps }); }} label="timestamps" />} />
        </Panel>
        <PersonalitySettings draft={draft} save={save} />
        <VoiceSettings ctx={ctx} />
        <Panel icon="bell" title="Notifications" sub="Toasts \u00b7 quiet hours \u00b7 push">
          <SetRow title="Toast duration" control={<Slider value={Number(draft.toast_duration_ms ?? 4200)} min={1500} max={10000} step={500}
            onPick={(v) => set("toast_duration_ms", v)} format={(v) => `${(v / 1000).toFixed(1)}s`} />} />
          <SetRow title="Quiet hours" sub="Push suppressed overnight (your timezone)."
            control={<span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
              <input type="time" value={(draft.quiet_start || "") as string} onChange={(e) => set("quiet_start", e.target.value)} />
              <small className="dim">\u2192</small>
              <input type="time" value={(draft.quiet_end || "") as string} onChange={(e) => set("quiet_end", e.target.value)} />
            </span>} />
          <div style={{ marginTop: 8 }}><Btn small kind="violet" onClick={() => save({ toast_duration_ms: draft.toast_duration_ms ?? 4200, quiet_start: draft.quiet_start || "", quiet_end: draft.quiet_end || "" }, "Notifications saved")}>Save</Btn></div>
          <small className="secttl2">Push {pushCfg === false ? "(server keys not configured)" : ""}</small>
          {!pushSupported() && <Empty title="Push not supported" sub="Use Chrome/Edge on HTTPS or localhost." />}
          {pushSupported() && pushOn === null && <Skel />}
          {pushSupported() && pushOn !== null && (
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <Pill c={pushOn ? "green" : "amber"}>{pushOn ? `subscribed \u2026${pushOn}` : "off"}</Pill>
              {!pushOn && <Btn small kind="violet" onClick={async () => { try { const r = await subscribePush(); setPushOn(r.endpoint.slice(-12)); toast("Push enabled", "success"); } catch (e) { toast(`${e instanceof Error ? e.message : e}`, "error"); } }}>Enable push</Btn>}
              {!!pushOn && <Btn small onClick={async () => { await unsubscribePush(); setPushOn(""); toast("Push disabled", "success"); }}>Disable</Btn>}
              {!!pushOn && <Btn small onClick={async () => { try { await api.push.test({ title: "AURA test", body: "Push is wired up." }); toast("Test push sent", "success"); } catch (e) { toast(`${e instanceof Error ? e.message : e}`, "error"); } }}>Send test</Btn>}
            </div>
          )}
        </Panel>
        <BrowserAlertSettings />
        <Panel icon="shield" title="Data & Privacy" sub="Memory policy \u00b7 retention \u00b7 device sync">
          <SetRow title="Device name" sub="Labels sync bundles from this device."
            control={<span style={{ display: "inline-flex", gap: 6 }}>
              <Field value={(draft.device_name || "") as string} onChange={(e) => set("device_name", e.target.value)} placeholder="aura-main" />
              <Btn small kind="violet" onClick={() => save({ device_name: draft.device_name || "aura-main" }, "Device saved")}>Save</Btn>
            </span>} />
          <SetRow title="Timezone" sub="Drives quiet hours, calendar days and briefings."
            control={<span style={{ display: "inline-flex", gap: 6 }}>
              <select aria-label="Timezone" value={(draft.timezone || "Africa/Nairobi") as string} onChange={(e) => set("timezone", e.target.value)}>
                {ONBOARD_ZONES.map((z) => <option key={z} value={z}>{z}</option>)}
              </select>
              <Btn small kind="violet" onClick={() => save({ timezone: draft.timezone || "Africa/Nairobi" }, "Timezone saved")}>Save</Btn>
            </span>} />
          <SetRow title="Onboarding" sub="Replay the first-run setup wizard."
            control={<Btn small onClick={async () => {
              await api.settings.update({ onboarded: false });
              window.location.reload();
            }}>Replay</Btn>} />
          <SetRow title="Device sync" sub="Export a bundle here, import it on another device. Merge by name/title — local wins conflicts."
            control={<span style={{ display: "inline-flex", gap: 6 }}>
              <Btn small onClick={async () => {
                const b = await api.sync.export((draft.device_name as string) || "web");
                const blob = new Blob([JSON.stringify(b)], { type: "application/json" });
                const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
                a.download = `aura-sync-${Date.now()}.json`; a.click();
                toast("Sync bundle exported (no credentials inside)", "success");
              }}>Export</Btn>
              <label><Btn small>Import<input type="file" accept="application/json" hidden onChange={async (e) => {
                const f = e.target.files?.[0]; if (!f) return;
                try {
                  const bundle = JSON.parse(await f.text());
                  const r = await api.sync.import(bundle, (draft.device_name as string) || "web");
                  const conf = Object.values(r.tables).reduce((a, t) => a + t.conflicts, 0);
                  toast(`Merged ${r.inserted} rows \u00b7 ${conf} conflicts kept local`, conf ? "warn" : "success");
                  refresh();
                } catch (err) { toast(`Import failed: ${err instanceof Error ? err.message : err}`, "error"); }
              }} /></Btn></label>
            </span>} />
          <SetRow title="Auto-store memories" sub="AURA extracts durable facts from chat."
            control={<Toggle on={draft.memory_auto_store !== false} onFlip={() => save({ memory_auto_store: draft.memory_auto_store === false })} label="auto-store" />} />
          <SetRow title="Worker pool size" sub="How many jobs AURA runs at once (1-8). Only matters once something enqueues work."
            control={<Slider value={Number(draft.worker_pool_size ?? 3)} min={1} max={8} step={1}
              onPick={(v) => set("worker_pool_size", v)} format={(v) => `${v}`} />} />
          <SetRow title="Job retries" sub="Attempts before a job is dead-lettered (0-5)."
            control={<Slider value={Number(draft.worker_max_retries ?? 3)} min={0} max={5} step={1}
              onPick={(v) => set("worker_max_retries", v)} format={(v) => `${v}`} />} />
          {/* A Slider only edits the draft; without this the two controls above
              would be permanently invisible, saving the wrong rows silently. */}
          <div style={{ marginTop: 8 }}><Btn small kind="violet" onClick={() => save({
            worker_pool_size: draft.worker_pool_size ?? 3,
            worker_max_retries: draft.worker_max_retries ?? 3,
          }, "Worker settings saved")}>Save worker settings</Btn></div>
          <SetRow title="Memory consolidation" sub="Nightly dedupe and re-scoring of your memory."
            control={<Toggle on={draft.consolidate_enabled !== false}
              onFlip={() => save({ consolidate_enabled: draft.consolidate_enabled === false })}
              label="consolidation" />} />
          <SetRow title="Observability retention" sub="Activity/audit/tool logs older than this are pruned nightly. Never touches your content."
            control={<Slider value={Number(draft.retention_days ?? 90)} min={0} max={365} step={5}
              onPick={(v) => set("retention_days", v)} format={(v) => (v === 0 ? "forever" : `${v}d`)} />} />
          <div style={{ marginTop: 8 }}><Btn small kind="violet" onClick={() => save({ retention_days: draft.retention_days ?? 90 }, "Retention saved")}>Save retention</Btn></div>
        </Panel>
        <Panel icon="users" title="Profile & Local LFM" sub="Local-first identity">
          <Row icon="users" title={me?.name || "\u2014"} sub={me?.role} />
          <Row icon="target" title={me?.location || "\u2014"} sub="Home timezone Africa/Nairobi" />
          <div style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
            <Field value={(draft.ollama_base_url || "") as string} onChange={(e) => set("ollama_base_url", e.target.value)} placeholder="Ollama URL" />
            <Field value={(draft.ollama_chat_model || "") as string} onChange={(e) => set("ollama_chat_model", e.target.value)} placeholder="Chat model" />
            <Field value={(draft.ollama_vision_model || "") as string} onChange={(e) => set("ollama_vision_model", e.target.value)} placeholder="Vision model" />
          </div>
          <SetRow title="Image understanding" sub="Describe attached images with the vision model (local first, cloud when allowed)."
            control={<Toggle on={draft.vision_enabled !== false} onFlip={() => save({ vision_enabled: draft.vision_enabled === false })} label="vision" />} />
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <Btn small kind="violet" onClick={() => save({ ollama_base_url: draft.ollama_base_url, ollama_chat_model: draft.ollama_chat_model, ollama_vision_model: draft.ollama_vision_model }, "Local LFM saved")}>Save LFM</Btn>
            <Btn small onClick={async () => { await refresh(); toast("Refreshed", "success"); }}><Icon n="refresh" s={14} /> Refresh status</Btn>
          </div>
        </Panel>
        <Panel icon="cpu" title="Inference Router" sub="Live backend status">
          {(health?.services || []).map((s) => (
            <Row key={s.name} icon={s.status === "online" ? "check" : "alert"} title={s.name} sub={s.detail}
              right={<Pill c={s.status === "online" ? "green" : s.status === "degraded" ? "amber" : "red"}>{s.status}</Pill>} />
          ))}
          <small className="dim">uptime {Math.round((health?.metrics.uptime_s || 0) / 60)}m \u00b7 runs/24h {health?.metrics.runs_24h} \u00b7 avg {health?.metrics.avg_run_ms}ms \u00b7 tools ok {health?.metrics.tools_ok} / err {health?.metrics.tools_err}</small>
        </Panel>
        <Panel icon="alert" title="About & Danger Zone" sub={`AURA OS v${me?.version || ""} \u00b7 single-user \u00b7 local-first`}>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Btn small onClick={async () => {
              const [h, s] = await Promise.all([api.health(), fetch("/api/system").then((r) => r.json()).catch(() => ({}))]);
              const blob = new Blob([JSON.stringify({ exported_at: new Date().toISOString(), health: h, system: s }, null, 2)], { type: "application/json" });
              const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "aura-diagnostics.json"; a.click();
              toast("Diagnostics downloaded", "success");
            }}>Download diagnostics</Btn>
            <Btn small onClick={async () => {
              if (!confirm("Reset ALL settings to defaults? Cloud keys stay until forgotten.")) return;
              const r = await api.settings.reset();
              setDraft({ ...r.values }); setSecrets({ ...r.secrets }); setSources({ ...r.sources }); setServerCache(r.values);
              toast("Settings reset to defaults", "success"); refresh();
            }}>Reset settings</Btn>
          </div>
          <small className="dim">Reset clears server overrides (env config still applies). Appearance lives in this browser only.</small>
        </Panel>
      </div>
      {/* AC-CMD-003: every command with its category, description and example. */}
      <CommandsView />
      <Panel icon="zap" title={`Hermes Tools (${tools?.tools.length || 0})`} sub={`Embedded runtime v${tools?.hermes || "2.0.0"} \u00b7 risk-gated`}>
        <div className="toolgrid">
          {(tools?.tools || []).map((t) => (
            <div key={t.name} className="tool"><code>{t.name}</code><small>{t.description}</small><Pill c={t.risk === "R0" ? "blue" : t.risk === "R1" ? "green" : t.risk === "R2" ? "amber" : "red"}>{t.risk}</Pill></div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
