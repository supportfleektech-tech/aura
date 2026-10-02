/* AURA OS global store — view routing, data, chat, orb state, voice, toasts. */
import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, chatStream, ChatMsg, Dashboard, OrbState, uid } from "./api";
import { createApprovalAlerts, playAlertSound } from "./alerts";
import { getServer, loadServerSettings, voicePreferenceKey } from "./prefs";

/** Every view the shell can render, and the single source for the `View` type.
 *  `App.tsx` renders views with a `view === x` chain and *no default branch*, so
 *  a name outside this list yields a blank main pane with no error anywhere.
 *  Deriving the type from the list makes TS-side drift impossible by
 *  construction; `backend/app/slash.py`'s `VIEWS` mirrors it, and
 *  `test_slash.py::test_slash_views_match_the_frontend_view_union` fails if the
 *  two lists ever disagree. */
export const VIEWS = [
  "home", "career", "clients", "personal", "inbox", "calendar", "memory",
  "sessions", "voice", "gateway", "automations", "board", "activity",
  "analytics", "smarthome", "files", "models", "terminal", "feeds", "perf",
  "settings",
] as const;

export type View = (typeof VIEWS)[number];

interface Toast { id: string; text: string; kind: "info" | "success" | "warn" | "error" }

interface Store {
  view: View; setView: (v: View) => void;
  me: { name: string; role: string; location: string; version?: string } | null;
  dash: Dashboard | null; online: boolean; lfm: string; activeModel: { backend: string; provider: string; model: string; privacy_mode: string; local_online: boolean; cloud_configured: boolean } | null;
  refresh: () => Promise<void>;
  orb: OrbState; setOrb: (s: OrbState) => void;
  msgs: ChatMsg[]; sending: boolean; sessionId: string | null;
  send: (text: string, attachments?: unknown[]) => Promise<void>;
  newChat: () => void;
  loadSession: (sid: string) => Promise<void>;
  palette: boolean; setPalette: (b: boolean) => void;
  toasts: Toast[]; toast: (text: string, kind?: Toast["kind"]) => void;
  listening: boolean; toggleListen: (onSend?: (t: string) => void) => void; transcript: string;
  speak: (text: string, onComplete?: () => void) => void; speaking: boolean; stopSpeak: () => void; stopGenerating: () => void;
  micLevel: React.MutableRefObject<number>;
  pendingApprovals: number;
  call: boolean; setCall: (b: boolean) => void;
  composerFocus: number; requestComposerFocus: () => void;
}

const Ctx = createContext<Store>(null as unknown as Store);
export const useStore = () => useContext(Ctx);

const GREETINGS: Record<string, string[]> = {
  morning: ["Good morning", "Top of the morning"],
  afternoon: ["Good afternoon"],
  evening: ["Good evening"],
};
const GREETINGS_SW: Record<string, string[]> = {
  morning: ["Habari za asubuhi", "Amka salama"],
  afternoon: ["Habari za mchana"],
  evening: ["Habari za jioni"],
};
export const daypart = () => {
  const h = parseInt(new Intl.DateTimeFormat("en", { hour: "numeric", hour12: false, timeZone: "Africa/Nairobi" }).format(new Date()), 10);
  return h < 12 ? "morning" : h < 17 ? "afternoon" : "evening";
};
export const greetWord = (lang = "en") => {
  const p = daypart();
  const arr = (lang === "sw" ? GREETINGS_SW : GREETINGS)[p];
  return arr[Math.floor(Math.random() * arr.length)];
};

export function StoreProvider({ children }: { children: React.ReactNode }) {
  const [view, setView] = useState<View>("home");
  const [me, setMe] = useState<Store["me"]>(null);
  const [dash, setDash] = useState<Dashboard | null>(null);
  const [online, setOnline] = useState(true);
  const [lfm, setLfm] = useState("checking…");
  const [orb, setOrbState] = useState<OrbState>("idle");
  const [activeModel, setActiveModel] = useState<Store["activeModel"]>(null);
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [sending, setSending] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [palette, setPalette] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [speaking, setSpeaking] = useState(false);
  const [pendingApprovals, setPendingApprovals] = useState(0);
  const [call, setCall] = useState(false);
  const [composerFocus, setComposerFocus] = useState(0);
  const micLevel = useRef(0);
  const recRef = useRef<{ stop: () => void } | null>(null);
  const orbTimer = useRef<number>(0);
  const chatAbortRef = useRef<AbortController | null>(null);

  const toast = useCallback((text: string, kind: Toast["kind"] = "info") => {
    const id = uid();
    setToasts((t) => [...t.slice(-4), { id, text, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), getServer("toast_duration_ms", 4200));
    if (kind === "error") void playAlertSound();
  }, []);

  const updateApprovalAlerts = useRef(createApprovalAlerts());

  const setOrb = useCallback((s: OrbState) => {
    setOrbState(s);
    window.clearTimeout(orbTimer.current);
    if (s === "success" || s === "error" || s === "warning") {
      orbTimer.current = window.setTimeout(() => setOrbState((cur) => (cur === s ? "idle" : cur)), 2600);
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [m, d, h, ap] = await Promise.all([api.me.get(), api.dashboard(), api.health(), api.approvals.list()]);
      setMe(m); setDash(d); setOnline(true);
      const l = h.services.find((s) => s.name === "Local LFM");
      setLfm(l?.status === "online" ? "Local LFM Online" : "Builtin Engine · LFM Standby");
      if (h.active_model) setActiveModel(h.active_model);
      setPendingApprovals(ap.approvals.length);
      updateApprovalAlerts.current(ap.approvals.map((a) => a.id));
    } catch {
      setOnline(false);
      setOrb("offline");
    }
  }, []);

  useEffect(() => {
    refresh();
    loadServerSettings().catch(() => undefined);
    const t = setInterval(refresh, 30000);
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((p) => !p); }
    };
    window.addEventListener("keydown", onKey);
    return () => { clearInterval(t); window.removeEventListener("keydown", onKey); };
  }, [refresh]);

  /* ---------------- voice (browser + server engines) ---------------- */
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const speakAbortRef = useRef<AbortController | null>(null);
  const speakGenRef = useRef(0);
  const speakUrlRef = useRef<string | null>(null);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);
  const releaseSpeech = useCallback(() => {
    const a = audioRef.current;
    audioRef.current = null;
    if (a) {
      a.onended = null; a.onerror = null;
      try { a.pause(); a.removeAttribute("src"); a.load(); } catch {}
    }
    if (speakUrlRef.current) URL.revokeObjectURL(speakUrlRef.current);
    speakUrlRef.current = null;
    if (utteranceRef.current) { utteranceRef.current.onend = null; utteranceRef.current.onerror = null; }
    utteranceRef.current = null;
  }, []);
  const stopSpeak = useCallback(() => {
    speakGenRef.current += 1;
    speakAbortRef.current?.abort();
    speakAbortRef.current = null;
    releaseSpeech();
    try { speechSynthesis.cancel(); } catch {}
    setSpeaking(false);
  }, [releaseSpeech]);
  useEffect(() => () => stopSpeak(), [stopSpeak]);

  const stopGenerating = useCallback(() => {
    chatAbortRef.current?.abort();
    chatAbortRef.current = null;
    setSending(false);
    setOrb("idle");
  }, []);

  const VOICE_EMO: Record<string, { rate: number; pitch: number }> = {
    neutral: { rate: 1, pitch: 1 }, cheerful: { rate: 1.1, pitch: 1.15 }, calm: { rate: 0.88, pitch: 0.9 },
    excited: { rate: 1.15, pitch: 1.25 }, serious: { rate: 0.95, pitch: 0.85 }, sad: { rate: 0.88, pitch: 0.85 },
  };

  const speak = useCallback((text: string, onComplete?: () => void) => {
    stopSpeak();
    const generation = speakGenRef.current;
    let finished = false;
    const current = () => generation === speakGenRef.current && !finished;
    const finish = () => {
      if (!current()) return;
      finished = true;
      speakAbortRef.current = null;
      releaseSpeech();
      setSpeaking(false);
      onComplete?.();
    };
    try {
      const clean = text.replace(/[*#>`]/g, "").replace(/\[.*?\]/g, "").replace(/\n+/g, ". ").slice(0, 1500);
      if (!clean.trim()) { finish(); return; }
      const engine = String(getServer("voice_engine", "browser"));
      const emo = VOICE_EMO[String(getServer("voice_emotion", "neutral"))] || VOICE_EMO.neutral;
      if (engine === "piper" || engine === "edge" || engine === "kokoro") {
        setSpeaking(true);
        const vkey = voicePreferenceKey(engine);
        const controller = new AbortController();
        speakAbortRef.current = controller;
        api.voice.speakUrl(clean, { engine, emotion: String(getServer("voice_emotion", "neutral")), voice: String(getServer(vkey, "")) || undefined }, controller.signal)
          .then((url) => {
            if (!current()) { URL.revokeObjectURL(url); return; }
            speakUrlRef.current = url;
            const a = new Audio(url);
            audioRef.current = a;
            a.onended = finish;
            a.onerror = finish;
            return a.play();
          })
          .catch((e) => { if (!current()) return; finish(); toast(`Voice: ${e instanceof Error ? e.message : e}`, "error"); });
        return;
      }
      if (!("speechSynthesis" in window)) { toast("TTS not supported in this browser", "warn"); finish(); return; }
      const u = new SpeechSynthesisUtterance(clean);
      const ur = Number(getServer("voice_rate", 1.0)), up = Number(getServer("voice_pitch", 1.0));
      u.rate = Math.min(2, Math.max(0.5, emo.rate * ur));
      u.pitch = Math.min(2, Math.max(0, emo.pitch + (up - 1)));
      u.lang = String(getServer("voice_lang", "en-KE"));
      const want = String(getServer("voice_browser_name", ""));
      if (want) {
        try {
          const vs = speechSynthesis.getVoices();
          const hit = vs.find((x) => x.name === want) || vs.find((x) => x.name.toLowerCase().includes(want.toLowerCase()));
          if (hit) u.voice = hit;
        } catch { /* noop */ }
      }
      u.onend = finish;
      u.onerror = finish;
      utteranceRef.current = u;
      setSpeaking(true);
      speechSynthesis.speak(u);
    } catch { finish(); }
  }, [stopSpeak, toast, releaseSpeech]);

  const speakRef = useRef<((t: string) => void) | null>(null);
  useEffect(() => { speakRef.current = speak; }, [speak]);
  // A custom command returns its prompt so the *client* sends it as a normal
  // message. The follow-up has to be deferred until this turn's stream is fully
  // consumed: firing it inline would let the outer `done` frame land
  // `setSending(false)` in the middle of the second turn, and would let the
  // outer `finally` null `chatAbortRef` out from under it.
  const sendRef = useRef<((t: string, a?: unknown[], depth?: number) => Promise<void>) | null>(null);
  const pendingPromptRef = useRef<string | null>(null);
  // A custom command's prompt is arbitrary text, so it can name another custom
  // command. Without a bound, `/a` → prompt "/b" → `/b` → prompt "/a" would loop
  // forever hammering the backend. Chains are capped rather than blocked: a
  // prompt that legitimately resolves to a second command still resolves.
  const MAX_COMMAND_CHAIN = 4;

  /* ---------------- chat ---------------- */
  const requestComposerFocus = useCallback(() => {
    setComposerFocus((n) => n + 1);
    setView("home");
  }, []);

  const send = useCallback(async (text: string, attachments: unknown[] = [],
                             chainDepth = 0) => {
    const clean = text.trim();
    if (!clean && attachments.length === 0) return;
    if (!online) { toast("Backend offline — running in local mode", "warn"); }
    const um: ChatMsg = { id: uid(), role: "user", text: clean, ts: Date.now(),
      files: (attachments as { id?: number; name?: string }[]).filter((a) => a && typeof a.id === "number")
        .map((a) => ({ id: a.id as number, name: String(a.name || `#${a.id}`) })) };
    const aid = uid();
    const am: ChatMsg = { id: aid, role: "assistant", text: "", ts: Date.now(), steps: [] };
    setMsgs((m) => [...m, um, am]);
    setSending(true);
    setOrb("thinking");
    let acc = "";
    let aborted = false;
    const patch = (p: Partial<ChatMsg>) => setMsgs((ms) => ms.map((m) => (m.id === aid ? { ...m, ...p } : m)));
    const controller = new AbortController();
    chatAbortRef.current = controller;
    try {
      await chatStream(clean, sessionId, {
        onOrb: (s) => setOrb(s),
        onPlan: (p) => { patch({ steps: p.steps }); setSessionId(p.session_id); },
        onStep: (s) => setMsgs((ms) => ms.map((m) => m.id === aid
          ? { ...m, steps: (m.steps || []).map((x) => (x.id === s.id ? { ...x, status: s.status } : x)) } : m)),
        onToken: (t) => { acc += t; if (getServer("chat_streaming", true)) patch({ text: acc }); },
        onThinking: (t) => setMsgs((ms) => ms.map((m) => m.id === aid ? { ...m, thinking: [...(m.thinking || []), t.text] } : m)),
        onApproval: (a) => { if (a) updateApprovalAlerts.current([a.id]); patch({ approval: a || undefined }); },
        onResult: (r) => {
          acc = r.text;
          if (r.approval) updateApprovalAlerts.current([r.approval.id]);
          patch({ text: r.text, memories: r.memories_used || [], approval: r.approval || undefined, model: r.model, thinking: undefined });
          if (getServer("voice_autoplay", false) && r.text.trim()) speakRef.current?.(r.text);
        },
        onMemory: (m) => { if (m.stored?.length) toast(`Saved to memory: ${m.stored[0].title.slice(0, 60)}`, "success"); },
        // No toast for `facts`: the event also fires on read-only turns that
        // merely list clients/projects, and a "Noted:" toast with no user
        // action behind it is noise. The SSE frame is still parsed by api.ts.
        onVision: (v) => setMsgs((ms) => ms.map((m) => m.id === aid
          ? { ...m, vision: [...(m.vision || []).filter((x) => x.file !== v.file), v] } : m)),
        onMission: (mv) => setMsgs((ms) => ms.map((m) => m.id === aid
          ? { ...m, missions: [...(m.missions || []).filter((x) => x.id !== mv.id), mv] } : m)),
        onSlash: (r) => {
          // A view the shell cannot render must degrade to visible text, never a
          // blank main pane: `App.tsx` is a `view === x` chain with no default
          // branch, so `setView("analytic")` renders nothing at all. `save_custom`
          // rejects unknown views server-side, so this only catches rows saved
          // before that guard existed.
          const target = (r.view && VIEWS.includes(r.view as View)) ? r.view : null;
          // FR-CMD-004: a custom command is a *prompt*, not an answer. The spec
          // says executing one "returns its prompt so the client sends it as a
          // normal message". Rendering `r.text` as AURA's reply made the
          // transcript show the assistant repeating the user's own prompt back
          // at them; `/brief` typed as "summarise my day" appeared as if AURA
          // had said it. So: send it, never render it.
          //
          // Ordering is deliberate — navigate *first*, then send. Navigation is
          // instant local state, so the turn lands in the destination view. The
          // send is deferred to `finally` (below) rather than fired here, because
          // this stream has not ended yet.
          const prompt = (r.result as { prompt?: string } | null)?.prompt;
          if (typeof prompt === "string" && prompt.trim()) {
            if (chainDepth >= MAX_COMMAND_CHAIN) {
              // The cap is a hard stop, and it must be *stated*. Falling through
              // to the generic render branch below is the bug: `execute()`'s
              // `text` for a custom command is the user's own prompt, so the
              // transcript ended with the assistant apparently repeating back
              // something the user typed and never answered. Better an honest
              // "here is why the chain ended" than a fabricated utterance.
              patch({ text: `Command chain stopped after ${MAX_COMMAND_CHAIN} steps — `
                           + `${r.command} was not run.` });
              refresh();
              return;
            }
            if (target) setView(target as View);
            patch({ text: `→ ${r.command}` });
            pendingPromptRef.current = prompt;
            refresh();
            return;
          }
          // Navigation is a view switch; anything else is rendered verbatim.
          // `ok: false` is a real answer (a usage error), so it still goes in
          // the transcript rather than looking like silence.
          if (target) { setView(target as View); patch({ text: `→ ${r.command}` }); }
          else patch({ role: r.ok ? "assistant" : "error", text: r.text || "(no output)" });
          refresh();
        },
        onDone: () => { setSending(false); setOrb("success"); refresh(); },
      }, attachments, controller.signal);
    } catch (e) {
      if (e instanceof Error && e.name === "AbortError") { aborted = true; return; }
      patch({ role: "error", text: `I couldn't reach the AURA backend. ${String(e).slice(0, 120)}` });
      setSending(false);
      setOrb("error");
    } finally {
      chatAbortRef.current = null;
      // Deferred custom-command prompt, sent as an ordinary turn now that this
      // stream is done and `chatAbortRef` belongs to nobody. Skipped on abort:
      // the user hit Stop, so firing another message at them is the opposite of
      // what they asked.
      const follow = aborted ? null : pendingPromptRef.current;
      pendingPromptRef.current = null;
      if (follow) void sendRef.current?.(follow, [], chainDepth + 1);
    }
  }, [online, sessionId, refresh, setOrb, toast]);
  useEffect(() => { sendRef.current = send; }, [send]);

  const newChat = useCallback(() => {
    setMsgs([]);
    setSessionId(null);
    setOrb("idle");
  }, [setOrb]);

  const loadSession = useCallback(async (sid: string) => {
    try {
      const r = await api.sessions.get(sid);
      setMsgs(r.messages.map((m) => ({
        id: uid(), role: (m.role === "user" ? "user" : "assistant") as ChatMsg["role"],
        text: m.content, ts: Date.now(),
      })));
      setSessionId(sid);
      setView("home");
      toast("Conversation loaded", "info");
    } catch {
      toast("Could not load conversation", "error");
    }
  }, [toast]);

  const toggleListen = useCallback((onSend?: (t: string) => void) => {
    if (listening) {
      recRef.current?.stop();
      setListening(false);
      setOrb("idle");
      return;
    }
    const SR = (window as unknown as { SpeechRecognition?: new () => WebRec; webkitSpeechRecognition?: new () => WebRec }).SpeechRecognition
      || (window as unknown as { webkitSpeechRecognition?: new () => WebRec }).webkitSpeechRecognition;
    if (!SR) { toast("Speech recognition not supported in this browser — type instead", "warn"); return; }
    try {
      const rec: WebRec = new SR();
      rec.lang = getServer("voice_lang", "en-KE");
      rec.interimResults = true;
      rec.continuous = false;
      let final = "";
      rec.onresult = (e: { results: { isFinal: boolean; [i: number]: { transcript: string } }[] }) => {
        let interim = "";
        for (const r of e.results) { if (r.isFinal) final += r[0].transcript; else interim += r[0].transcript; }
        setTranscript(final + interim);
      };
      rec.onend = () => {
        recRef.current = null;
        setListening(false);
        setOrb("idle");
        const t = final.trim();
        setTranscript("");
        if (t) { api.voice.log(t).catch(() => undefined); (onSend || send)(t); }
      };
      rec.onerror = () => { recRef.current = null; setListening(false); setOrb("idle"); };
      recRef.current = rec;
      rec.start();
      setListening(true);
      setOrb("listening");
      // mic level meter
      navigator.mediaDevices?.getUserMedia({ audio: true }).then((stream) => {
        const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        if (!AC) return;
        const ac = new AC();
        const src = ac.createMediaStreamSource(stream);
        const an = ac.createAnalyser();
        an.fftSize = 256;
        src.connect(an);
        const arr = new Uint8Array(an.frequencyBinCount);
        const tick = () => {
          if (!recRef.current) { stream.getTracks().forEach((t) => t.stop()); ac.close().catch(() => undefined); return; }
          an.getByteFrequencyData(arr);
          micLevel.current = arr.reduce((a, b) => a + b, 0) / arr.length / 255;
          requestAnimationFrame(tick);
        };
        tick();
      }).catch(() => undefined);
    } catch { toast("Could not start microphone", "error"); }
  }, [listening, send, setOrb, toast]);

  useEffect(() => () => { recRef.current = null; try { speechSynthesis.cancel(); } catch { /* noop */ } }, []);

  return (
    <Ctx.Provider value={{
      view, setView, me, dash, online, lfm, refresh, orb, setOrb, msgs, sending, sessionId,
      send, newChat, loadSession, palette, setPalette, toasts, toast, listening, toggleListen, transcript,
      speak, speaking, stopSpeak, stopGenerating, micLevel, pendingApprovals, call, setCall,
      composerFocus, requestComposerFocus, activeModel,
    }}>
      {children}
    </Ctx.Provider>
  );
}

interface WebRec {
  lang: string; interimResults: boolean; continuous: boolean;
  onresult: ((e: { results: { isFinal: boolean; [i: number]: { transcript: string } }[] }) => void) | null;
  onend: (() => void) | null; onerror: (() => void) | null;
  start: () => void; stop: () => void;
}
