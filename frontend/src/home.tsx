/* AURA OS Home — greeting, domain panels, orb stage, right intelligence rail. */
import { useEffect, useRef, useState } from "react";
import Orb from "./Orb";
import { ago, api, Opportunity } from "./api";
import { greetWord, useStore, View } from "./store";
import { useLang } from "./i18n";
import { Btn, ChatThread, Composer, Dot, Empty, fmtDate, Icon, Panel, Pill, Progress, Row, useNairobiClock, Waveform } from "./ui";

const QUOTES = [
  "Big dreams, structured plans, consistent action.",
  "Clarity compounds. Momentum matters.",
  "Plan the work. Work the plan.",
  "Small steps daily beat sprints occasionally.",
];

/* ============================== HOME ============================== */
export function OpportunitiesCard() {
  const [items, setItems] = useState<Opportunity[]>([]);
  const [draft, setDraft] = useState<{ key: string; text: string } | null>(null);
  const [done, setDone] = useState<{ key: string; title: string; resolved_at: string }[] | null>(null);
  const { send, setView, toast, refresh } = useStore();
  useEffect(() => {
    api.proactive.list().then((r) => setItems(r.opportunities || [])).catch(() => undefined);
  }, []);
  if (!items.length) return null;
  const drop = (key: string) => setItems((cur) => cur.filter((x) => x.key !== key));
  const runAct = async (o: Opportunity) => {
    try {
      const r = await api.proactive.act(o.key);
      if (r.gone) { toast("Already resolved", "success"); drop(o.key); return; }
      if (r.kind === "draft" && r.action?.text) { setDraft({ key: o.key, text: r.action.text }); return; }
      if (r.kind === "open" && r.action?.view) { setView(r.action.view as View); return; }
      if (r.kind === "chat" && r.action?.text) { send(r.action.text); return; }
      if (r.kind === "mission") { toast("Mission created & scheduled — see Automations → Missions", "success"); drop(o.key); refresh(); return; }
      toast(r.kind === "run_backup" ? "Backup running" : "Done", "success");
      drop(o.key); refresh();
    } catch (e) { toast(`Action failed: ${e instanceof Error ? e.message : e}`, "error"); }
  };
  return (
    <Panel icon="eye" title="Worth a look" sub="Proactive finds — act, snooze, or dismiss"
      right={done === null
        ? <Btn small onClick={() => api.proactive.resolved().then((r) => setDone(r.resolved || [])).catch(() => undefined)}>✓ Resolved</Btn>
        : <Btn small onClick={() => setDone(null)}>Back</Btn>}>
      {done !== null ? (
        done.length === 0 ? <Empty title="Nothing resolved yet" sub="Handled items land here." /> :
          done.map((d) => <Row key={d.key} icon="check" title={d.title} sub={`resolved ${ago(d.resolved_at)}`} />)
      ) : items.slice(0, 4).map((o) => (
        <div key={o.key}>
          <Row icon="zap" title={o.title} sub={(o.reasons || [])[0] || o.detail}
            right={<span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
              {o.action && o.action.kind !== "none" && (
                <Btn small onClick={() => runAct(o)} title={o.action!.label || "Act"}>⚡ {o.action.label || "Act"}</Btn>)}
              <Btn small onClick={() => {
                api.proactive.snooze(o.key).then(() => drop(o.key)).catch(() => toast("Snooze failed", "error"));
              }} title="Snooze 24h">💤</Btn>
              <button className="xbtn" title="Dismiss"
                onClick={() => { api.proactive.dismiss(o.key).catch(() => undefined); drop(o.key); }}>
                <Icon n="x" s={13} /></button>
            </span>} />
          {draft?.key === o.key && (
            <div style={{ padding: "0 4px 8px 40px", fontSize: 13 }}>
              <div className="muted" style={{ marginBottom: 4 }}>{draft.text}</div>
              <Btn small onClick={() => {
                try { navigator.clipboard.writeText(draft.text); toast("Copied", "success"); }
                catch { toast("Copy failed", "error"); }
              }}>Copy</Btn>
            </div>)}
        </div>
      ))}
    </Panel>
  );
}

export function HomeView() {
  const { me, dash, setView, send, orb, micLevel, online, setCall, requestComposerFocus } = useStore();
  const composerArea = useRef<HTMLDivElement>(null);
  const openAttachment = (image: boolean) => {
    composerArea.current?.querySelector<HTMLInputElement>(image
      ? 'input[type="file"][accept="image/*"]'
      : 'input[type="file"]:not([accept="image/*"])')?.click();
  };
  const shortcuts = [
    { label: "Voice", icon: "mic", fn: () => setView("voice") },
    { label: "Text", icon: "chat", fn: requestComposerFocus },
    { label: "Image", icon: "image", fn: () => openAttachment(true) },
    { label: "File", icon: "file", fn: () => openAttachment(false) },
    { label: "Camera/screen", icon: "eye", fn: () => setView("files") },
    { label: "More", icon: "more", fn: () => setView("settings") },
  ];
  const { lang } = useLang();
  const { date, time } = useNairobiClock();
  const quote = QUOTES[new Date().getDate() % QUOTES.length];
  const chips = [
    { icon: "search", label: "Search my memory", fn: () => setView("memory") },
    { icon: "cal", label: "Plan my day", fn: () => send("plan my day") },
    { icon: "file", label: "Optimize my resume", fn: () => setView("career") },
    { icon: "brief", label: "Update project", fn: () => setView("clients") },
    { icon: "heart", label: "Check my health", fn: () => setView("personal") },
    { icon: "mic", label: "Talk to me", fn: () => setView("voice") },
    { icon: "phone", label: "Call AURA", fn: () => setCall(true) },
  ];
  const tasks = dash?.priorities || [];
  const projects = dash?.projects || [];
  const acts = dash?.activity || [];
  return (
    <div className="home">
      <div className="greetrow">
        <div className="greet">
          <h1>{greetWord(lang)}, {me?.name || "Antony"}! <span className="wavehand">👋</span></h1>
          <p>Your AI sidekick is ready. What would you like to do today?</p>
          <div className="chips">{chips.map((c) => <button key={c.label} className="chip" onClick={c.fn}><Icon n={c.icon} s={14} />{c.label}</button>)}</div>
        </div>
        <div className="datetimecard">
          <em>“{quote}”</em>
          <small>{date}</small>
          <strong>{time}</strong>
          <span>Nairobi, Kenya</span>
          <span className="wx">⛅ 18°C <i>Partly Cloudy</i></span>
          {!online && <Pill c="red">Offline mode</Pill>}
        </div>
      </div>

      <section aria-label="Text chat">
        <ChatThread />
        <div ref={composerArea}><Composer /></div>
      </section>

      <OpportunitiesCard />

      <div className="homegrid">
        {/* Career & Work Panel */}
        <Panel icon="brief" title="Career & Work Panel" sub="Grow your career, boost productivity, achieve more." glow="g-blue"
          right={<button className="xbtn" onClick={() => setView("career")} title="Open workspace"><Icon n="chev" s={14} /></button>}>
          <Row icon="file" title="Resume Optimization" sub="Tailor your resume for your target roles" onClick={() => setView("career")} />
          <Row icon="heart" title="Interview Preparation" sub="Practice with AI-powered mock interviews" onClick={() => setView("career")} />
          <Row icon="cal" title="Time Blocking" sub="Plan your day for maximum productivity" onClick={() => setView("career")} />
          <small className="secttl">Quick Actions</small>
          <div className="qgrid">
            <Btn kind="violet" small onClick={() => setView("career")}>Optimize Resume</Btn>
            <Btn small onClick={() => send("prep me for interviews")}>Prepare Interview</Btn>
            <Btn kind="green" small onClick={() => send("plan my day")}>Plan My Day</Btn>
            <Btn small onClick={() => setView("personal")}>View Goals</Btn>
          </div>
          <small className="secttl">Recent Career Activity <button className="link" onClick={() => setView("activity")}>View All</button></small>
          {acts.filter((a) => a.domain === "career" || a.kind === "task").slice(0, 3).map((a) => (
            <Row key={a.id} icon="zap" title={a.title.slice(0, 44)} sub={ago(a.created_at)} />
          ))}
          {acts.length === 0 && <Empty title="No activity yet" sub="AURA will log career actions here." />}
        </Panel>

        {/* Orb stage */}
        <section className="panel orbstage" aria-label="AURA orb">
          <div className="orbtitle"><span className="auralogo">AURA <b>OS</b></span><small>Multimodal AI Sidekick</small></div>
          <div className="orbwrap" onClick={() => send("system status")} title="Click to inspect status">
            <Orb state={orb} levelRef={micLevel} size={264} />
          </div>
          <div className="orbbadge"><Icon n="mic" s={14} />{orbLabel(orb)}</div>
          <Waveform active={orb === "listening" || orb === "working" || orb === "thinking"} />
          <div className="orbbtns">
            {shortcuts.map((s) => (
              <button key={s.label} onClick={s.fn}><Icon n={s.icon} s={17} /><small>{s.label}</small></button>
            ))}
          </div>
        </section>

        {/* Clients & Projects Panel */}
        <Panel icon="users" title="Clients & Projects Panel" sub="Manage clients, track projects, deliver results." glow="g-green"
          right={<button className="xbtn" onClick={() => setView("clients")} title="Open workspace"><Icon n="chev" s={14} /></button>}>
          <Row icon="users" title="Client Directory" sub="View & manage your clients" onClick={() => setView("clients")} />
          <Row icon="chart" title="Project Tracker" sub="Track progress, deadlines, milestones" onClick={() => setView("clients")} />
          <Row icon="db" title="Backup Management" sub="Secure your files & data" onClick={() => setView("clients")} />
          <small className="secttl">Quick Actions</small>
          <div className="qgrid">
            <Btn kind="violet" small onClick={() => send("add client ")}>Add Client</Btn>
            <Btn small onClick={() => send("new project ")}>New Project</Btn>
            <Btn kind="green" small onClick={() => send("run a backup")}>Backup Now</Btn>
            <Btn small onClick={() => setView("clients")}>View All Projects</Btn>
          </div>
          <small className="secttl">Recent Project Activity <button className="link" onClick={() => setView("activity")}>View All</button></small>
          {projects.slice(0, 3).map((p) => (
            <div key={p.id} className="projrow" onClick={() => setView("clients")}>
              <span className="ricon"><Icon n="brief" s={15} /></span>
              <span className="rtitles"><strong>{p.name}</strong><small className={p.status === "completed" ? "green" : p.health !== "on_track" ? "amber" : "blue"}>{p.status === "completed" ? "Completed" : p.status === "review" ? "In Review" : `In Progress · ${p.progress}%`}</small></span>
              <Progress v={p.progress} />
            </div>
          ))}
        </Panel>

        {/* Personal Life Panel */}
        <Panel icon="heart" title="Personal Life Panel" sub="Balance your mind, body and future." glow="g-pink"
          right={<button className="xbtn" onClick={() => setView("personal")} title="Open workspace"><Icon n="chev" s={14} /></button>}>
          <Row icon="moon" title="Wellbeing & Mindfulness" sub="Meditation, stress relief, journaling" onClick={() => setView("personal")} />
          <Row icon="heart" title="Health & Fitness" sub="Workouts, nutrition, sleep" onClick={() => setView("personal")} />
          <Row icon="wallet" title="Finance & Goals" sub="Budgeting, investments, savings" onClick={() => setView("personal")} />
          <Row icon="users" title="Relationships" sub="Family, friends, social life" onClick={() => setView("personal")} />
          <small className="secttl">Quick Actions</small>
          <div className="qgrid">
            <Btn kind="violet" small onClick={() => send("log mood ")}>Log Mood</Btn>
            <Btn small onClick={() => send("log workout ")}>Track Health</Btn>
            <Btn kind="green" small onClick={() => send("add expense ")}>Add Expense</Btn>
            <Btn small onClick={() => setView("personal")}>Set Goal</Btn>
          </div>
          <small className="secttl">Personal Insights <button className="link" onClick={() => setView("personal")}>View All</button></small>
          <div className="insights">
            <div><Icon n="moon" s={16} /><small>Sleep</small><strong>{dash?.insights.sleep || "—"}</strong>{dash?.insights.sleep_state ? <i className="green">{dash.insights.sleep_state}</i> : <i style={{ opacity: 0.55 }}>no data</i>}</div>
            <div><span>😊</span><small>Mood</small><strong>{dash?.insights.mood || "—"}</strong>{dash?.insights.mood_delta ? <i className="green">{dash.insights.mood_delta}</i> : null}</div>
            <div><Icon n="wallet" s={16} /><small>Spending</small><strong>KES {(dash?.counts.spending || 0).toLocaleString()}{(dash?.insights.spending_other && dash.insights.spending_other !== "0") ? "+" : ""}</strong><i className={dash?.insights.spending_dir === "up" ? "amber" : "green"}>{dash?.insights.spending_state || ""}</i></div>
          </div>
        </Panel>
      </div>

      {tasks.length > 0 && (
        <div className="todaystrip">
          <strong><Icon n="target" s={15} /> Today's priorities</strong>
          {tasks.slice(0, 4).map((t) => (
            <button key={t.id} className="tchip" onClick={() => send(`mark "${t.title}" as ${t.status === "completed" ? "in progress" : "completed"}`)} title={t.title}>
              <Dot c={t.priority === "urgent" ? "red" : t.priority === "high" ? "amber" : "blue"} />{t.title.slice(0, 40)}{t.due_at ? ` · ${fmtDate(t.due_at)}` : ""}
            </button>
          ))}
          {(dash?.counts.overdue || 0) > 0 && <Pill c="red">{dash?.counts.overdue} overdue</Pill>}
        </div>
      )}

      <Capabilities />
    </div>
  );
}

function orbLabel(o: string) {
  return { idle: "Ready", listening: "Listening…", thinking: "Thinking…", retrieving: "Recalling…", working: "Working…", waiting_approval: "Needs approval", success: "Done", warning: "Attention", error: "Error", offline: "Offline" }[o] || o;
}

function Capabilities() {
  const items = [
    { icon: "search", c: "amber", t: "Semantic Search", d: "Find anything across all panels with AI relevance ranking" },
    { icon: "spark", c: "violet", t: "3D Aura Orb", d: "Immersive visual interface with real-time AI response" },
    { icon: "cpu", c: "green", t: "Persistent Memory", d: "Your data, context and history across all sessions" },
    { icon: "zap", c: "violet", t: "Local LFM Inference", d: "Private, fast, offline-capable AI processing" },
    { icon: "grid", c: "blue", t: "Multi-Platform", d: "Connect everywhere — Telegram, Discord, Slack, etc." },
    { icon: "shield", c: "green", t: "Enterprise Security", d: "End-to-end encryption and privacy protection" },
  ];
  return (
    <div className="capgrid">
      {items.map((x) => (
        <div key={x.t} className="cap"><span className={`cicon ${x.c}`}><Icon n={x.icon} s={18} /></span><span><strong>{x.t}</strong><small>{x.d}</small></span></div>
      ))}
    </div>
  );
}

/* ============================== RIGHT RAIL ============================== */
const RECENT_KEY = "aura_recent_search";
export function RightRail() {
  const { dash, listening, toggleListen, transcript, online, setView } = useStore();
  const [q, setQ] = useState("");
  const [res, setRes] = useState<{ title: string; snippet: string; relevance: number }[]>([]);
  const [recent, setRecent] = useState<string[]>(() => { try { return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]"); } catch { return []; } });
  const gw = dash?.gateway || [];
  const runSearch = async (query: string) => {
    if (query.trim().length < 2) return;
    setRecent((r) => { const n = [query, ...r.filter((x) => x !== query)].slice(0, 5); localStorage.setItem(RECENT_KEY, JSON.stringify(n)); return n; });
    try { const r = await api.search(query); setRes(r.results.slice(0, 4)); } catch { /* offline */ }
  };
  return (
    <aside className="rail">
      <Panel icon="mic" title="Voice Assistant" right={listening ? <Pill c="violet">Listening…</Pill> : undefined}>
        <Waveform active={listening} />
        <div className="voicebtns">
          <button className={`bigmic ${listening ? "live" : ""}`} onClick={() => toggleListen()} title={listening ? "Click to stop" : "Talk to AURA"}>
            <Icon n="mic" s={22} />
          </button>
        </div>
        <small className="center dim">{listening ? (transcript || "Listening…") : "Click to talk"}</small>
      </Panel>

      <Panel icon="search" title="Memory Search">
        <div className="msearch"><Icon n="search" s={15} />
          <input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && runSearch(q)} placeholder="Search your memories…" />
        </div>
        {res.length > 0 ? (
          <div className="mres">{res.map((r, i) => (
            <div key={i} className="mrow" onClick={() => setView("memory")}><strong>{r.title.slice(0, 50)}</strong><small>{r.snippet.slice(0, 70)}</small><i>{Math.round((r.relevance || 0) * 100)}% match</i></div>
          ))}</div>
        ) : (
          <>
            <small className="secttl">Recent Searches</small>
            {(recent.length ? recent : ["best resume tips", "client meeting notes", "workout plan", "investment opportunities", "project deadline"]).map((r) => (
              <button key={r} className="recentq" onClick={() => { setQ(r); runSearch(r); }}><Icon n="clock" s={13} />{r}</button>
            ))}
          </>
        )}
      </Panel>

      <Panel icon="grid" title="Multi-Platform Gateway">
        <div className="gwgrid">
          {gw.map((g) => (
            <button key={g.platform} className="gwcell" onClick={() => setView("gateway")} title={`${g.platform}: ${g.status}`}>
              <span className={`gwic ${g.status === "connected" ? "on" : "off"}`}>
                <Icon n={g.platform === "email" ? "mail" : g.platform === "slack" ? "hash" : g.platform === "whatsapp" ? "chat" : g.platform === "discord" ? "users" : "tg"} s={19} />
              </span>
              <small style={{ textTransform: "capitalize" }}>{g.platform}</small>
              <Dot c={g.status === "connected" ? "green" : "red"} />
            </button>
          ))}
        </div>
      </Panel>

      <Panel icon="cpu" title="System Status">
        <div className="syslist">
          <SysRow n="Hermes Agent" ok={online} />
          <SysRow n="Local LFM" ok={online} standby />
          <SysRow n="Memory Engine" ok={online} />
          <SysRow n="SQLite" ok={online} />
          <SysRow n="Gateway" ok={online} />
        </div>
        <div className={`allok ${online ? "" : "bad"}`}><Icon n={online ? "check" : "alert"} s={14} />{online ? "All Systems Operational" : "Backend unreachable — local mode"}</div>
      </Panel>
    </aside>
  );
}

const SysRow = ({ n, ok, standby = false }: { n: string; ok: boolean; standby?: boolean }) => (
  <div className="sysrow"><Icon n={n.includes("Agent") ? "zap" : n.includes("LFM") ? "cpu" : n.includes("Memory") ? "db" : n.includes("SQL") ? "db" : "grid"} s={14} />{n}<Dot c={ok ? (standby ? "amber" : "green") : "red"} /><i>{ok ? (standby ? "Standby" : "Online") : "Offline"}</i></div>
);
