/* AURA OS UI kit — icons, atoms, shell chrome, chat, composer. */
import React, { useEffect, useRef, useState } from "react";
import { ago, api, ChatMsg, md } from "./api";
import { SlashPalette } from "./CommandPalette";
import { catalogFrom, SlashCommand } from "./slash";
import { TKey, useLang } from "./i18n";
import { useStore, View } from "./store";
import { getServer } from "./prefs";
import { initInstallPrompt, promptInstall } from "./install";

/* ================= error boundary (never a black screen) ================= */
export class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { err: string | null }> {
  state = { err: null as string | null };
  static getDerivedStateFromError(e: unknown) { return { err: e instanceof Error ? e.message : "Something went wrong" }; }
  render() {
    if (this.state.err) return (
      <div className="fatal" role="alert"><h1>Aura hit a snag</h1><p>{this.state.err}</p>
        <button className="btn primary" onClick={() => location.reload()}>Reload Aura</button>
      </div>
    );
    return this.props.children;
  }
}

/* ================= icons (single coherent stroke set) ================= */
const P: Record<string, React.ReactNode> = {
  home: <path d="M3 11l9-8 9 8v10a1 1 0 01-1 1h-5v-6h-6v6H4a1 1 0 01-1-1z" />,
  brief: <><rect x="2" y="7" width="20" height="14" rx="2" /><path d="M16 7V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v2M2 13h20" /></>,
  users: <><circle cx="9" cy="7" r="4" /><path d="M2 21v-2a5 5 0 015-5h6a5 5 0 015 5v2M16 3.5a4 4 0 010 7M22 21v-2a5 5 0 00-3-4.6" /></>,
  heart: <path d="M12 21C7 16.5 2 13 2 8.5A4.5 4.5 0 0112 6a4.5 4.5 0 0110 2.5c0 4.5-5 8-10 12.5z" />,
  search: <><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></>,
  mic: <><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 10a7 7 0 0014 0M12 19v3" /></>,
  grid: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
  gear: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 00.3 1.9l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.9-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.2a1.7 1.7 0 00-1-1.5 1.7 1.7 0 00-1.9.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.9 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.2a1.7 1.7 0 001.5-1 1.7 1.7 0 00-.3-1.9l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.9.3h0a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.2a1.7 1.7 0 001 1.5h0a1.7 1.7 0 001.9-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.9v0a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.2a1.7 1.7 0 00-1.4 1z" /></>,
  bell: <><path d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.7 21a2 2 0 01-3.4 0" /></>,
  send: <><path d="M22 2L11 13" /><path d="M22 2l-7 20-4-9-9-4z" /></>,
  down: <><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><path d="M7 10l5 5 5-5" /><path d="M12 15V3" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  file: <><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" /><path d="M14 2v6h6" /></>,
  image: <><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" /></>,
  x: <path d="M18 6L6 18M6 6l12 12" />,
  check: <path d="M20 6L9 17l-5-5" />,
  minus: <path d="M5 12h14" />,
  circle: <circle cx="12" cy="12" r="9" />,
  rocket: <><path d="M4.5 16.5c-1.5 1.3-2 5-2 5s3.7-.5 5-2c.7-.8.7-2 0-2.8-.8-.7-2-.7-3 .8z" /><path d="M12 15l-3-3a22 22 0 012-4A12.9 12.9 0 0122 2c0 2.7-.8 7.5-6 11a22 22 0 01-4 2z" /><path d="M9 12H4s.5-3.7 2-6c1.6-2.4 5-3 5-3M12 15v5s3.7-.5 6-2c2.4-1.6 3-5 3-5" /></>,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /></>,
  zap: <path d="M13 2L3 14h8l-1 8 11-14h-8z" />,
  shield: <><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /><path d="M9 12l2 2 4-4" /></>,
  db: <><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5" /><path d="M3 12c0 1.7 4 3 9 3s9-1.3 9-3" /></>,
  cpu: <><rect x="4" y="4" width="16" height="16" rx="2" /><rect x="9" y="9" width="6" height="6" /><path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3" /></>,
  chat: <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />,
  cal: <><rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" /></>,
  chart: <><path d="M3 3v18h18" /><path d="M7 15l4-6 4 3 5-8" /></>,
  folder: <path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" />,
  trash: <path d="M3 6h18M8 6V4a1 1 0 011-1h6a1 1 0 011 1v2M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6" />,
  edit: <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7M18.5 2.5a2.1 2.1 0 013 3L12 15l-4 1 1-4z" />,
  play: <><circle cx="12" cy="12" r="10" /><path d="M10 8l6 4-6 4z" /></>,
  pause: <><circle cx="12" cy="12" r="10" /><path d="M9 8v8M15 8v8" /></>,
  refresh: <path d="M23 4v6h-6M1 20v-6h6M3.5 9a9 9 0 0114.9-3.4L23 10M1 14l4.6 4.4A9 9 0 0020.5 15" />,
  alert: <><path d="M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z" /><path d="M12 9v4M12 17h.01" /></>,
  chev: <path d="M9 18l6-6-6-6" />,
  spark: <path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9zM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9z" />,
  book: <path d="M4 19.5A2.5 2.5 0 016.5 17H20V2H6.5A2.5 2.5 0 004 4.5zM4 19.5A2.5 2.5 0 006.5 22H20v-5" />,
  target: <><circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="6" /><circle cx="12" cy="12" r="2" /></>,
  wallet: <><rect x="1" y="4" width="22" height="16" rx="2" /><path d="M1 10h22M16 15h2" /></>,
  moon: <path d="M21 12.8A9 9 0 1111.2 3 7 7 0 0021 12.8z" />,
  link: <path d="M10 13a5 5 0 007.5.5l3-3a5 5 0 00-7-7l-1.7 1.7M14 11a5 5 0 00-7.5-.5l-3 3a5 5 0 007 7l1.7-1.7" />,
  more: <><circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" /></>,
  logout: <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9" />,
  wave: <path d="M2 12h2M6 8v8M10 5v14M14 9v6M18 6v12M22 10v4" />,
  eye: <><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></>,
  undo: <><path d="M9 14L4 9l5-5" /><path d="M4 9h10a6 6 0 010 12h-3" /></>,
  pin: <><path d="M9 4h6l-1 7 3 3v2H7v-2l3-3z" /><path d="M12 16v5" /></>,
  star: <path d="M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z" />,
  tg: <path d="M21 4L3 11.2l6.3 2.2L11.5 20l3.7-4.8 5.8 2.1z" />,
  mail: <><rect x="2" y="4" width="20" height="16" rx="2" /><path d="M22 7l-10 6L2 7" /></>,
  hash: <path d="M4 9h16M4 15h16M10 3L8 21M16 3l-2 18" />,
  term: <><path d="M4 17l6-5-6-5" /><path d="M12 19h8" /></>,
  rss: <><path d="M4 11a9 9 0 019 9M4 4a16 16 0 0116 16" /><circle cx="5" cy="19" r="1.5" /></>,
  phone: <path d="M22 16.9v3a2 2 0 01-2.2 2 19.8 19.8 0 01-8.6-3.1 19.5 19.5 0 01-6-6A19.8 19.8 0 012.1 4.2 2 2 0 014.1 2h3a2 2 0 012 1.7c.1.96.4 1.9.7 2.8a2 2 0 01-.5 2.1L8.1 9.9a16 16 0 006 6l1.3-1.3a2 2 0 012.1-.4c.9.3 1.8.5 2.8.7a2 2 0 011.7 2z" />,
  cloud: <path d="M18 10h-1.3A8 8 0 109 20h9a5 5 0 000-10z" />,
};
export const Icon = ({ n, s = 16, className = "" }: { n: string; s?: number; className?: string }) => (
  <svg className={"ic " + className} width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden>{P[n] || P.more}</svg>
);

/* ================= atoms ================= */
export const Panel = ({ icon, title, sub, right, children, className = "", glow = "" }: {
  icon: string; title: string; sub?: string; right?: React.ReactNode; children: React.ReactNode; className?: string; glow?: string;
}) => (
  <section className={`panel ${glow} ${className}`}>
    <header className="phead">
      <span className="picon"><Icon n={icon} s={18} /></span>
      <span className="ptitles"><strong>{title}</strong>{sub && <small>{sub}</small>}</span>
      <span className="pright">{right}</span>
    </header>
    <div className="pbody">{children}</div>
  </section>
);

export const Pill = ({ c = "blue", children }: { c?: string; children: React.ReactNode }) => <span className={`pill ${c}`}>{children}</span>;
export const Dot = ({ c = "green" }: { c?: string }) => <span className={`dot ${c}`} />;
export const Progress = ({ v, c = "" }: { v: number; c?: string }) => (
  <div className="bar"><div className={`barfill ${c}`} style={{ width: `${Math.min(100, Math.max(0, v))}%` }} /></div>
);
export const Empty = ({ icon = "spark", title, sub, action }: { icon?: string; title: string; sub?: string; action?: React.ReactNode }) => (
  <div className="empty"><Icon n={icon} s={30} /><strong>{title}</strong>{sub && <span>{sub}</span>}{action}</div>
);
export const Skel = () => (<div className="skel"><div /><div /><div /></div>);
export const Row = ({ icon, title, sub, right, onClick, c = "" }: { icon: string; title: React.ReactNode; sub?: string; right?: React.ReactNode; onClick?: () => void; c?: string }) => (
  <div className={`rowitem ${onClick ? "click" : ""} ${c}`} onClick={onClick}
    role={onClick ? "button" : undefined} tabIndex={onClick ? 0 : undefined}
    onKeyDown={onClick ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onClick(); } } : undefined}>
    <span className="ricon"><Icon n={icon} s={16} /></span>
    <span className="rtitles"><strong>{title}</strong>{sub && <small>{sub}</small>}</span>
    <span className="rright">{right}</span>
  </div>
);
export const Btn = ({ children, onClick, kind = "", small = false, disabled = false, title }: {
  children: React.ReactNode; onClick?: () => void; kind?: string; small?: boolean; disabled?: boolean; title?: string;
}) => <button className={`btn ${kind} ${small ? "sm" : ""}`} onClick={onClick} disabled={disabled} title={title}>{children}</button>;

/* ================= settings primitives ================= */
export const Toggle = ({ on, onFlip, label }: { on: boolean; onFlip: () => void; label?: string }) => (
  <button className={`toggle ${on ? "on" : ""}`} onClick={onFlip} role="switch" aria-checked={on} aria-label={label || "toggle"} />
);
export const Seg = <T extends string>({ options, value, onPick }: {
  options: { v: T; label: string }[]; value: T; onPick: (v: T) => void;
}) => (
  <div className="seg">{options.map((o) => (
    <button key={o.v} className={value === o.v ? "on" : ""} aria-pressed={value === o.v} onClick={() => onPick(o.v)}>{o.label}</button>
  ))}</div>
);
export const Slider = ({ value, min, max, step = 1, onPick, format }: {
  value: number; min: number; max: number; step?: number; onPick: (v: number) => void; format?: (v: number) => string;
}) => (
  <span style={{ display: "inline-flex", gap: 8, alignItems: "center" }}>
    <input type="range" className="slider" min={min} max={max} step={step} value={value}
      onChange={(e) => onPick(Number(e.target.value))} />
    <small className="dim" style={{ minWidth: 52, textAlign: "right" }}>{format ? format(value) : value}</small>
  </span>
);
export const SetRow = ({ title, sub, control }: { title: string; sub?: string; control: React.ReactNode }) => (
  <div className="setrow"><div className="grow"><strong style={{ fontSize: 12.5 }}>{title}</strong>{sub && <small className="dim">{sub}</small>}</div>{control}</div>
);

/* ================= sidebar ================= */
const NAV: { v: View; icon: string; key: TKey; section?: TKey }[] = [
  { v: "home", icon: "home", key: "nav.home" },
  { v: "career", icon: "brief", key: "nav.career" },
  { v: "clients", icon: "users", key: "nav.clients" },
  { v: "personal", icon: "heart", key: "nav.personal" },
  { v: "inbox", icon: "mail", key: "nav.inbox" },
  { v: "calendar", icon: "cal", key: "nav.calendar" },
  { v: "memory", icon: "search", key: "nav.memory" },
  { v: "sessions", icon: "chat", key: "nav.sessions" },
  { v: "voice", icon: "mic", key: "nav.voice" },
  { v: "feeds", icon: "rss", key: "nav.feeds" },
  { v: "gateway", icon: "grid", key: "nav.gateway" },
  { v: "board", icon: "rocket", key: "nav.board" },
  { v: "automations", icon: "zap", key: "nav.automations", section: "nav.system" },
  { v: "activity", icon: "clock", key: "nav.activity" },
  { v: "analytics", icon: "chart", key: "nav.analytics" },
  { v: "smarthome", icon: "home", key: "nav.smarthome" },
  { v: "files", icon: "folder", key: "nav.files" },
  { v: "terminal", icon: "term", key: "nav.terminal" },
  { v: "models", icon: "cpu", key: "nav.models" },
  { v: "settings", icon: "gear", key: "nav.settings" },
];

export function Sidebar() {
  const { view, setView, dash, online, pendingApprovals } = useStore();
  const { t } = useLang();
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem("aura_nav") === "c");
  useEffect(() => localStorage.setItem("aura_nav", collapsed ? "c" : "e"), [collapsed]);
  let lastSection = "";
  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <button className="brand" aria-label="AURA OS home" onClick={() => setView("home")}>
        <svg width="34" height="34" viewBox="0 0 32 32"><defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#38bdf8" /><stop offset="1" stopColor="#a855f7" /></linearGradient></defs><path fill="url(#lg)" d="M16 1l13 29h-7.5L16 16.5 10.5 30H3z" /><path fill="#e0f2fe" opacity=".85" d="M16 12l4.5 10h-2.6L16 17.4 14.1 22h-2.6z" /></svg>
        {!collapsed && <span><strong>AURA OS</strong><small>{t("nav.tagline")}</small></span>}
      </button>
      <nav className="nav" aria-label="Main navigation">
        {NAV.map((n) => {
          const head = n.section && n.section !== lastSection ? (<div key={n.section} className="navsec">{!collapsed && t(n.section)}</div>) : null;
          lastSection = n.section || lastSection;
          return (
            <React.Fragment key={n.v}>
              {head}
              <button className={`navitem ${view === n.v ? "active" : ""}`} onClick={() => setView(n.v)} title={t(n.key)} aria-label={t(n.key)} aria-current={view === n.v ? "page" : undefined}>
                <Icon n={n.icon} s={18} />{!collapsed && <span>{t(n.key)}</span>}
                {!collapsed && n.v === "activity" && pendingApprovals > 0 && <em className="badge">{pendingApprovals}</em>}
              </button>
            </React.Fragment>
          );
        })}
      </nav>
      {!collapsed && (
        <div className="sideplats">
          <small>{t("nav.connected")}</small>
          {(dash?.gateway || []).map((g) => (
            <div key={g.platform} className="sideplat">
              <Icon n={g.platform === "email" ? "mail" : g.platform === "slack" ? "hash" : "tg"} s={15} />
              <span style={{ textTransform: "capitalize" }}>{g.platform}</span>
              <Dot c={g.status === "connected" ? "green" : "red"} /><i>{g.status}</i>
            </div>
          ))}
        </div>
      )}
      <div className="sidefoot">
        {!collapsed && <div className="hermes"><Icon n="zap" s={16} /><span>Hermes Agent v2.0.0<small>{online ? t("nav.powered") : t("nav.offline")}</small></span></div>}
        <button className="collapsebtn" onClick={() => setCollapsed(!collapsed)} title={collapsed ? "Expand" : "Collapse"}>‹</button>
      </div>
    </aside>
  );
}

/* ================= topbar ================= */
export function UndoButton({ watch }: { watch: unknown }) {
  const { t } = useLang();
  const { toast } = useStore();
  const [label, setLabel] = useState<string | null>(null);
  const load = async () => {
    try {
      const r = await api.undo.preview();
      setLabel(r.undoable ? (r.journal[0]?.summary || "?") : null);
    } catch { setLabel(null); }
  };
  useEffect(() => { load(); }, [watch]);
  if (label === null) return null;
  return (
    <button className="iconbtn" title={`${t("top.undo")}: ${label}`} onClick={async () => {
      try {
        const r = await api.undo.apply();
        const u = r.undone[0];
        toast(u ? u.result : t("top.nothing"), u ? "success" : "warn");
      } catch { toast(t("top.nothing"), "warn"); }
      load();
    }}><Icon n="undo" s={18} /></button>
  );
}

export function TopBar() {
  const { setPalette, lfm, online, me, dash, toast, setView, refresh, activeModel } = useStore();
  const { t } = useLang();
  const [showNotes, setShowNotes] = useState(false);
  const notes = dash?.notifications || [];
  const [canInst, setCanInst] = useState(false);
  useEffect(() => { initInstallPrompt(setCanInst); }, []);
  const unread = dash?.counts.unread || 0;
  const am = activeModel;
  const isCloud = am?.backend === "cloud";
  const isLocal = am?.backend === "ollama";
  const isBuiltin = am?.backend === "builtin";
  const indicatorColor = isCloud ? (am.cloud_configured ? "green" : "amber")
    : isLocal ? (am.local_online ? "green" : "amber")
    : "blue";
  const indicatorText = isCloud ? (am.cloud_configured ? "Cloud Ready" : "Cloud Not Configured")
    : isLocal ? (am.local_online ? "Local Online" : "Local Offline")
    : "Builtin Engine";
  const modelLabel = am ? `${am.provider}: ${am.model}` : lfm;
  return (
    <header className="topbar">
      <button className="gsearch" onClick={() => setPalette(true)}>
        <Icon n="search" s={16} /><span>{t("top.search")}</span><kbd>Ctrl + K</kbd>
      </button>
      <div className="topright">
        <span className={`lfm ${online ? "on" : "off"}`} title={`Privacy: ${am?.privacy_mode || "local-first"} · Backend: ${am?.backend || "unknown"}`}>
          <Dot c={indicatorColor} /><span>{modelLabel}<small>{indicatorText}</small></span>
        </span>
        <button className="iconbtn" onClick={() => setShowNotes(!showNotes)} title={t("top.notifications")}>
          <Icon n="bell" s={18} />{unread > 0 && <em className="badge">{unread}</em>}
        </button>
        <UndoButton watch={dash} />
{canInst && <button className="iconbtn" onClick={async () => { if (await promptInstall()) { setCanInst(false); toast("AURA installed", "success"); } }} title="Install AURA app"><Icon n="down" s={18} /></button>}
        <button className="iconbtn" onClick={() => setView("settings")} title={t("nav.settings")}><Icon n="shield" s={18} /></button>
        <button className="avatar" onClick={() => setView("settings")} title={me?.name}>
          <span className="aface">{(me?.name || "A")[0]}</span>
          <span className="aname"><strong>{me?.name || "Antony"}</strong><small>{me?.role || "Builder"}</small></span>
        </button>
      </div>
      {showNotes && (
        <div className="notesdrop">
          <header><strong>{t("top.notifications")}</strong><button className="link" onClick={() => { api.notes.readAll().then(() => refresh()).catch(() => undefined); setShowNotes(false); toast(t("top.allcaught"), "success"); }}>{t("top.markread")}</button></header>
          {notes.length === 0 && <Empty title={t("top.nonotes")} sub={t("top.caughtup")} />}
          {notes.map((n) => (
            <div key={n.id} className={`note ${n.read ? "" : "unread"}`}>
              <Dot c={n.level === "warn" ? "amber" : n.level === "critical" ? "red" : "blue"} />
              <div><strong>{n.title}</strong><small>{n.body}</small><i>{ago(n.created_at)}</i></div>
            </div>
          ))}
        </div>
      )}
    </header>
  );
}

/* ================= command palette ================= */
export function CommandPalette() {
  const { palette, setPalette, setView, send, refresh, toast, loadSession, newChat, setCall } = useStore();
  const { t } = useLang();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<{ type: string; title: string; snippet: string; matched?: string }[]>([]);
  const [sess, setSess] = useState<{ id: string; title: string; n: number }[]>([]);
  const input = useRef<HTMLInputElement>(null);
  const dialog = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!palette) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    let active = true;
    setQ(""); setResults([]);
    api.sessions.list().then((r) => { if (active) setSess(r.sessions.slice(0, 6)); }).catch(() => undefined);
    input.current?.focus();
    return () => { active = false; previous?.focus(); };
  }, [palette]);
  useEffect(() => {
    if (!palette || q.length < 2) { setResults([]); return; }
    const t = setTimeout(() => api.search(q).then((r) => setResults(r.results.slice(0, 6))).catch(() => undefined), 250);
    return () => clearTimeout(t);
  }, [q, palette]);
  if (!palette) return null;
  const go = (v: View) => { setView(v); setPalette(false); };
  const ask = (t: string) => { setPalette(false); setView("home"); send(t); };
  const acts = [
    { icon: "cal", label: t("pal.plan"), fn: () => ask("plan my day") },
    { icon: "users", label: t("pal.review"), fn: () => ask("review my client workload") },
    { icon: "brief", label: t("pal.resume"), fn: () => go("career") },
    { icon: "plus", label: t("pal.task"), fn: () => ask("create a task to ") },
    { icon: "plus", label: t("pal.project"), fn: () => ask("new project ") },
    { icon: "search", label: t("pal.memory"), fn: () => go("memory") },
    { icon: "mic", label: t("pal.voice"), fn: () => go("voice") },
    { icon: "db", label: t("pal.backup"), fn: () => { api.backup.run().then(() => { toast("Backup completed", "success"); refresh(); }); setPalette(false); } },
    { icon: "zap", label: t("pal.auto"), fn: () => go("automations") },
    { icon: "heart", label: t("pal.mood"), fn: () => ask("log mood ") },
    { icon: "plus", label: t("pal.chat"), fn: () => { newChat(); setPalette(false); } },
    { icon: "term", label: t("pal.terminal"), fn: () => go("terminal") },
    { icon: "cpu", label: t("pal.models"), fn: () => go("models") },
    { icon: "rss", label: t("pal.feeds"), fn: () => go("feeds") },
    { icon: "phone", label: t("pal.call"), fn: () => { setPalette(false); setCall(true); } },
  ].filter((a) => a.label.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="palwrap" onClick={() => setPalette(false)}>
      <div ref={dialog} className="palette" role="dialog" aria-modal="true" aria-label={t("top.search")} onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          if (e.key === "Escape") { e.stopPropagation(); setPalette(false); }
          if (e.key !== "Tab") return;
          const items = dialog.current?.querySelectorAll<HTMLElement>('input, button:not(:disabled)');
          if (!items?.length) return;
          const first = items[0], last = items[items.length - 1];
          if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
          else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }}>
        <div className="palinput"><Icon n="search" s={18} />
          <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("pal.placeholder")} aria-label={t("pal.placeholder")}
            onKeyDown={(e) => { if (e.key === "Enter" && q.trim()) ask(q); }} />
          <kbd>esc</kbd>
        </div>
        <div className="palbody">
          <small>Actions</small>
          {acts.map((a) => <button key={a.label} className="palitem" onClick={a.fn}><Icon n={a.icon} s={16} />{a.label}</button>)}
          {sess.length > 0 && q.length < 2 && <><small>Recent conversations</small>
            {sess.map((s) => <button key={s.id} className="palitem" onClick={() => { loadSession(s.id); setPalette(false); }}><Icon n="chat" s={16} /><span><strong>{(s.title || "Conversation").slice(0, 52)}</strong><small>{s.n} messages</small></span></button>)}
          </>}
          {results.length > 0 && <><small>Search results</small>
            {results.map((r, i) => <button key={i} className="palitem" onClick={() => ask(`tell me about ${r.title}`)}>
              <Pill c="violet">{r.type}</Pill><span><strong>{r.title}</strong>
                <small>{r.matched ? `${r.matched}` : r.snippet.slice(0, 80)}</small>
              </span>
            </button>)}
          </>}
        </div>
      </div>
    </div>
  );
}

/* ================= toasts ================= */
export function Toasts() {
  const { toasts } = useStore();
  return (
    <div className="toasts">
      <div className="toast-live" role="status" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className={`toast ${t.kind}`}><Icon n={t.kind === "success" ? "check" : t.kind === "error" ? "alert" : "bell"} s={15} />{t.text}</div>)}
      </div>
    </div>
  );
}

/* ================= plan + approval + chat ================= */
export function PlanSteps({ steps }: { steps: { id: string; label: string; status: string }[] }) {
  if (!steps || steps.length === 0) return null;
  return (
    <div className="planbox">
      <small>AURA PLAN</small>
      {steps.map((s) => (
        <div key={s.id} className={`pstep ${s.status}`}>
          <span className="psic">{s.status === "done" ? <Icon n="check" s={13} /> : s.status === "running" ? <span className="spin" /> : s.status === "waiting_approval" ? <Icon n="clock" s={13} /> : s.status === "error" ? <Icon n="x" s={13} /> : <span className="pdot" />}</span>
          {s.label}
        </div>
      ))}
    </div>
  );
}

export function MissionLive({ missions }: { missions: NonNullable<ChatMsg["missions"]> }) {
  if (!missions || missions.length === 0) return null;
  const mark: Record<string, string> = { done: "✓", running: "▸", awaiting: "…", failed: "✗" };
  return (
    <div className="planbox">
      <small>MISSIONS</small>
      {missions.map((m) => (
        <div key={m.id}>
          <div className="pstep running" style={{ fontWeight: 600 }}>{m.goal} <span className="muted">· {m.status}</span></div>
          {(m.steps || []).slice(0, 6).map((s, i) => (
            <div key={i} className={`pstep ${s.status}`} style={{ paddingLeft: 14 }}>
              <span className="psic">{mark[s.status] || <span className="pdot" />}</span>
              {s.label}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

export function ApprovalCard({ approval, onDone }: { approval: NonNullable<ChatMsg["approval"]>; onDone?: () => void }) {
  const { toast, refresh, setOrb } = useStore();
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const [failedCount, setFailedCount] = useState(0);
  const [editing, setEditing] = useState(false);
  const [drafts, setDrafts] = useState(approval?.drafts || []);
  if (!approval) return null;
  if (done) return (
    <div className="approval done">
      <Icon n={done === "approved" ? "check" : done === "failed" ? "alert" : "x"} s={16} />
      <strong>{done === "approved" ? "Approved and sent via gateway" : done === "failed" ? `${failedCount} of ${approval.drafts.length} message(s) failed to send` : `Approval ${done}`}</strong>
    </div>
  );
  const resolve = async (decision: "approved" | "rejected") => {
    setBusy(true);
    try {
      const r = await api.approvals.resolve(approval.id, decision, editing ? drafts : undefined);
      if (decision === "approved" && r.errors && r.errors.length > 0) {
        toast(`${r.errors.length} of ${approval.drafts.length} message(s) failed to send: ${(r.errors[0] || "").slice(0, 140)}`, "error");
        setFailedCount(r.errors.length);
        setDone("failed");
        setOrb("error");
      } else {
        toast(decision === "approved" ? "Approved and sent via gateway" : "Approval rejected", decision === "approved" ? "success" : "warn");
        setDone(decision);
        setOrb(decision === "approved" ? "success" : "idle");
      }
      refresh(); onDone?.();
    } catch { toast("Could not resolve approval", "error"); }
    setBusy(false);
  };
  return (
    <div className="approval">
      <header><Icon n="shield" s={16} /><strong>AURA wants to send {approval.drafts.length} message{approval.drafts.length !== 1 ? "s" : ""}</strong><Pill c="amber">{approval.risk}</Pill></header>
      {(editing ? drafts : approval.drafts).slice(0, 3).map((d, i) => (
        <div key={i} className="draft"><strong>To {d.to}</strong><em>{d.subject}</em>
          {editing
            ? <textarea className="ta" rows={3} value={d.body} onChange={(e) => setDrafts(drafts.map((x, j) => (j === i ? { ...x, body: e.target.value } : x)))} />
            : <p>{d.body}</p>}
        </div>
      ))}
      <div className="apbtns">
        <Btn kind="green" small disabled={busy} onClick={() => resolve("approved")}><Icon n="check" s={14} /> {editing ? "Save and Send" : "Approve and Send"}</Btn>
        <Btn small disabled={busy} onClick={() => setEditing(!editing)}><Icon n="edit" s={14} /> {editing ? "Done" : "Edit"}</Btn>
        <Btn small disabled={busy} onClick={() => resolve("rejected")}><Icon n="x" s={14} /> Reject</Btn>
      </div>
    </div>
  );
}

export function ChatThread({ compact = false }: { compact?: boolean }) {
  const { msgs, sending, speak, speaking, stopSpeak } = useStore();
  const showTs = getServer("chat_timestamps", false);
  const ts = (t: number) => {
    try { return new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Africa/Nairobi" }).format(new Date(t)); }
    catch { return ""; }
  };
  const end = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const [showNewMsg, setShowNewMsg] = useState(false);
  const userScrolledUp = useRef(false);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const handleScroll = () => {
      const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
      userScrolledUp.current = !nearBottom;
      setShowNewMsg(userScrolledUp.current);
    };
    el.addEventListener("scroll", handleScroll, { passive: true });
    return () => el.removeEventListener("scroll", handleScroll);
  }, []);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
    if (nearBottom && !userScrolledUp.current) {
      end.current?.scrollIntoView({ behavior: "smooth", block: "end" });
      setShowNewMsg(false);
    }
  }, [msgs, sending]);

  const scrollToBottom = () => {
    const el = box.current;
    if (el) {
      userScrolledUp.current = false;
      setShowNewMsg(false);
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    }
  };

  if (msgs.length === 0) return (
    <div className="thread empty" aria-live="polite" style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center" }}>
      {speaking && <Btn small onClick={stopSpeak}>Stop speaking</Btn>}
      <div className="chat-placeholder">
        <strong>Start a conversation</strong>
        <span>Type a message below to chat with AURA.</span>
      </div>
    </div>
  );
  return (
    <div ref={box} className={`thread ${compact ? "compact" : ""}`} style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      {speaking && <div style={{ position: "sticky", top: 0, zIndex: 1, background: "var(--surface)", borderBottom: "1px solid var(--border)" }}><Btn small onClick={stopSpeak}>Stop speaking</Btn></div>}
      {msgs.map((m) => (
        <div key={m.id} className={`msg ${m.role}`}>
          {m.role === "user" ? (
            <div className="bubble user">{m.text}
              {(m.files?.length || 0) > 0 && (
                <div className="attchips">{m.files!.map((f) => (
                  /\.(png|jpe?g|gif|webp|bmp)$/i.test(f.name)
                    ? <a key={f.id} href={`/api/files/${f.id}`} target="_blank" rel="noreferrer">
                        <img src={`/api/files/${f.id}`} alt={f.name} title={f.name} style={{ maxWidth: 120, maxHeight: 90, borderRadius: 8 }} /></a>
                    : <span key={f.id}><Icon n="file" s={12} />{f.name}</span>
                ))}</div>
              )}
              {showTs && <small className="ts">{ts(m.ts)}</small>}
            </div>
          ) : (
            <div className="abubble">
              <PlanSteps steps={m.steps || []} />
              <MissionLive missions={m.missions || []} />
              {(m.vision?.length || 0) > 0 && (
                <div className="memchips">{m.vision!.map((v) => (
                  <span key={v.file} className="memchip" title={v.model || v.status}>
                    <Icon n={v.status === "done" ? "image" : v.status === "unavailable" ? "x" : "search"} s={12} />
                    {v.status === "analyzing" ? `Seeing ${v.file}…` : v.status === "done" ? `Saw ${v.file}` : `${v.file} unseen`}
                  </span>))}</div>
              )}
              {m.thinking && m.thinking.length > 0 && (
                <details className="thinking-block" open>
                  <summary className="thinking-summary">
                    <Icon n="spark" s={12} className="thinking-icon" />
                    <span>Thinking…</span>
                    <Icon n="chev" s={10} className="thinking-chev" />
                  </summary>
                  <div className="thinking-content">
                    {m.thinking.map((t, i) => (
                      <div key={i} className="thinking-line">{t}</div>
                    ))}
                  </div>
                </details>
              )}
              {m.text ? <div className="md" dangerouslySetInnerHTML={{ __html: md(m.text) }} /> : (sending && !m.thinking && <span className="typing"><i /><i /><i /></span>)}
              {(m.memories?.length || 0) > 0 && (
                <div className="memchips">{m.memories!.map((x) => <span key={x.id} className="memchip" title={`relevance ${x.relevance}`}><Icon n="db" s={12} />{x.title.slice(0, 42)}</span>)}</div>
              )}
              {m.approval && <ApprovalCard approval={m.approval} />}
              {m.text && m.role === "assistant" && (
                <div className="msgacts">
                  <button onClick={() => speak(m.text)} title="Read aloud"><Icon n="wave" s={13} /> Speak</button>
                  {showTs && <small>{ts(m.ts)}</small>}
                  {m.model && <small>{m.model}</small>}
                </div>
              )}
            </div>
          )}
        </div>
      ))}
      {showNewMsg && (
        <button className="new-msg-indicator" onClick={scrollToBottom} aria-label="Scroll to latest message">
          <Icon n="chev" s={14} /> New messages
        </button>
      )}
      <div ref={end} />
    </div>
  );
}

/* ================= waveform ================= */
export function Waveform({ active, bars = 42, h = 44 }: { active: boolean; bars?: number; h?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const { micLevel } = useStore();
  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return; // headless/odd browsers: static canvas, no crash
    let raf = 0;
    const t0 = Date.now();
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const W = cv.width, H = cv.height;
      ctx.clearRect(0, 0, W, H);
      const t = (Date.now() - t0) / 1000;
      const lvl = active ? 0.35 + micLevel.current * 0.9 : 0.12;
      const bw = W / bars;
      for (let i = 0; i < bars; i++) {
        const w = Math.sin(i * 0.55 + t * (active ? 6 : 1.4)) * 0.5 + 0.5;
        const bh = Math.max(3, w * lvl * H * (0.6 + 0.4 * Math.sin(i * 0.2 + t * 2)));
        const x = i * bw + bw * 0.2;
        const grad = ctx.createLinearGradient(0, H / 2 - bh / 2, 0, H / 2 + bh / 2);
        grad.addColorStop(0, "#38bdf8"); grad.addColorStop(1, "#a855f7");
        ctx.fillStyle = grad;
        ctx.globalAlpha = active ? 0.95 : 0.4;
        ctx.beginPath();
        if (typeof (ctx as unknown as { roundRect?: unknown }).roundRect === "function") {
          (ctx as unknown as { roundRect: (x: number, y: number, w: number, h: number, r: number) => void }).roundRect(x, H / 2 - bh / 2, bw * 0.6, bh, 3);
        } else {
          ctx.rect(x, H / 2 - bh / 2, bw * 0.6, bh);
        }
        ctx.fill();
      }
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, [active, bars, micLevel]);
  return <canvas ref={ref} width={bars * 7} height={h} className="wave" />;
}

const EMOJIS = [
  "😀","😃","😄","😁","😆","😅","🤣","😂","🙂","🙃","😉","😊","😇","🥰","😍","🤩","😘","😗","☺️","😚","😙","😋","😛","😜","🤪","😝","🤑","🤗","🤭","🤫","🤔","🤐","🤨","😐","😑","😶","😏","😒","🙄","😬","🤥","😌","😔","😪","🤤","😴","😷","🤒","🤕","🤢","🤮","🤧","🥵","🥶","🥴","😵","🤯","🤠","🥳","😎","🤓","🧐","😕","😟","🙁","☹️","😮","😯","😲","😳","🥺","😦","😧","😨","😰","😥","😢","😭","😱","😖","😣","😞","😓","😩","😫","😤","😡","😠","🤬","😈","👿","💀","☠️","💩","🤡","👻","👽","👾","🤖","😺","😸","😹","😻","😼","😽","🙀","😿","😾","👋","🤚","🖐","✋","🖖","👌","🤌","🤏","✌️","🤞","🤟","🤘","🤙","👈","👉","👆","🖕","👇","☝️","👍","👎","✊","👊","🤛","🤜","👏","🙌","👐","🤲","🤝","🙏","✍️","💅","🤳","💪","🦾","🦿","🦵","🦶","👂","🦻","👃","🧠","🫀","🫁","🦷","🦴","👀","👁","👅","👄","💋","🩸","👶","🧒","👦","👧","🧑","👱","👨","👩","🧓","👴","👵","🙍","🙎","🙅","🙆","💁","🙋","🙇","🤦","🤷","🧑‍🦽","🧑‍🦼","🧑‍🦯","🏃","💃","🕺","🕴️","🧍","🧎","🧑‍🦽","🧑‍🦼","🧑‍🦯","🏃","💃","🕺","🕴️","🧍","🧎","🛌","🧑‍🤝‍🧑","👭","👫","👬","💏","💑","👨‍👩‍👧","👨‍👩‍👧‍👦","👨‍👩‍👦‍👦","👨‍👩‍👧‍👧","👩‍👩‍👦","👩‍👩‍👦‍👦","👩‍👩‍👧","👩‍👩‍👧‍👧","👨‍👨‍👦","👨‍👨‍👦‍👦","👨‍👨‍👧","👨‍👨‍👧‍👧","👨‍👦","👨‍👦‍👦","👨‍👧","👨‍👧‍👧","👩‍👦","👩‍👦‍👦","👩‍👧","👩‍👧‍👧","🗣️","👤","👥","🫂","👪","🧑‍🤝‍🧑","👭","👫","👬","💏","💑","👨‍👩‍👧","👨‍👩‍👧‍👦","👨‍👩‍👦‍👦","👨‍👩‍👧‍👧","👩‍👩‍👦","👩‍👩‍👦‍👦","👩‍👩‍👧","👩‍👩‍👧‍👧","👨‍👨‍👦","👨‍👨‍👦‍👦","👨‍👨‍👧","👨‍👨‍👧‍👧","👨‍👦","👨‍👦‍👦","👨‍👧","👨‍👧‍👧","👩‍👦","👩‍👦‍👦","👩‍👧","👩‍👧‍👧","🗣️","👤","👥","🫂","🧠","🫀","🫁","🦷","🦴","👀","👁","👅","👄","💋","🩸"
];

/* ================= composer ================= */
export function Composer({ big = false }: { big?: boolean }) {
  const { send, sending, listening, toggleListen, transcript, toast, refresh, newChat, composerFocus, stopGenerating } = useStore();
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [showEmoji, setShowEmoji] = useState(false);
  const ta = useRef<HTMLTextAreaElement>(null);
  const wasListening = useRef(false);
  const fref = useRef<HTMLInputElement>(null);
  const iref = useRef<HTMLInputElement>(null);
  const lastFocusReq = useRef(0);
  const emojiRef = useRef<HTMLDivElement>(null);
  const cmdRef = useRef<HTMLDivElement>(null);
  const [showCmds, setShowCmds] = useState(false);
  const [cmdQuery, setCmdQuery] = useState("");
  const [cmdCatalog, setCmdCatalog] = useState<SlashCommand[]>([]);
  // Fetched on open, not on mount: the palette is dead weight until the user
  // actually types a slash.
  useEffect(() => {
    if (!showCmds) return;
    let live = true;
    api.slash.catalog()
      .then((r) => { if (live) setCmdCatalog(catalogFrom(r)); })
      .catch(() => { if (live) setCmdCatalog([]); });
    return () => { live = false; };
  }, [showCmds]);
  useEffect(() => {
    if (composerFocus !== lastFocusReq.current) {
      lastFocusReq.current = composerFocus;
      ta.current?.focus();
    }
  }, [composerFocus]);
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (emojiRef.current && !emojiRef.current.contains(e.target as Node)) {
        setShowEmoji(false);
      }
      // The palette floats above the composer, so its own backdrop click never
      // fires — without this it stays open over the chat after the user clicks
      // back into the message box.
      if (cmdRef.current && !cmdRef.current.contains(e.target as Node)) {
        setShowCmds(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);
  const insertEmoji = (emoji: string) => {
    setText((prev) => prev + emoji);
    ta.current?.focus();
  };
  const submit = async () => {
    if (sending) return;
    let atts: unknown[] = [];
    if (files.length) {
      try {
        const dt = new DataTransfer();
        files.forEach((f) => dt.items.add(f));
        const r = await api.files.upload(dt.files);
        atts = r.files;
        toast(`${r.files.length} file(s) attached & indexed`, "success");
        refresh();
      } catch { toast("File upload failed", "error"); return; }
    }
    const t = text;
    setText(""); setFiles([]);
    await send(t || (atts.length ? "I've attached files — review them." : ""), atts);
  };
  useEffect(() => { if (transcript) setText(transcript); }, [transcript]);
  useEffect(() => {
    if (wasListening.current && !listening) setText("");
    wasListening.current = listening;
  }, [listening]);
  return (
    <div className={`composer ${big ? "big" : ""}`}>
      <input ref={fref} type="file" multiple hidden aria-label="Attach files"
        onChange={(e) => { setFiles([...files, ...Array.from(e.target.files || [])]); e.target.value = ""; }} />
      <input ref={iref} type="file" accept="image/*" multiple hidden aria-label="Attach image"
        onChange={(e) => { setFiles([...files, ...Array.from(e.target.files || [])]); e.target.value = ""; }} />
      <textarea
        ref={ta} rows={big ? 3 : 2} value={listening ? (transcript || "Listening… speak now") : text}
        onChange={(e) => {
          const v = e.target.value;
          setText(v);
          // Position 0 only — a `/` mid-sentence is prose (FR-CMD-001).
          if (v.startsWith("/")) { setCmdQuery(v); setShowCmds(true); }
          else setShowCmds(false);
        }}
        onKeyDown={(e) => {
          const ets = getServer("enter_to_send", true);
          if (e.key === "Enter" && (ets ? !e.shiftKey : (e.ctrlKey || e.metaKey))) { e.preventDefault(); submit(); }
        }}
        placeholder="Ask me anything… (type, speak or upload)" aria-label="Message AURA"
      />
      {files.length > 0 && <div className="attchips">{files.map((f, i) => <span key={i}><Icon n="file" s={12} />{f.name}<button onClick={() => setFiles(files.filter((_, j) => j !== i))}><Icon n="x" s={12} /></button></span>)}</div>}
      <div className="crow">
        <div className="cbtns">
          <button onClick={() => fref.current?.click()} title="Attach file"><Icon n="plus" s={14} /> Attach</button>
          <button onClick={() => iref.current?.click()} title="Upload image"><Icon n="image" s={14} /> Image</button>
          <button className={listening ? "live" : ""} onClick={() => toggleListen()} title="Voice input"><Icon n="mic" s={14} /> {listening ? "Stop" : "Voice"}</button>
          <button onClick={() => fref.current?.click()} title="Files"><Icon n="file" s={14} /> File</button>
          <button onClick={newChat} title="Start a new conversation"><Icon n="plus" s={14} /> New</button>
          <button onClick={() => setShowEmoji(!showEmoji)} title="Emoji picker"><Icon n="spark" s={14} /></button>
        </div>
        <div className="cright">
          <Waveform active={listening || sending} bars={18} h={26} />
          {sending && <button className="sendbtn" onClick={stopGenerating} title="Stop generating"><Icon n="square" s={18} /></button>}
          <button className="sendbtn" onClick={submit} disabled={sending} title="Send"><Icon n="send" s={18} /></button>
        </div>
      </div>
      {showCmds && cmdCatalog.length > 0 && (
        <div ref={cmdRef}>
          <SlashPalette catalog={cmdCatalog} query={cmdQuery}
            onClose={() => setShowCmds(false)}
            onPick={(c) => {
              setShowCmds(false);
              // Commands that take an argument get a trailing space so the user
              // can keep typing instead of having to aim for the end of the line.
              setText(c.arg ? `${c.name} ` : c.name);
              ta.current?.focus();
            }} />
        </div>
      )}
      {showEmoji && (
        <div ref={emojiRef} className="emoji-picker">
          <div className="emoji-search"><input type="text" placeholder="Search emojis…" onChange={(e) => { /* filter */ }} /></div>
          <div className="emoji-grid">
            {EMOJIS.map((emoji) => (
              <button key={emoji} className="emoji-btn" onClick={() => insertEmoji(emoji)}>{emoji}</button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* Nairobi clock hook */
export function useNairobiClock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 10000); return () => clearInterval(t); }, []);
  const date = new Intl.DateTimeFormat("en", { weekday: "short", month: "short", day: "numeric", year: "numeric", timeZone: "Africa/Nairobi" }).format(now);
  const time = new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Africa/Nairobi" }).format(now);
  return { date, time };
}

export const fmtDate = (iso: string | null) => {
  if (!iso) return "—";
  try { return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", timeZone: "Africa/Nairobi" }).format(new Date(iso)); }
  catch { return iso.slice(0, 10); }
};
