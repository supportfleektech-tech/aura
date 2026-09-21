/* AURA OS workspaces II — Memory, Voice, Gateway, Automations, Activity, Files, Settings. */
import { useEffect, useRef, useState } from "react";
import { ago, api, GwIntegration, Memory, Mission } from "./api";
import { useStore } from "./store";
import { useLang } from "./i18n";
import { currentSubscription, pushSupported, subscribePush, unsubscribePush } from "./push";
import { Field, useFetch } from "./views1";
import { BriefingsPanel } from "./views3";
import { ONBOARD_ZONES } from "./Onboarding";
import { ApprovalCard, Btn, ChatThread, Composer, Dot, Empty, Icon, Panel, Pill, Row, Seg, SetRow, Skel, Slider, Toggle, Waveform } from "./ui";
import { Accent, applyUiPrefs, getServer, loadUiPrefs, saveUiPrefs, setServerCache, UiPrefs, voicePreferenceKey } from "./prefs";
import { PersonalitySettings } from "./PersonalitySettings";
import { playAlertSound } from "./alerts";
import { CallHistoryPanel, WatchPanel } from "./views4";

/* ============================== MEMORY ============================== */
export function MemoryView() {
  const { t } = useLang();
  const { toast, refresh } = useStore();
  const [q, setQ] = useState("");
  const [domain, setDomain] = useState("");
  const [mtype, setMtype] = useState("");
  const [list, setList] = useState<Memory[]>([]);
  const [stats, setStats] = useState<{ total: number; by_domain: Record<string, number> }>({ total: 0, by_domain: {} });
  const [title, setTitle] = useState(""); const [content, setContent] = useState("");
  const load = async () => {
    const qs = `?q=${encodeURIComponent(q)}${domain ? `&domain=${domain}` : ""}${mtype ? `&mtype=${mtype}` : ""}`;
    const r = await api.memories.list(qs).catch(() => null);
    if (r) { setList(r.memories); setStats(r.stats); }
  };
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const hybrid = async () => {
    if (q.trim().length < 2) { load(); return; }
    const r = await api.memories.search({ query: q, limit: 12 }).catch(() => null);
    if (r) setList(r.results);
  };
  return (
    <div className="view">
      <div className="vhead"><h2><Icon n="search" s={20} /> {t("title.memory")}</h2><Pill c="violet">{stats.total} memories</Pill></div>
      <div className="actionstrip">
        <input className="grow" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && hybrid()} placeholder="Hybrid search: FTS5 + vector + rerank…" />
        <select value={domain} onChange={(e) => setDomain(e.target.value)}><option value="">all domains</option>{["general", "career", "clients", "personal"].map((d) => <option key={d} value={d}>{d}</option>)}</select>
        <select value={mtype} onChange={(e) => setMtype(e.target.value)}><option value="">all types</option>{["episodic", "semantic", "procedural", "preference", "context"].map((d) => <option key={d} value={d}>{d}</option>)}</select>
        <Btn small kind="violet" onClick={hybrid}>Search</Btn>
        <Btn small onClick={async () => { if (!q.trim()) return; if (!confirm(`Forget everything about "${q}"?`)) return; const r = await api.memories.forget(q); toast(`Forgot ${r.forgotten} memories`, "warn"); load(); refresh(); }}>Forget topic</Btn>
      </div>
      <div className="grid2">
        <Panel icon="db" title="Memories" sub="Confidence · importance · source · why used">
          {list.map((m) => <MemCard key={m.id} m={m} onDone={load} />)}
          {list.length === 0 && <Empty title="No memories match" sub="Tell AURA to remember things as you chat." />}
        </Panel>
        <Panel icon="plus" title="Store Memory" sub="Explicit long-term knowledge">
          <Field value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title" />
          <textarea className="ta" rows={4} value={content} onChange={(e) => setContent(e.target.value)} placeholder="What should AURA never forget?" />
          <div style={{ display: "flex", gap: 8 }}>
            <select value={domain} onChange={(e) => setDomain(e.target.value)}><option value="general">general</option><option value="career">career</option><option value="clients">clients</option><option value="personal">personal</option></select>
            <Btn small kind="green" onClick={async () => { if (!content.trim()) return; await api.memories.create({ title: title || content.slice(0, 50), content, domain: domain || "general" }); setTitle(""); setContent(""); load(); refresh(); toast("Memory stored", "success"); }}>Store</Btn>
            <Btn small onClick={() => {
              const blob = new Blob([JSON.stringify(list, null, 2)], { type: "application/json" });
              const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "aura-memories.json"; a.click();
            }}>Export</Btn>
          </div>
          <small className="secttl">By domain</small>
          {Object.entries(stats.by_domain).map(([d, c]) => <Row key={d} icon="folder" title={d} right={<Pill c="blue">{c}</Pill>} />)}
        </Panel>
      </div>
      <ChatThread compact /><Composer />
    </div>
  );
}

function MemCard({ m, onDone }: { m: Memory; onDone: () => void }) {
  const [edit, setEdit] = useState(false);
  const [body, setBody] = useState(m.content);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const source = m.source.startsWith("user-corrected:") ? `Corrected by you · original source: ${m.source.slice(15)}` : `Source: ${m.source}`;
  const save = async () => {
    if (saving || !body.trim() || body.trim() === m.content) return;
    setSaving(true); setError("");
    try { await api.memories.update(m.id, { content: body.trim() }); setEdit(false); onDone(); }
    catch (e) { setError(`Correction failed: ${e instanceof Error ? e.message : e}`); }
    finally { setSaving(false); }
  };
  return (
    <div className="entitycard">
      <header><div><strong>{m.title}</strong><small>{m.mtype} · {m.domain} · {source} · {ago(m.created_at)}</small></div>
        <div style={{ display: "flex", gap: 4 }}>
          {m.relevance != null && <Pill c="green">{Math.round(m.relevance * 100)}%</Pill>}
          <Pill c={m.sensitivity === "normal" ? "blue" : "amber"}>{m.sensitivity}</Pill>
        </div>
      </header>
      {edit ? <><label>Corrected content<textarea className="ta" rows={3} value={body} disabled={saving} onChange={(e) => setBody(e.target.value)} /></label><small className="dim">Saving replaces this memory and reindexes it for search. The original source is retained and marked as corrected by you.</small></> : <p>{m.content}</p>}
      {error && <p role="alert">{error}</p>}
      {m.why_used && <small className="dim">Why used: {m.why_used}</small>}
      <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
        <small className="dim">conf {m.confidence.toFixed(2)} · imp {m.importance.toFixed(2)}</small>
        <span style={{ flex: 1 }} />
        {edit
          ? <><Btn small kind="green" disabled={saving || !body.trim() || body.trim() === m.content} onClick={() => void save()}>{saving ? "Saving…" : "Save correction"}</Btn><Btn small disabled={saving} onClick={() => { setEdit(false); setError(""); }}>Cancel</Btn></>
          : <><button className="xbtn" aria-label={`Correct ${m.title}`} onClick={() => { setBody(m.content); setError(""); setEdit(true); }}><Icon n="edit" s={14} /></button>
            <button className="xbtn" aria-label={`Delete ${m.title}`} onClick={async () => { if (confirm("Delete this memory?")) { await api.memories.remove(m.id); onDone(); } }}><Icon n="trash" s={14} /></button></>}
      </div>
    </div>
  );
}

/* ============================== VOICE ============================== */
const CAP_WORKLET = `class Cap extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch && ch.length) {
      const ratio = sampleRate / 16000;
      const out = new Int16Array(Math.floor(ch.length / ratio));
      for (let i = 0; i < out.length; i++) {
        const s = ch[Math.min(ch.length - 1, Math.floor(i * ratio))] || 0;
        out[i] = Math.max(-32768, Math.min(32767, Math.round(s * 32767)));
      }
      this.port.postMessage(out.buffer, [out.buffer]);
    }
    return true;
  }
}
registerProcessor("aura-cap", Cap);`;

export function VoiceLoopPanel() {
  const { toast } = useStore();
  const { data: st } = useFetch(() => api.voice.loopStatus());
  const [on, setOn] = useState(false);
  const [state, setState] = useState("off");
  const [tapMode, setTapMode] = useState(false);
  const [lines, setLines] = useState<{ who: string; text: string }[]>([]);
  const R = useRef<{ ws: WebSocket | null; stream: MediaStream | null; ctx: AudioContext | null; el: HTMLAudioElement | null; lastAnswer: string }>({ ws: null, stream: null, ctx: null, el: null, lastAnswer: "" });

  const generationRef = useRef(0);
  const activeRef = useRef(false);
  const audioGenerationRef = useRef(0);
  const audioUrlRef = useRef<string | null>(null);
  const workletUrlRef = useRef<string | null>(null);
  const nodeRef = useRef<AudioWorkletNode | null>(null);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);

  function stopAudio() {
    audioGenerationRef.current += 1;
    const el = R.current.el;
    R.current.el = null;
    if (el) {
      el.onended = null; el.onerror = null;
      try { el.pause(); el.removeAttribute("src"); el.load(); } catch {}
    }
    if (audioUrlRef.current) URL.revokeObjectURL(audioUrlRef.current);
    audioUrlRef.current = null;
    if (utteranceRef.current) { utteranceRef.current.onend = null; utteranceRef.current.onerror = null; }
    utteranceRef.current = null;
    try { speechSynthesis.cancel(); } catch {}
  }
  function played() {
    try { if (activeRef.current && R.current.ws?.readyState === 1) R.current.ws.send("played"); } catch {}
  }
  function browserSpeak(text: string) {
    if (!activeRef.current) return;
    stopAudio();
    const generation = audioGenerationRef.current;
    const finish = () => { if (activeRef.current && generation === audioGenerationRef.current) { stopAudio(); played(); } };
    try {
      const u = new SpeechSynthesisUtterance(text);
      utteranceRef.current = u;
      u.onend = finish;
      u.onerror = finish;
      speechSynthesis.speak(u);
    } catch { finish(); }
  }
  function cleanup() {
    activeRef.current = false;
    generationRef.current += 1;
    stopAudio();
    const ws = R.current.ws;
    if (ws) {
      ws.onopen = null; ws.onmessage = null; ws.onclose = null; ws.onerror = null;
      try { if (ws.readyState === 1) ws.send("stop"); } catch {}
      try { ws.close(); } catch {}
    }
    if (nodeRef.current) { nodeRef.current.port.onmessage = null; try { nodeRef.current.disconnect(); } catch {} }
    nodeRef.current = null;
    if (workletUrlRef.current) URL.revokeObjectURL(workletUrlRef.current);
    workletUrlRef.current = null;
    try { R.current.stream?.getTracks().forEach((tr) => tr.stop()); } catch {}
    try { void R.current.ctx?.close().catch(() => undefined); } catch {}
    R.current = { ws: null, stream: null, ctx: null, el: null, lastAnswer: "" };
  }
  useEffect(() => () => cleanup(), []);
  function stopAll() {
    cleanup();
    setOn(false);
    setState("off");
  }
  function playReply(data: ArrayBuffer) {
    if (!activeRef.current) return;
    stopAudio();
    const generation = audioGenerationRef.current;
    const current = () => activeRef.current && generation === audioGenerationRef.current;
    const fallback = () => { if (current()) browserSpeak(R.current.lastAnswer); };
    try {
      const url = URL.createObjectURL(new Blob([data]));
      audioUrlRef.current = url;
      const el = new Audio(url);
      R.current.el = el;
      el.onended = () => { if (current()) { stopAudio(); played(); } };
      el.onerror = fallback;
      void el.play().catch(fallback);
    } catch { fallback(); }
  }
  async function start() {
    if (activeRef.current) return;
    if (!st?.whisper) { toast("Server STT not installed — pip install -r backend/requirements-voice.txt", "error"); return; }
    if (!navigator.mediaDevices?.getUserMedia) { toast("Microphone unavailable in this browser", "error"); return; }
    activeRef.current = true;
    const generation = ++generationRef.current;
    const current = () => activeRef.current && generation === generationRef.current;
    setOn(true);
    setState("connecting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      if (!current()) { stream.getTracks().forEach((tr) => tr.stop()); return; }
      R.current.stream = stream;
      const ws = new WebSocket(api.voice.loopWsUrl());
      R.current.ws = ws;
      ws.binaryType = "arraybuffer";
      ws.onopen = async () => {
        if (!current()) return;
        try {
          const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
          const ctx = new Ctx({ sampleRate: 16000 });
          R.current.ctx = ctx;
          const url = URL.createObjectURL(new Blob([CAP_WORKLET], { type: "application/javascript" }));
          workletUrlRef.current = url;
          try { await ctx.audioWorklet.addModule(url); }
          finally { if (workletUrlRef.current === url) { URL.revokeObjectURL(url); workletUrlRef.current = null; } }
          if (!current()) return;
          const src = ctx.createMediaStreamSource(stream);
          const node = new AudioWorkletNode(ctx, "aura-cap");
          nodeRef.current = node;
          node.port.onmessage = (e: MessageEvent) => { if (current() && ws.readyState === 1) ws.send(e.data); };
          src.connect(node);
          setOn(true);
          setState("connecting");
        } catch (e) { toast(`Audio capture failed: ${e instanceof Error ? e.message : e}`, "error"); stopAll(); }
      };
      ws.onmessage = (e) => {
        if (!current()) return;
        if (typeof e.data !== "string") { playReply(e.data); return; }
        let m: { t?: string; state?: string; text?: string; followup?: boolean; tap_to_talk?: boolean; wake?: boolean; stage?: string };
        try { m = JSON.parse(e.data); } catch { return; }
        if (m.t === "hello") {
          setTapMode(!!m.tap_to_talk);
          setState(m.wake ? "sleeping · say “hey jarvis”" : "tap Talk, then speak");
        } else if (m.t === "state") {
          setState(m.state === "listening" && m.followup ? "listening · follow-up" : (m.state || ""));
        } else if (m.t === "wake") {
          setState("listening");
        } else if (m.t === "barge") {
          stopAudio();
          setState("listening");
          toast("Interrupted — I'm listening", "info");
        } else if (m.t === "transcript" && m.text) {
          setLines((l) => [...l.slice(-9), { who: "you", text: m.text || "" }]);
        } else if (m.t === "answer" && m.text) {
          R.current.lastAnswer = m.text;
          setLines((l) => [...l.slice(-9), { who: "aura", text: m.text || "" }]);
        } else if (m.t === "error" && m.stage === "speak" && R.current.lastAnswer) {
          browserSpeak(R.current.lastAnswer);
        } else if (m.t === "error") {
          toast(`Voice loop: ${m.stage || "error"}`, "warn");
        }
      };
      ws.onclose = () => { setOn(false); setState("off"); };
      ws.onerror = () => toast("Voice loop connection failed", "error");
    } catch { toast("Microphone unavailable", "error"); }
  }
  const pill: "green" | "violet" | "amber" | "blue" = state.startsWith("speaking") ? "green" : state.startsWith("listening") ? "violet" : state === "thinking" ? "amber" : "blue";
  return (
    <Panel icon="mic" title="Live Conversation" sub="Always-on voice loop · server STT + TTS">
      {!st && <Skel />}
      {st && !st.whisper && <Empty title="Server voice not installed" sub="pip install -r backend/requirements-voice.txt" />}
      {st?.whisper && (
        <>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <Pill c={pill}>{state}</Pill>
            {!on
              ? <Btn small kind="green" onClick={() => void start()}>Start live loop</Btn>
              : <><Btn small kind="red" onClick={stopAll}>Stop</Btn>
                {(state === "thinking" || state.startsWith("speaking")) && <Btn small onClick={stopAll}>Stop speaking</Btn>}
                <Btn small kind="violet" onClick={() => { try { R.current.ws?.send("talk"); } catch { /* noop */ } }}>Talk</Btn></>}
          </div>
          <small className="dim">{st.wake_available && st.wake_enabled
            ? "Say “hey jarvis” — I'm listening. Say it while I talk to interrupt."
            : st.wake_available
              ? "Wake word installed but off — enable it in Settings, or tap Talk."
              : "Wake word not installed — tap Talk and speak (silence still end-points you)."}</small>
          {tapMode && on && <small className="dim">Tap-to-talk mode this session.</small>}
          {lines.map((l, i) => <Row key={i} icon={l.who === "you" ? "mic" : "spark"} title={l.who === "you" ? "You" : "AURA"} sub={l.text.slice(0, 160)} />)}
        </>
      )}
    </Panel>
  );
}

export function VoiceView() {
  const { t } = useLang();
  const { listening, toggleListen, transcript, speak, speaking, stopSpeak, send, toast, setCall } = useStore();
  const { data } = useFetch(() => api.voice.config());
  const { data: vstat } = useFetch(() => api.voice.status());
  const [say, setSay] = useState("Hello Antony. Your AI sidekick is ready.");
  const [srvText, setSrvText] = useState("");
  const [rec, setRec] = useState<MediaRecorder | null>(null);
  const [audioUrl, setAudioUrl] = useState("");
  return (
    <div className="view">
      <div className="vhead"><h2><Icon n="mic" s={20} /> {t("title.voice")}</h2><Pill c={listening ? "violet" : "blue"}>{listening ? "Listening…" : "Idle"}</Pill></div>
      <div className="callcta">
        <Btn kind="violet" onClick={() => setCall(true)}><Icon n="phone" s={15} /> Call AURA — hands-free voice</Btn>
        <small className="dim">Talk like a phone call: it listens, answers out loud, and you can interrupt. Works best in Chrome/Edge; uses your local Whisper loop when configured.</small>
      </div>
      <div className="grid2">
        <Panel icon="mic" title="Voice Session" sub="Push-to-talk · live transcript · interruption">
          <Waveform active={listening} bars={56} h={64} />
          <div className="voicebtns big">
            <button className={`bigmic ${listening ? "live" : ""}`} onClick={() => toggleListen()}>{<Icon n="mic" s={26} />}</button>
          </div>
          <p className="center">{listening ? (transcript || "Listening… speak now") : "Tap the microphone and speak — your words become a message to AURA."}</p>
          <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
            <Btn small onClick={() => send("what can you do?")}>Try: “what can you do?”</Btn>
            <Btn small onClick={() => send("plan my day")}>Try: “plan my day”</Btn>
          </div>
        </Panel>
        <Panel icon="wave" title="Speech Output" sub={data?.tts || "browser TTS"}>
          <textarea className="ta" rows={4} value={say} onChange={(e) => setSay(e.target.value)} />
          <div style={{ display: "flex", gap: 8 }}>
            <Btn small kind="violet" onClick={() => speak(say)}>{speaking ? "Speaking…" : "Speak"}</Btn>
            <Btn small onClick={stopSpeak}>Stop</Btn>
          </div>
          <small className="secttl">Engine</small>
          <Row icon="cpu" title="STT: Web Speech (on-device where available)" sub={data?.note} />
          <Row icon="wave" title="TTS: system voices" sub={`Language ${data?.language || "en-KE"}`} />
        </Panel>
      </div>
      <div className="grid2">
        <VoiceLoopPanel />
        <Panel icon="cpu" title="Server STT" sub={vstat ? `whisper ${vstat.whisper_model}${vstat.whisper_ready ? " · loaded" : ""}` : "checking…"}>
          {vstat && !vstat.stt_installed && <Empty title="Not installed" sub="pip install -r backend/requirements-voice.txt" />}
          {vstat?.stt_installed && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              {!rec && <Btn small kind="violet" onClick={async () => {
                try {
                  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                  const mr = new MediaRecorder(stream);
                  const chunks: Blob[] = [];
                  mr.ondataavailable = (e) => chunks.push(e.data);
                  mr.onstop = async () => {
                    stream.getTracks().forEach((tr) => tr.stop());
                    try {
                      const r = await api.voice.transcribe(new Blob(chunks, { type: "audio/webm" }));
                      setSrvText(r.text); toast(`Heard (${r.duration}s)`, "success");
                    } catch (e) { toast(`${e instanceof Error ? e.message : e}`, "error"); }
                  };
                  mr.start(); setRec(mr);
                } catch { toast("Microphone unavailable", "error"); }
              }}>● Record</Btn>}
              {rec && <Btn small kind="red" onClick={() => { rec.stop(); setRec(null); }}>■ Stop & transcribe</Btn>}
              <label><Btn small>Upload audio<input type="file" accept="audio/*" hidden onChange={async (e) => {
                const f = e.target.files?.[0]; if (!f) return;
                try { const r = await api.voice.transcribe(f); setSrvText(r.text); toast("Transcribed", "success"); }
                catch (err) { toast(`${err instanceof Error ? err.message : err}`, "error"); }
              }} /></Btn></label>
            </div>
          )}
          {srvText && <><p style={{ marginTop: 8 }}>“{srvText}”</p><Btn small kind="green" onClick={() => send(srvText)}>Send to chat →</Btn></>}
        </Panel>
        <Panel icon="wave" title="Server TTS" sub={vstat ? vstat.piper_voice : "checking…"}>
          {vstat && !vstat.tts_installed && <Empty title="Not installed" sub="pip install -r backend/requirements-voice.txt" />}
          {vstat?.tts_installed && (
            <div style={{ display: "flex", gap: 8 }}>
              <Field value={say} onChange={(e) => setSay(e.target.value)} placeholder="Text to speak…" />
              <Btn small kind="violet" onClick={async () => {
                try {
                  const eng = String(getServer("voice_engine", "browser"));
                  setAudioUrl(await api.voice.speakUrl(say, {
                    engine: eng === "browser" ? "piper" : eng,
                    emotion: String(getServer("voice_emotion", "neutral")),
                  }));
                } catch (e) { toast(`${e instanceof Error ? e.message : e}`, "error"); }
              }}>Speak</Btn>
            </div>
          )}
          {audioUrl && <audio controls src={audioUrl} style={{ width: "100%", marginTop: 8 }} />}
        </Panel>
      </div>
      <CallHistoryPanel />
      <ChatThread compact /><Composer />
    </div>
  );
}

/* ============================== GATEWAY ============================== */
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
            {g.platform === "telegram" && <Btn small onClick={async () => { try { const r = await api.gateway.telegramPoll(); r.ok ? toast(r.inbound?.length ? `${r.inbound.length} new message(s)${r.replies ? ` · ${r.replies} auto-replied` : ""}` : "No new messages", "success") : toast(`Poll: ${r.error || ""}`, "error"); } catch (e) { toast(`Poll failed: ${e instanceof Error ? e.message : e}`, "error"); } reload(); }}>Check messages</Btn>}</>
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
          {(g.platform === "telegram" || g.platform === "whatsapp") && <small className="dim">Inbound: POST /api/gateway/{g.platform}/webhook{g.platform === "whatsapp" ? " · verify via GET with hub.mode/hub.verify_token/hub.challenge" : " · secret header x-telegram-bot-api-secret-token"} — needs a public URL; polling needs none.</small>}
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
      r.ok ? toast(`${entity_id || service} → ${r.state || r.mode || "ok"}`, "success") : toast(r.error || "failed", "error");
    } catch (e) { toast(`${e instanceof Error ? e.message : e}`, "error"); }
    reload();
  };
  return (
    <div className="view">
      <div className="vhead"><h2><Icon n="home" s={20} /> {t("title.smarthome")}</h2>
        <Pill c={connected ? "green" : "amber"}>{st ? st.status : "…"}</Pill>
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
              {mode === "live" && <small className="dim">HA → your profile → Long-Lived Access Tokens. Token never leaves the server.</small>}
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
                try { const r = await api.gateway.test("homeassistant"); r.ok ? toast(`HA ok — ${r.latency_ms}ms${r.detail ? ` · ${r.detail}` : ""}`, "success") : toast(r.error || "test failed", "error"); }
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

/* ============================== AUTOMATIONS ============================== */
function BriefKindPick({ action, kind, setKind, bid, setBid }: { action: string; kind: string; setKind: (v: string) => void; bid: string; setBid: (v: string) => void }) {
  const { data } = useFetch(() => api.brief.list());
  if (action !== "brief") return null;
  return (<>
    <select value={kind} onChange={(e) => setKind(e.target.value)}>
      <option value="morning">morning</option><option value="evening">evening</option><option value="weekly">weekly</option><option value="custom">custom</option>
    </select>
    <select value={bid} onChange={(e) => setBid(e.target.value)}>
      <option value="">ad-hoc digest</option>
      {(data?.briefings || []).map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
    </select>
  </>);
}

const MISSION_HINTS = ["plan my day", "inbox zero", "follow up", "backup", "brief me", "weekly review"];

const MISSION_RISKS: Record<string, string> = { R0: "read-only", R1: "local changes run after Start", R2: "external action; separate approval required", R3: "high risk; separate approval required", R4: "prohibited; will not execute" };
type MissionTools = Awaited<ReturnType<typeof api.tools>>["tools"];
type MissionApprovals = Awaited<ReturnType<typeof api.approvals.list>>["approvals"];

function MissionCard({ m, reload, tools, approvals }: { m: Mission; reload: () => void; tools: MissionTools; approvals: MissionApprovals }) {
  const { toast, setView } = useStore();
  const [busy, setBusy] = useState(false);
  const riskFor = (s: Mission["steps"][number]) => s.kind === "send_drafts" ? "R2" : tools.find((t) => t.name === s.tool)?.risk;
  const reviewable = m.steps.every((s) => { const risk = riskFor(s); return risk && risk !== "R4" && Boolean(MISSION_RISKS[risk]); });
  const review = m.steps.map((s, i) => `${i + 1}. ${s.tool || s.kind} [${riskFor(s) || "unknown"}]\n${JSON.stringify(s.kind === "send_drafts" ? { drafts_from: s.drafts_from ?? 0 } : s.args || {}, null, 2)}`).join("\n\n");
  const done = m.steps.filter((s) => s.status === "done" || s.status === "skipped").length;
  const pill: "green" | "amber" | "violet" | "blue" | "red" = m.status === "done" ? "green" : m.status === "failed" ? "red" : m.status === "awaiting" ? "amber" : m.status === "running" ? "violet" : "blue";
  const act = async (action: string, ok: string) => {
    if (busy) return;
    if (action === "start" && (!reviewable || !confirm(`Start ${m.goal}?\n\n${review}\n\nR0/R1 steps run without further approval. R2/R3 and draft sends pause for separate approval. Starting does not approve sending.`))) return;
    setBusy(true);
    try { await api.automations.controlMission(m.id, action); reload(); toast(ok, "success"); }
    catch (e) { toast(`${e instanceof Error ? e.message : e}`, "error"); }
    finally { setBusy(false); }
  };
  let every = "off";
  try { every = JSON.parse(m.schedule_json || "{}").every || "off"; } catch { /* keep off */ }
  const { data: runsData } = useFetch(() => api.automations.missionRuns(m.id));
  const lastRun = (runsData?.runs || [])[0];
  const sched = async (val: string) => {
    try { await api.automations.scheduleMission(m.id, val); reload(); toast(val === "off" ? "Schedule cleared" : `Runs ${val}`, "success"); }
    catch (e) { toast(`${e instanceof Error ? e.message : e}`, "error"); }
  };
  return (
    <div className="entitycard">
      <header><div><strong>{m.goal}</strong><small>{done}/{m.steps.length} steps · {ago(m.created_at)}{m.needs_review ? " · needs review" : ""}</small></div>
        <Pill c={pill}>{m.status}</Pill></header>
      <small className="dim">Review tools and arguments before Start. R0/R1 steps run without further approval; R2/R3 and draft sends pause. Starting is not approval to send.</small>
      {m.steps.map((s, i) => {
        const risk = riskFor(s);
        const approval = s.status === "awaiting" ? approvals.find((a) => a.id === s.approval_id && a.status === "pending") : undefined;
        return <div key={i}>
          <Row icon={s.status === "done" ? "check" : s.status === "failed" ? "x" : s.status === "awaiting" ? "clock" : s.status === "skipped" ? "minus" : i === m.step_idx && m.status === "running" ? "play" : "circle"}
            title={`${i + 1}. ${s.label}`} sub={[s.tool || s.kind, s.status, s.note].filter(Boolean).join(" · ")} />
          <small>{risk ? `${risk} · ${MISSION_RISKS[risk] || "Risk unavailable"}` : "Risk unavailable — reload the tool catalog before starting."}</small>
          {s.kind === "send_drafts" ? <p>Drafts from step {(s.drafts_from ?? 0) + 1}. Exact recipients and messages are available for review when this step pauses, before sending.</p> : <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(s.args || {}, null, 2)}</pre>}
          {approval && <div><strong>Approval #{approval.id} · {approval.risk} · {approval.title}</strong><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(approval.detail, null, 2)}</pre></div>}
        </div>;
      })}
      {m.status === "awaiting" && <><small className="amber">Waiting on you — resolve the approval in Activity → Approvals. No pending action is auto-approved.</small><Btn small onClick={() => setView("activity")}>Review approvals</Btn></>}
      {m.status === "done" && m.result && <small className="dim">{m.result.slice(0, 200)}</small>}
      {m.status === "failed" && m.result && <small className="red">{m.result.slice(0, 200)}</small>}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        <small className="dim">repeat</small>
        <select value={every} onChange={(e) => void sched(e.target.value)} aria-label="repeat schedule">
          {["off", "hourly", "daily", "weekly"].map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        {m.next_run_at ? <small className="dim">next {m.next_run_at.slice(0, 16).replace("T", " ")}</small> : null}
        {lastRun ? <small className="dim">{`last run: ${lastRun.status}${lastRun.summary ? ` · ${lastRun.summary.slice(0, 60)}` : ""}`}</small> : null}
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {(m.status === "draft" || m.status === "paused") && m.steps.length > 0 && <Btn small kind="green" disabled={busy || !reviewable} onClick={() => void act("start", "Mission started")}>Start</Btn>}
        {m.status === "running" && <Btn small onClick={() => void act("pause", "Mission paused")}>Pause</Btn>}
        {["draft", "running", "awaiting", "paused"].includes(m.status) && <Btn small onClick={() => void act("cancel", "Mission cancelled")}>Cancel</Btn>}
      </div>
    </div>
  );
}

export function MissionsPanel() {
  const { data, reload } = useFetch(() => api.automations.missions());
  const { data: catalog, reload: reloadCatalog } = useFetch(() => api.tools());
  const { data: approvals, reload: reloadApprovals } = useFetch(() => api.approvals.list());
  const { toast } = useStore();
  const [goal, setGoal] = useState("");
  return (
    <Panel icon="rocket" title="Missions" sub="Delegate a goal — AURA runs the steps, asks when it matters">
      <div style={{ display: "flex", gap: 8 }}>
        <Field value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="e.g. plan my day" />
        <Btn small kind="violet" onClick={async () => {
          if (!goal.trim()) return;
          try {
            const r = await api.automations.planMission(goal.trim());
            setGoal(""); reload();
            toast(r.message, r.steps.length ? "success" : "warn");
          } catch (e) { toast(`${e instanceof Error ? e.message : e}`, "error"); }
        }}>Plan</Btn>
        <Btn small onClick={async () => {
          if (!goal.trim()) return;
          try {
            const r = await api.automations.planMission(goal.trim(), "llm");
            setGoal(""); reload();
            toast(r.message, r.steps.length ? "success" : "warn");
          } catch (e) { toast(`${e instanceof Error ? e.message : e}`, "error"); }
        }}>✨ AI plan</Btn>
      </div>
      <div style={{ display: "flex", gap: 6, marginTop: 6, flexWrap: "wrap" }}>
        {MISSION_HINTS.map((h) => <Btn key={h} small onClick={() => setGoal(h)}>{h}</Btn>)}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 8 }}>
        <Btn small onClick={() => { reload(); reloadCatalog(); reloadApprovals(); }}>Refresh mission details</Btn>
        {(data?.missions || []).map((m) => <MissionCard key={m.id} m={m} reload={() => { reload(); reloadApprovals(); }} tools={catalog?.tools || []} approvals={approvals?.approvals || []} />)}
        {(data?.missions || []).length === 0 && <Empty title="No missions yet" sub="Plan one above — R0/R1 steps run alone, R2+ asks first." />}
      </div>
    </Panel>
  );
}

export function AutomationsView() {
  const { t } = useLang();
  const { data, reload } = useFetch(() => api.automations.list());
  const { toast } = useStore();
  const [name, setName] = useState(""); const [every, setEvery] = useState("daily"); const [action, setAction] = useState("notify"); const [whUrl, setWhUrl] = useState(""); const [whSecret, setWhSecret] = useState(""); const [briefKind, setBriefKind] = useState("morning"); const [briefId, setBriefId] = useState("");
  return (
    <div className="view">
      <div className="vhead"><h2><Icon n="zap" s={20} /> {t("title.automations")}</h2></div>
      <BriefingsPanel />
      <MissionsPanel />
      <Panel icon="plus" title="New Automation" sub="Trigger → action with history & retry">
        <div style={{ display: "flex", gap: 8 }}>
          <Field value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Evening shutdown review" />
          <select value={every} onChange={(e) => setEvery(e.target.value)}><option value="hourly">hourly</option><option value="daily">daily</option><option value="weekly">weekly</option></select>
          <select value={action} onChange={(e) => setAction(e.target.value)}><option value="notify">notify</option><option value="backup">backup</option><option value="chat">log</option><option value="brief">LLM brief</option><option value="proactive">proactive scan</option><option value="webhook">webhook</option></select>
          <BriefKindPick action={action} kind={briefKind} setKind={setBriefKind} bid={briefId} setBid={setBriefId} />
          <Btn small kind="violet" onClick={async () => { if (!name.trim()) return; if (action === "webhook" && !whUrl.trim()) { toast("Webhook needs a URL", "warn"); return; } try { const act = action === "webhook" ? { url: whUrl.trim(), secret: whSecret.trim() } : action === "brief" ? { kind: briefKind, ...(briefId ? { briefing_id: Number(briefId) } : {}) } : {}; await api.automations.create({ name: name.trim(), trigger_kind: "schedule", trigger: { every }, action_kind: action, action: act, next_run: new Date(Date.now() + 864e5).toISOString() }); setName(""); setWhUrl(""); setWhSecret(""); reload(); toast("Automation created", "success"); } catch (e) { toast(`Create failed: ${e instanceof Error ? e.message : e}`, "error"); } }}>{t("c.create")}</Btn>
        </div>
        {action === "webhook" && <div style={{ display: "flex", gap: 8, marginTop: 8 }}><Field value={whUrl} onChange={(e) => setWhUrl(e.target.value)} placeholder="https://... (signed POST on fire)" /><Field value={whSecret} onChange={(e) => setWhSecret(e.target.value)} placeholder="Signing secret (optional)" /></div>}
      </Panel>
      <Panel icon="zap" title="Automations" sub="Status · next run · success rate">
        {(data?.automations || []).map((a) => {
          const total = a.success_count + a.fail_count;
          return (
            <div key={a.id} className="entitycard">
              <header><div><strong>{a.name}</strong><small>{a.trigger_kind} · {a.action_kind} · next {a.next_run ? ago(a.next_run) : "—"} · last {a.last_run ? ago(a.last_run) : "never"}</small></div>
                <Pill c={a.status === "active" ? "green" : "amber"}>{a.status}</Pill></header>
              <small className="dim">{a.success_count} ok · {a.fail_count} failed{total > 0 ? ` · ${Math.round((a.success_count / total) * 100)}% success` : ""}</small>
              <div style={{ display: "flex", gap: 6 }}>
                <Btn small onClick={async () => { await api.automations.run(a.id); reload(); toast("Automation fired", "success"); }}><Icon n="play" s={13} /> {t("c.runnow")}</Btn>
                <Btn small onClick={async () => { try { const r = await api.automations.dryRun(a.id); toast(`Dry run ${r.fired?.ok ? "would fire" : "would fail"}${(r.blocked || []).length ? ` — ${(r.blocked || [])[0]}` : ""}`, r.fired?.ok ? "success" : "warn"); } catch { toast("Dry run failed", "warn"); } }}>Dry</Btn>
                <Btn small onClick={async () => { await api.automations.update(a.id, { status: a.status === "active" ? "paused" : "active" }); reload(); }}>{a.status === "active" ? t("c.pause") : t("c.resume")}</Btn>
                <Btn small onClick={async () => { if (confirm("Delete automation?")) { await api.automations.remove(a.id); reload(); } }}><Icon n="trash" s={13} /></Btn>
              </div>
            </div>
          );
        })}
      </Panel>
    </div>
  );
}

/* ============================== ACTIVITY ============================== */
export function ActivityView() {
  const { t } = useLang();
  const [kind, setKind] = useState("");
  const { data, reload } = useFetch(() => api.activity(kind ? `?kind=${kind}` : ""), [kind]);
  const { data: ap, reload: rap } = useFetch(() => api.approvals.list());
  const sev = (s: string) => (s === "success" ? "green" : s === "warn" ? "amber" : s === "error" ? "red" : "blue");
  return (
    <div className="view">
      <div className="vhead"><h2><Icon n="clock" s={20} /> {t("title.activity")}</h2>
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">all types</option>{["message", "run", "tool", "memory", "task", "project", "client", "integration", "automation", "approval", "backup", "system"].map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
      </div>
      {(ap?.approvals?.length || 0) > 0 && (
        <Panel icon="shield" title={`Pending Approvals (${ap!.approvals.length})`} sub="R2/R3 actions wait for you">
          {ap!.approvals.map((a) => <ApprovalCard key={a.id} approval={{ id: a.id, risk: a.risk, title: a.title, drafts: a.detail.drafts || [] }} onDone={() => { rap(); reload(); }} />)}
        </Panel>
      )}
      <Panel icon="clock" title="Unified Feed" sub="Messages · runs · tools · memory · entities · system">
        {(data?.activity || []).map((a) => (
          <div key={a.id} className="feedrow">
            <Dot c={sev(a.severity)} />
            <div><strong>{a.title}</strong><small>{a.detail.slice(0, 140)}</small></div>
            <span style={{ flex: 1 }} /><Pill c="blue">{a.kind}</Pill><small className="dim">{ago(a.created_at)}</small>
          </div>
        ))}
        {(data?.activity || []).length === 0 && <Empty title="No activity" sub="AURA logs everything here." />}
      </Panel>
    </div>
  );
}

/* ============================== FILES ============================== */
export function LookPanel() {
  const { toast } = useStore();
  const { data: st } = useFetch(() => api.vision.status());
  const [q, setQ] = useState("");
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ description: string; model: string; ms: number } | null>(null);
  const [camOn, setCamOn] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  function stopStream() {
    try { streamRef.current?.getTracks().forEach((tr) => tr.stop()); } catch { /* noop */ }
    streamRef.current = null;
    setCamOn(false);
  }
  useEffect(() => () => stopStream(), []);
  async function send(blob: Blob | null) {
    if (!blob) { toast("Capture failed", "error"); return; }
    setBusy(true);
    try {
      const r = await api.vision.look(blob, q, remember);
      setResult(r);
      toast(`Described with ${r.model}`, "success");
    } catch (e) { toast(`${e instanceof Error ? e.message : e}`, "error"); }
    finally { setBusy(false); }
  }
  function snap(video: HTMLVideoElement | null): Promise<Blob | null> {
    return new Promise((resolve) => {
      try {
        const v = video;
        if (!v || !v.videoWidth) { resolve(null); return; }
        const c = document.createElement("canvas");
        c.width = v.videoWidth; c.height = v.videoHeight;
        c.getContext("2d")?.drawImage(v, 0, 0);
        c.toBlob((b) => resolve(b), "image/jpeg", 0.85);
      } catch { resolve(null); }
    });
  }
  async function startCamera() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
      streamRef.current = stream;
      setCamOn(true);
      setTimeout(() => { if (videoRef.current) { videoRef.current.srcObject = stream; void videoRef.current.play().catch(() => undefined); } }, 50);
    } catch { toast("Camera unavailable", "error"); }
  }
  async function captureScreen() {
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: true });
      const v = document.createElement("video");
      v.srcObject = stream;
      await v.play().catch(() => undefined);
      await new Promise((r) => setTimeout(r, 400));
      const blob = await snap(v);
      stream.getTracks().forEach((tr) => tr.stop());
      await send(blob);
    } catch { toast("Screen capture cancelled or unavailable", "warn"); }
  }
  return (
    <Panel icon="eye" title="Look" sub="Live senses — camera or screen, described by vision">
      {!st && <Skel />}
      {st && (
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <Pill c={st.available ? "green" : "amber"}>{st.available ? `vision ready · ${st.ollama_online ? `ollama/${st.ollama_model}` : "cloud"}` : "no vision model"}</Pill>
        </div>
      )}
      {st && !st.available && <small className="dim">Start Ollama with {st.ollama_model} (or configure cloud vision) to switch this on.</small>}
      <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
        <Field value={q} onChange={(e) => setQ(e.target.value)} placeholder="What do you see? (optional question)" />
      </div>
      <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
        {!camOn && <Btn small kind="violet" disabled={busy} onClick={() => void startCamera()}>📷 Camera</Btn>}
        {camOn && <Btn small kind="green" disabled={busy} onClick={async () => { const b = await snap(videoRef.current); stopStream(); await send(b); }}>{busy ? "Looking…" : "Capture"}</Btn>}
        {camOn && <Btn small onClick={stopStream}>Cancel</Btn>}
        <Btn small disabled={busy} onClick={() => void captureScreen()}>🖥️ Screenshot</Btn>
        <label><Btn small disabled={busy}>📎 Upload frame<input type="file" accept="image/*" hidden onChange={async (e) => { const f = e.target.files?.[0]; if (f) await send(f); e.target.value = ""; }} /></Btn></label>
        <label style={{ display: "flex", gap: 6, alignItems: "center" }}><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /><small>remember</small></label>
      </div>
      {camOn && <video ref={videoRef} style={{ width: "100%", maxHeight: 320, marginTop: 8, borderRadius: 8 }} muted playsInline />}
      {result && <Row icon="eye" title={`${result.model} · ${result.ms}ms`} sub={result.description.slice(0, 400)} />}
    </Panel>
  );
}

export function FilesView() {
  const { t } = useLang();
  const { data, reload } = useFetch(() => api.files.list());
  const { toast } = useStore();
  const [analysis, setAnalysis] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState<number | null>(null);
  const analyze = async (id: number) => {
    setBusy(id);
    try {
      const r = await api.files.analyze(id);
      setAnalysis((a) => ({ ...a, [id]: r.description }));
      toast(`Described with ${r.model}`, "success");
    } catch (e) { toast(`Vision failed: ${e instanceof Error ? e.message : e}`, "error"); }
    finally { setBusy(null); }
  };
  return (
    <div className="view">
      <div className="vhead"><h2><Icon n="folder" s={20} /> {t("title.files")}</h2></div>
      <LookPanel />
      <Panel icon="plus" title="Upload" sub="PDF · DOCX · CSV · TXT · images · audio — text is indexed into memory">
        <input type="file" multiple onChange={async (e) => { if (!e.target.files?.length) return; await api.files.upload(e.target.files); toast("Uploaded & indexed", "success"); reload(); }} />
      </Panel>
      <Panel icon="folder" title="Library" sub={`${(data?.files || []).length} files`}>
        {(data?.files || []).map((f) => (
          <div key={f.id}>
            <Row icon={f.mime.startsWith("image") ? "image" : "file"} title={f.name} sub={`${(f.size / 1024).toFixed(1)} KB · ${ago(f.created_at)}${(f.analysis_count || 0) > 0 ? ` · 👁 ${f.analysis_count}` : ""}`}
              right={<span style={{ display: "inline-flex", gap: 6 }}>
                {f.mime.startsWith("image") && <Btn small disabled={busy === f.id} onClick={() => analyze(f.id)}>{busy === f.id ? "Seeing…" : "Analyze"}</Btn>}
                <a className="btn sm" href={`/api/files/${f.id}`} download>Download</a>
              </span>} />
            {analysis[f.id] && <div className="muted" style={{ fontSize: 13, padding: "2px 4px 8px 40px" }}>{analysis[f.id]}</div>}
          </div>
        ))}
        {(data?.files || []).length === 0 && <Empty title="No files yet" sub="Upload documents for AURA to read." />}
      </Panel>
      <WatchPanel />
    </div>
  );
}

/* ============================== SETTINGS ============================== */
const FREE_PRESETS = [
  { id: "google/gemma-4-31b-it:free", name: "Gemma 4 31B · multimodal general" },
  { id: "openrouter/free", name: "Free Models Router · auto-picks a free model" },
  { id: "nvidia/nemotron-3-ultra-550b-a55b:free", name: "Nemotron 3 Ultra · 1M-context reasoning" },
  { id: "nvidia/nemotron-3-super-120b-a12b:free", name: "Nemotron 3 Super · long-context reasoning" },
  { id: "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free", name: "Nemotron 3 Omni · multimodal reasoning" },
  { id: "nvidia/nemotron-3.5-lightning:free", name: "Nemotron 3.5 Lightning · fast 1M general" },
  { id: "google/gemma-4-26b-a4b-it:free", name: "Gemma 4 26B · fast multimodal" },
  { id: "thinkingmachines/inkling:free", name: "Inkling · 1M general" },
  { id: "cohere/north-mini-code:free", name: "North Mini Code · coding" },
  { id: "poolside/laguna-s-2.1:free", name: "Laguna S 2.1 · coding agent" },
  { id: "poolside/laguna-xs-2.1:free", name: "Laguna XS 2.1 · fast coding" },
  { id: "liquid/lfm-2.5-2.6b:free", name: "LFM 2.5 2.6B · tiny + fast" },
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
      const list = (free.length ? free : r.models).slice(0, 120).map((m) => ({ id: m.id, name: `${m.name} · ${m.free ? "free" : "paid"} · ${(m.context_length / 1024).toFixed(0)}k` }));
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
      toast(r.ok ? `Cloud OK — ${r.model} · ${r.latency_ms}ms` : `Cloud test failed: ${r.error || "no reply"}`, r.ok ? "success" : "error");
    } catch (e) { toast(`Test failed: ${e instanceof Error ? e.message : e}`, "error"); }
    finally { setTesting(false); }
  };
  const doSave = async () => {
    const body: Record<string, unknown> = {
      cloud_provider: provider, privacy: draft.privacy, cloud_temperature: draft.cloud_temperature,
      cloud_max_tokens: draft.cloud_max_tokens, cloud_memory_policy: draft.cloud_memory_policy,
      [modelKey]: model,
    };
    if (provider === "custom") body.custom_base_url = draft.custom_base_url;
    if (tkey.trim()) body[keyKey] = tkey.trim();
    await save(body, "AI engine saved");
    setTkey("");
  };
  return (
    <Panel icon="cpu" title="AI Engine & Cloud" sub="Local LFM → cloud → builtin composer chain"
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
          placeholder={keySet ? `API key saved ${sources[keyKey] === "env" ? "(from env)" : ""} — type a new one to replace` : "Paste API key…"} />
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
        {provider === "openrouter" && !customMode ? (
          <select value={model} onChange={(e) => set(modelKey, e.target.value)} style={{ flex: 1, minWidth: 220 }}>
            {!model && <option value="">select a model…</option>}
            {opts.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        ) : (
          <Field value={model} onChange={(e) => set(modelKey, e.target.value)} placeholder="model id, e.g. google/gemma-4-31b-it:free" />
        )}
        {provider === "openrouter" && <>
          <Btn small onClick={() => setCustomMode(!customMode)}>{customMode ? "Presets" : "Custom"}</Btn>
          <Btn small onClick={loadLive} disabled={loadingModels}>{loadingModels ? "Loading…" : "↻ Live list"}</Btn>
        </>}
      </div>
      {provider === "openrouter" && <small className="dim">{listNote} — free models rotate; the live list is authoritative.</small>}
      <div style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap", alignItems: "center" }}>
        <Btn small kind="violet" onClick={doSave}>Save engine</Btn>
        <Btn small onClick={doTest} disabled={testing}>{testing ? "Testing…" : "Test connection"}</Btn>
        {keySet && <Btn small onClick={async () => { if (!confirm("Forget the saved key?")) return; await save({ [keyKey]: "" }, "Key forgotten"); }}>Forget key</Btn>}
        {testRes && (testRes.ok
          ? <Pill c="green">ok · {testRes.latency_ms}ms{testRes.reply ? ` · “${testRes.reply}”` : ""}</Pill>
          : <Pill c="red">failed · {(testRes.error || "").slice(0, 90)}</Pill>)}
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
    <Panel icon="spark" title="Appearance" sub="Instant preview · stored in this browser">
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
  const toks = (b: any) => `${b.calls} call${b.calls === 1 ? "" : "s"} · ${(b.prompt_tokens + b.completion_tokens).toLocaleString()} tokens`;
  return (
    <Panel icon="zap" title="Cloud costs" sub="Spend · budgets · per-model" right={<Btn small onClick={load}>Refresh</Btn>}>
      <SetRow title="Today" sub={costs?.today ? toks(costs.today) + (costs.today.unknown_pricing ? " · some calls have unknown pricing" : "") : "…"}
        control={<b style={{ color: costs?.budgets?.daily_over ? "var(--danger)" : "inherit" }}>{costs?.today ? money(costs.today.cost_usd) : "…"}</b>} />
      <SetRow title="This month" sub={costs?.month ? toks(costs.month) + (costs.month.unknown_pricing ? " · some calls have unknown pricing" : "") : "…"}
        control={<b style={{ color: costs?.budgets?.monthly_over ? "var(--danger)" : "inherit" }}>{costs?.month ? money(costs.month.cost_usd) : "…"}</b>} />
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
                {m.model} <span style={{ opacity: 0.6 }}>({m.provider} · {m.calls})</span>
              </span>
              <span>{m.unknown_pricing && m.cost_usd === 0 ? "unknown" : money(m.cost_usd)}</span>
            </div>))}
        </div>)}
    </Panel>
  );
}

const VOICE_SAMPLE = "Jambo! This is AURA — warm, human, and full of feeling. How does this voice sound to you?";

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
    <Panel icon="mic" title="Voice" sub="Engines · voices · emotions">
      <SetRow title="Engine" sub={engInfo?.note || "…"}
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
      <SetRow title="Emotion" sub="Full acting on Edge Neural US voices · tone everywhere else."
        control={<select aria-label="emotion" value={(draft.voice_emotion || "neutral") as string}
          onChange={(e) => save({ voice_emotion: e.target.value }, "Emotion saved")}>
          {(veng?.emotions || [{ id: "neutral", label: "Neutral" }]).map((e) => <option key={e.id} value={e.id}>{e.label}</option>)}
        </select>} />
      <SetRow title="Recognition language" control={<select value={(draft.voice_lang || "en-KE") as string}
        onChange={(e) => save({ voice_lang: e.target.value })}>{["en-KE", "sw-KE", "en-US", "en-GB"].map((l) => <option key={l} value={l}>{l}</option>)}</select>} />
      <SetRow title="Speech rate" control={<Slider value={Number(draft.voice_rate ?? 1)} min={0.5} max={2} step={0.05}
        onPick={(v) => set("voice_rate", v)} format={(v) => `${v.toFixed(2)}×`} />} />
      <SetRow title="Pitch" control={<Slider value={Number(draft.voice_pitch ?? 1)} min={0.5} max={2} step={0.05}
        onPick={(v) => set("voice_pitch", v)} format={(v) => `${v.toFixed(2)}×`} />} />
      <SetRow title="Smart breaks" sub="Natural pauses between sentences and paragraphs."
        control={<Toggle on={draft.voice_breaks !== false} onFlip={() => save({ voice_breaks: draft.voice_breaks === false })} label="breaks" />} />
      <SetRow title="Autoplay replies" sub="Read every answer aloud."
        control={<Toggle on={!!draft.voice_autoplay} onFlip={() => save({ voice_autoplay: !draft.voice_autoplay })} label="autoplay" />} />
      <SetRow title="Wake word" sub="“Hey jarvis” starts listening in Live Conversation. Off = tap Talk."
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
        <Panel icon="chat" title="Language & Chat" sub="Locale · composer behavior">
          <SetRow title={t("set.language")} sub={t("set.languagesub")}
            control={<select value={lang} onChange={(e) => setLang(e.target.value as "en" | "sw")}><option value="en">English</option><option value="sw">Kiswahili</option></select>} />
          <SetRow title="Streaming replies" sub="Typewriter effect while AURA answers."
            control={<Toggle on={!!draft.chat_streaming} onFlip={() => save({ chat_streaming: !draft.chat_streaming })} label="streaming" />} />
          <SetRow title="Enter sends" sub="Off: Enter adds a line, Ctrl+Enter sends."
            control={<Toggle on={draft.enter_to_send !== false} onFlip={() => save({ enter_to_send: draft.enter_to_send === false })} label="enter to send" />} />
          <SetRow title="Message timestamps" sub="Show time under each message."
            control={<Toggle on={!!draft.chat_timestamps} onFlip={() => { save({ chat_timestamps: !draft.chat_timestamps }); }} label="timestamps" />} />
        </Panel>
        <PersonalitySettings draft={draft} save={save} />
        <VoiceSettings ctx={ctx} />
        <Panel icon="bell" title="Notifications" sub="Toasts · quiet hours · push">
          <SetRow title="Toast duration" control={<Slider value={Number(draft.toast_duration_ms ?? 4200)} min={1500} max={10000} step={500}
            onPick={(v) => set("toast_duration_ms", v)} format={(v) => `${(v / 1000).toFixed(1)}s`} />} />
          <SetRow title="Quiet hours" sub="Push suppressed overnight (your timezone)."
            control={<span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
              <input type="time" value={(draft.quiet_start || "") as string} onChange={(e) => set("quiet_start", e.target.value)} />
              <small className="dim">→</small>
              <input type="time" value={(draft.quiet_end || "") as string} onChange={(e) => set("quiet_end", e.target.value)} />
            </span>} />
          <div style={{ marginTop: 8 }}><Btn small kind="violet" onClick={() => save({ toast_duration_ms: draft.toast_duration_ms ?? 4200, quiet_start: draft.quiet_start || "", quiet_end: draft.quiet_end || "" }, "Notifications saved")}>Save</Btn></div>
          <small className="secttl2">Push {pushCfg === false ? "(server keys not configured)" : ""}</small>
          {!pushSupported() && <Empty title="Push not supported" sub="Use Chrome/Edge on HTTPS or localhost." />}
          {pushSupported() && pushOn === null && <Skel />}
          {pushSupported() && pushOn !== null && (
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <Pill c={pushOn ? "green" : "amber"}>{pushOn ? `subscribed …${pushOn}` : "off"}</Pill>
              {!pushOn && <Btn small kind="violet" onClick={async () => { try { const r = await subscribePush(); setPushOn(r.endpoint.slice(-12)); toast("Push enabled", "success"); } catch (e) { toast(`${e instanceof Error ? e.message : e}`, "error"); } }}>Enable push</Btn>}
              {!!pushOn && <Btn small onClick={async () => { await unsubscribePush(); setPushOn(""); toast("Push disabled", "success"); }}>Disable</Btn>}
              {!!pushOn && <Btn small onClick={async () => { try { await api.push.test({ title: "AURA test", body: "Push is wired up." }); toast("Test push sent", "success"); } catch (e) { toast(`${e instanceof Error ? e.message : e}`, "error"); } }}>Send test</Btn>}
            </div>
          )}
        </Panel>
        <BrowserAlertSettings />
        <Panel icon="shield" title="Data & Privacy" sub="Memory policy · retention · device sync">
          <SetRow title="Device name" sub="Labels sync bundles from this device."
            control={<span style={{ display: "inline-flex", gap: 6 }}>
              <Field value={(draft.device_name || "") as string} onChange={(e) => set("device_name", e.target.value)} placeholder="aura-main" />
              <Btn small kind="violet" onClick={() => save({ device_name: draft.device_name || "aura-main" }, "Device saved")}>Save</Btn>
            </span>} />
          <SetRow title="Timezone" sub="Drives quiet hours, calendar days and briefings."
            control={<span style={{ display: "inline-flex", gap: 6 }}>
              <select value={(draft.timezone || "Africa/Nairobi") as string} onChange={(e) => set("timezone", e.target.value)}>
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
                  toast(`Merged ${r.inserted} rows · ${conf} conflicts kept local`, conf ? "warn" : "success");
                  refresh();
                } catch (err) { toast(`Import failed: ${err instanceof Error ? err.message : err}`, "error"); }
              }} /></Btn></label>
            </span>} />
          <SetRow title="Auto-store memories" sub="AURA extracts durable facts from chat."
            control={<Toggle on={draft.memory_auto_store !== false} onFlip={() => save({ memory_auto_store: draft.memory_auto_store === false })} label="auto-store" />} />
          <SetRow title="Observability retention" sub="Activity/audit/tool logs older than this are pruned nightly. Never touches your content."
            control={<Slider value={Number(draft.retention_days ?? 90)} min={0} max={365} step={5}
              onPick={(v) => set("retention_days", v)} format={(v) => (v === 0 ? "forever" : `${v}d`)} />} />
          <div style={{ marginTop: 8 }}><Btn small kind="violet" onClick={() => save({ retention_days: draft.retention_days ?? 90 }, "Retention saved")}>Save retention</Btn></div>
        </Panel>
        <Panel icon="users" title="Profile & Local LFM" sub="Local-first identity">
          <Row icon="users" title={me?.name || "—"} sub={me?.role} />
          <Row icon="target" title={me?.location || "—"} sub="Home timezone Africa/Nairobi" />
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
          <small className="dim">uptime {Math.round((health?.metrics.uptime_s || 0) / 60)}m · runs/24h {health?.metrics.runs_24h} · avg {health?.metrics.avg_run_ms}ms · tools ok {health?.metrics.tools_ok} / err {health?.metrics.tools_err}</small>
        </Panel>
        <Panel icon="alert" title="About & Danger Zone" sub={`AURA OS v${me?.version || ""} · single-user · local-first`}>
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
      <Panel icon="zap" title={`Hermes Tools (${tools?.tools.length || 0})`} sub={`Embedded runtime v${tools?.hermes || "2.0.0"} · risk-gated`}>
        <div className="toolgrid">
          {(tools?.tools || []).map((t) => (
            <div key={t.name} className="tool"><code>{t.name}</code><small>{t.description}</small><Pill c={t.risk === "R0" ? "blue" : t.risk === "R1" ? "green" : t.risk === "R2" ? "amber" : "red"}>{t.risk}</Pill></div>
          ))}
        </div>
      </Panel>
    </div>
  );
}
