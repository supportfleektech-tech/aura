import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useStore } from "../store";
import { useLang } from "../i18n";
import { Field, useFetch } from "../views1";
import { getServer } from "../prefs";
import { Btn, ChatThread, Composer, Empty, Icon, Panel, Pill, Row, Skel, Waveform } from "../ui";
import { CallHistoryPanel } from "../views4";

export const CAP_WORKLET = `class Cap extends AudioWorkletProcessor {
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
          setState(m.wake ? "sleeping · say \u201chey jarvis\u201d" : "tap Talk, then speak");
        } else if (m.t === "state") {
          setState(m.state === "listening" && m.followup ? "listening · follow-up" : (m.state || ""));
        } else if (m.t === "wake") {
          setState("listening");
        } else if (m.t === "barge") {
          stopAudio();
          setState("listening");
          toast("Interrupted — I\u2019m listening", "info");
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
            ? "Say \u201chey jarvis\u201d — I\u2019m listening. Say it while I talk to interrupt."
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
      <div className="vhead"><h2><Icon n="mic" s={20} /> {t("title.voice")}</h2><Pill c={listening ? "violet" : "blue"}>{listening ? "Listening\u2026" : "Idle"}</Pill></div>
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
          <p className="center">{listening ? (transcript || "Listening\u2026 speak now") : "Tap the microphone and speak \u2014 your words become a message to AURA."}</p>
          <div style={{ display: "flex", gap: 8, justifyContent: "center" }}>
            <Btn small onClick={() => send("what can you do?")}>Try: \u201cwhat can you do?\u201d</Btn>
            <Btn small onClick={() => send("plan my day")}>Try: \u201cplan my day\u201d</Btn>
          </div>
        </Panel>
        <Panel icon="wave" title="Speech Output" sub={data?.tts || "browser TTS"}>
          <textarea className="ta" rows={4} value={say} onChange={(e) => setSay(e.target.value)} />
          <div style={{ display: "flex", gap: 8 }}>
            <Btn small kind="violet" onClick={() => speak(say)}>{speaking ? "Speaking\u2026" : "Speak"}</Btn>
            <Btn small onClick={stopSpeak}>Stop</Btn>
          </div>
          <small className="secttl">Engine</small>
          <Row icon="cpu" title="STT: Web Speech (on-device where available)" sub={data?.note} />
          <Row icon="wave" title="TTS: system voices" sub={`Language ${data?.language || "en-KE"}`} />
        </Panel>
      </div>
      <div className="grid2">
        <VoiceLoopPanel />
        <Panel icon="cpu" title="Server STT" sub={vstat ? `whisper ${vstat.whisper_model}${vstat.whisper_ready ? " · loaded" : ""}` : "checking\u2026"}>
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
              }}>\u25cf Record</Btn>}
              {rec && <Btn small kind="red" onClick={() => { rec.stop(); setRec(null); }}>\u25a0 Stop & transcribe</Btn>}
              <label><Btn small>Upload audio<input type="file" accept="audio/*" hidden onChange={async (e) => {
                const f = e.target.files?.[0]; if (!f) return;
                try { const r = await api.voice.transcribe(f); setSrvText(r.text); toast("Transcribed", "success"); }
                catch (err) { toast(`${err instanceof Error ? err.message : err}`, "error"); }
              }} /></Btn></label>
            </div>
          )}
          {srvText && <><p style={{ marginTop: 8 }}>\u201c{srvText}\u201d</p><Btn small kind="green" onClick={() => send(srvText)}>Send to chat \u2192</Btn></>}
        </Panel>
        <Panel icon="wave" title="Server TTS" sub={vstat ? vstat.piper_voice : "checking\u2026"}>
          {vstat && !vstat.tts_installed && <Empty title="Not installed" sub="pip install -r backend/requirements-voice.txt" />}
          {vstat?.tts_installed && (
            <div style={{ display: "flex", gap: 8 }}>
              <Field value={say} onChange={(e) => setSay(e.target.value)} placeholder="Text to speak\u2026" />
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
