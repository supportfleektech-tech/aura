/* AURA OS workspaces III — Inbox, Calendar, Briefings. */
import { useEffect, useState } from "react";
import { api, Briefing, BriefRun, Cal, CalEvent, Mail, MailFull, Session, md } from "./api";
import { useStore } from "./store";
import { useLang } from "./i18n";
import { Field, useFetch } from "./views1";
import { Btn, ChatThread, Composer, Empty, Icon, Panel, Pill, Row, Seg, Skel } from "./ui";

const nboTime = (iso: string) => {
  try { return new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Africa/Nairobi" }).format(new Date(iso)); }
  catch { return (iso || "").slice(11, 16); }
};
const nboDay = (iso: string) => {
  try { return new Intl.DateTimeFormat("en", { weekday: "short", month: "short", day: "numeric", timeZone: "Africa/Nairobi" }).format(new Date(iso)); }
  catch { return (iso || "").slice(0, 10); }
};
const triC = (t: string) => (t === "action" ? "red" : t === "waiting" ? "amber" : t === "fyi" ? "blue" : t === "done" ? "green" : "violet");

/* ============================== INBOX ============================== */
export function InboxView() {
  const { t } = useLang();
  const { toast, refresh, send } = useStore();
  const { data: accData, reload: racc } = useFetch(() => api.mail.accounts());
  const [filter, setFilter] = useState("");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [mails, setMails] = useState<Mail[]>([]);
  const [unread, setUnread] = useState(0);
  const [sel, setSel] = useState<number | null>(null);
  const [full, setFull] = useState<MailFull | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [name, setName] = useState("");
  const [mode, setMode] = useState("sandbox");
  const [host, setHost] = useState(""); const [port, setPort] = useState("993");
  const [user, setUser] = useState(""); const [pass, setPass] = useState("");
  const loadMails = async () => {
    const qs = `${filter ? `?triage=${filter}` : "?x=1"}${unreadOnly ? "&unread_only=true" : ""}`;
    try { const r = await api.mail.emails(qs); setMails(r.emails); setUnread(r.unread); }
    catch { /* offline */ }
  };
  useEffect(() => { loadMails(); }, [filter, unreadOnly]); // eslint-disable-line react-hooks/exhaustive-deps
  const openMail = async (id: number) => {
    setSel(id);
    try {
      const m = await api.mail.get(id);
      setFull(m);
      if (!m.seen) { await api.mail.set(id, { seen: true }); loadMails(); racc(); refresh(); }
    } catch { toast("Could not open message", "error"); }
  };
  const syncAll = async () => {
    for (const a of accData?.accounts || []) {
      try {
        const r = await api.mail.sync(a.id);
        toast(r.ok ? `${a.name}: ${r.new} new` : `${a.name} failed: ${r.error || ""}`, r.ok ? "success" : "error");
      } catch (e) { toast(`${a.name}: ${e instanceof Error ? e.message : e}`, "error"); }
    }
    racc(); loadMails(); refresh();
  };
  const accounts = accData?.accounts || [];
  return (
    <div className="view">
      <div className="vhead"><h2><Icon n="mail" s={20} /> {t("title.inbox")}</h2>
        <Pill c={unread ? "amber" : "green"}>{unread} unread</Pill><span style={{ flex: 1 }} />
        <Btn small onClick={syncAll}>Sync all</Btn>
        <Btn small kind="violet" onClick={async () => { const r = await api.mail.triage({}); toast(`Triaged ${r.triaged} (${r.llm_used} by LLM)`, "success"); loadMails(); }}>Triage now</Btn>
        <Btn small onClick={() => setShowAdd(!showAdd)}>{showAdd ? "Close" : "Add account"}</Btn>
      </div>
      {showAdd && (
        <Panel icon="plus" title="Add Mailbox" sub="Sandbox loads a sample inbox · live polls IMAP (read-only)">
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Field value={name} onChange={(e) => setName(e.target.value)} placeholder="Account name" />
            <Seg options={[{ v: "sandbox", label: "Sandbox" }, { v: "live", label: "Live IMAP" }]} value={mode} onPick={setMode} />
          </div>
          {mode === "live" && (
            <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
              <Field value={host} onChange={(e) => setHost(e.target.value)} placeholder="imap.host.com" />
              <Field value={port} onChange={(e) => setPort(e.target.value)} placeholder="993" />
              <Field value={user} onChange={(e) => setUser(e.target.value)} placeholder="username" />
              <Field type="password" value={pass} onChange={(e) => setPass(e.target.value)} placeholder="password / app password" />
            </div>
          )}
          <div style={{ marginTop: 8 }}><Btn small kind="green" onClick={async () => {
            try {
              const r = await api.mail.createAccount({ name: name || "Inbox", mode, host, port: Number(port) || 993, username: user, password: pass }) as { id: number };
              await api.mail.sync(r.id);
              setName(""); setHost(""); setUser(""); setPass(""); setShowAdd(false); racc(); loadMails();
              toast("Mailbox added & synced", "success");
            } catch (e) { toast(`Add failed: ${e instanceof Error ? e.message : e}`, "error"); }
          }}>Add & sync</Btn></div>
        </Panel>
      )}
      {accounts.length > 0 && (
        <div className="cards">
          {accounts.map((a) => (
            <div key={a.id} className="entitycard slim">
              <header><div><strong>{a.name}</strong><small>{a.mode === "live" ? `${a.username}@${a.host}` : "sample inbox"} · {a.unseen} unseen</small></div>
                <Pill c={a.mode === "live" ? "amber" : "green"}>{a.mode}</Pill></header>
              {a.last_error ? <small className="red">{a.last_error}</small> : null}
              <div style={{ display: "flex", gap: 6 }}>
                <Btn small onClick={async () => { const r = await api.mail.sync(a.id); toast(r.ok ? `${r.new} new` : r.error || "failed", r.ok ? "success" : "error"); racc(); loadMails(); }}>Sync</Btn>
                <Btn small onClick={() => send(`summarize unread email from ${a.name}`)}>Ask AURA</Btn>
                <Btn small onClick={async () => { if (confirm(`Delete ${a.name} and its mail?`)) { await api.mail.removeAccount(a.id); setSel(null); setFull(null); racc(); loadMails(); } }}><Icon n="trash" s={13} /></Btn>
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="grid2">
        <Panel icon="mail" title="Messages" sub={`${mails.length} shown`}
          right={<label style={{ display: "flex", gap: 6, alignItems: "center" }}><input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} /><small>unread only</small></label>}>
          <div className="tabs" style={{ marginBottom: 8 }}>{[["", "All"], ["action", "Action"], ["waiting", "Waiting"], ["fyi", "FYI"], ["done", "Done"]].map(([v, l]) => <button key={v} className={filter === v ? "on" : ""} onClick={() => setFilter(v)}>{l}</button>)}</div>
          {mails.map((m) => (
            <Row key={m.id} icon={m.seen ? "mail" : "spark"} title={`${m.seen ? "" : "● "}${m.subject || "(no subject)"}`}
              sub={`${m.sender} · ${(m.snippet || "").slice(0, 80)}`}
              right={<Pill c={triC(m.triage)}>{m.triage}</Pill>} onClick={() => openMail(m.id)} c={sel === m.id ? "sel" : ""} />
          ))}
          {mails.length === 0 && <Empty title="No messages" sub="Add a mailbox above — sandbox mode loads samples instantly." />}
        </Panel>
        <Panel icon="file" title={full ? full.subject : "Reader"} sub={full ? full.sender : "Select a message"}>
          {!full && <Empty title="Nothing selected" sub="Click a message to read it here." />}
          {full && (<>
            <small className="dim">To: {full.recipients} · {full.mail_date.slice(0, 16).replace("T", " ")}</small>
            <p style={{ whiteSpace: "pre-wrap", fontSize: 13 }}>{full.body || full.snippet}</p>
            {full.triage_reason && <small className="dim">Triage: {full.triage_reason}</small>}
            <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
              <Seg options={[{ v: "action", label: "Action" }, { v: "waiting", label: "Waiting" }, { v: "fyi", label: "FYI" }, { v: "done", label: "Done" }]}
                value={full.triage} onPick={async (v) => { await api.mail.set(full.id, { triage: v }); setFull({ ...full, triage: v }); loadMails(); }} />
              <Btn small onClick={() => send(`draft a reply to "${full.subject}" from ${full.sender}`)}>Draft reply</Btn>
              <Btn small onClick={async () => { await api.mail.set(full.id, { seen: !full.seen }); setFull({ ...full, seen: full.seen ? 0 : 1 }); loadMails(); }}>{full.seen ? "Mark unread" : "Mark read"}</Btn>
            </div>
          </>)}
        </Panel>
      </div>
      <ChatThread compact /><Composer />
    </div>
  );
}

/* ============================== CALENDAR ============================== */
export function CalendarView() {
  const { t } = useLang();
  const { toast, refresh } = useStore();
  const { data: weekData, reload: rweek } = useFetch(() => api.cal.week());
  const { data: calData, reload: rcal } = useFetch(() => api.cal.list());
  const [title, setTitle] = useState("");
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [time, setTime] = useState("09:00");
  const [dur, setDur] = useState("60");
  const [calId, setCalId] = useState(0);
  const [loc, setLoc] = useState("");
  const [showCal, setShowCal] = useState(false);
  const [cname, setCname] = useState("");
  const [csource, setCsource] = useState("local");
  const [curl, setCurl] = useState(""); const [cuser, setCuser] = useState(""); const [cpass, setCpass] = useState("");
  const [gcid, setGcid] = useState(""); const [gcsec, setGcsec] = useState("");
  const [gcode, setGcode] = useState(0); const [codeVal, setCodeVal] = useState("");
  const cals: Cal[] = calData?.calendars || [];
  useEffect(() => { if (!calId && cals.length) setCalId(cals[0].id); }, [calData]); // eslint-disable-line react-hooks/exhaustive-deps
  const events: CalEvent[] = weekData?.events || [];
  const byDay = new Map<string, CalEvent[]>();
  for (const e of events) {
    const k = nboDay(e.starts_at);
    if (!byDay.has(k)) byDay.set(k, []);
    byDay.get(k)!.push(e);
  }
  const addEvent = async () => {
    if (!title.trim()) return;
    try {
      const s = new Date(`${date}T${time}`);
      const e = new Date(s.getTime() + (Number(dur) || 60) * 60000);
      await api.cal.createEvent({ calendar_id: calId, title: title.trim(), starts_at: s.toISOString(), ends_at: e.toISOString(), location: loc });
      setTitle(""); setLoc(""); rweek(); refresh();
      toast("Event added", "success");
    } catch (e) { toast(`Add failed: ${e instanceof Error ? e.message : e}`, "error"); }
  };
  const connectGoogle = async (cal: Cal) => {
    try {
      const redirect = `${window.location.origin}/api/calendar/google/landing`;
      const r = await api.cal.googleAuthUrl(cal.id, redirect);
      window.open(r.url, "_blank");
      setGcode(cal.id);
      toast("Approve in the opened tab, then paste the code below", "info");
    } catch (e) { toast(`${e instanceof Error ? e.message : e}`, "error"); }
  };
  return (
    <div className="view">
      <div className="vhead"><h2><Icon n="cal" s={20} /> {t("title.calendar")}</h2>
        <Pill c="blue">{events.length} in next 7 days</Pill><span style={{ flex: 1 }} />
        <Btn small onClick={async () => { for (const c of cals) { try { await api.cal.sync(c.id); } catch { /* per-cal errors shown */ } } rweek(); rcal(); toast("Calendars synced", "success"); }}>Sync all</Btn>
        <Btn small onClick={() => setShowCal(!showCal)}>{showCal ? "Close" : "Calendars"}</Btn>
      </div>
      {showCal && (
        <Panel icon="plus" title="Calendars" sub="Local · CalDAV (iCloud/Fastmail/Nextcloud) · Google">
          <div className="cards">
            {cals.map((c) => (
              <div key={c.id} className="entitycard slim">
                <header><div><strong>{c.name}</strong><small>{c.source}{c.fields?.url ? ` · ${c.fields.url}` : ""}{c.fields?.username ? ` · ${c.fields.username}` : ""}</small></div>
                  <Pill c={c.source === "local" ? "green" : "violet"}>{c.source}</Pill></header>
                {c.last_error ? <small className="red">{c.last_error}</small> : null}
                {c.source === "google" && !c.secrets_set?.refresh_token && (
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 6 }}>
                    <Btn small kind="violet" onClick={() => connectGoogle(c)}>Connect Google</Btn>
                    {gcode === c.id && (<>
                      <Field value={codeVal} onChange={(e) => setCodeVal(e.target.value)} placeholder="paste code from Google tab" />
                      <Btn small kind="green" onClick={async () => {
                        try {
                          await api.cal.googleCallback({ calendar_id: c.id, code: codeVal.trim(), redirect_uri: `${window.location.origin}/api/calendar/google/landing` });
                          setCodeVal(""); setGcode(0); rcal(); toast("Google connected — syncing…", "success");
                          await api.cal.sync(c.id); rweek();
                        } catch (e) { toast(`Connect failed: ${e instanceof Error ? e.message : e}`, "error"); }
                      }}>Finish</Btn>
                    </>)}
                  </div>
                )}
                <div style={{ display: "flex", gap: 6 }}>
                  <Btn small onClick={async () => { try { const r = await api.cal.sync(c.id); toast(r.ok ? `${r.new || 0} new · ${r.updated || 0} updated` : r.error || "failed", r.ok ? "success" : "error"); } catch (e) { toast(`${e instanceof Error ? e.message : e}`, "error"); } rweek(); rcal(); }}>Sync</Btn>
                  {c.source !== "local" && <Btn small onClick={async () => { if (confirm(`Delete ${c.name} and its events?`)) { await api.cal.remove(c.id); rcal(); rweek(); } }}><Icon n="trash" s={13} /></Btn>}
                </div>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
            <Field value={cname} onChange={(e) => setCname(e.target.value)} placeholder="Calendar name" />
            <Seg options={[{ v: "local", label: "Local" }, { v: "caldav", label: "CalDAV" }, { v: "google", label: "Google" }]} value={csource} onPick={setCsource} />
          </div>
          {csource === "caldav" && (
            <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
              <Field value={curl} onChange={(e) => setCurl(e.target.value)} placeholder="https://caldav.host/remote.php/dav" />
              <Field value={cuser} onChange={(e) => setCuser(e.target.value)} placeholder="username" />
              <Field type="password" value={cpass} onChange={(e) => setCpass(e.target.value)} placeholder="password / app password" />
            </div>
          )}
          {csource === "google" && (
            <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
              <Field value={gcid} onChange={(e) => setGcid(e.target.value)} placeholder="Google OAuth client ID" />
              <Field type="password" value={gcsec} onChange={(e) => setGcsec(e.target.value)} placeholder="Client secret" />
              <small className="dim">Create an OAuth client (Desktop… any type works) — see docs/GOOGLE_CALENDAR_SETUP.md, then Connect above.</small>
            </div>
          )}
          <div style={{ marginTop: 8 }}><Btn small kind="green" onClick={async () => {
            try {
              const fields = csource === "caldav" ? { url: curl, username: cuser, password: cpass } : csource === "google" ? { client_id: gcid, client_secret: gcsec } : {};
              await api.cal.create({ name: cname || (csource === "local" ? "Personal" : csource), source: csource, fields });
              setCname(""); setCurl(""); setCuser(""); setCpass(""); setGcid(""); setGcsec(""); rcal();
              toast("Calendar added", "success");
            } catch (e) { toast(`Add failed: ${e instanceof Error ? e.message : e}`, "error"); }
          }}>Add calendar</Btn></div>
        </Panel>
      )}
      <Panel icon="plus" title="New Event" sub="Saved to the selected calendar (pushed upstream for CalDAV/Google)">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <Field value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Event title…" />
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
          <select aria-label="Event duration" value={dur} onChange={(e) => setDur(e.target.value)}>
            <option value="15">15m</option><option value="30">30m</option><option value="60">1h</option><option value="90">1.5h</option><option value="120">2h</option>
          </select>
          <select aria-label="Calendar" value={calId} onChange={(e) => setCalId(Number(e.target.value))}>
            {cals.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <Field value={loc} onChange={(e) => setLoc(e.target.value)} placeholder="Location (optional)" />
          <Btn small kind="violet" onClick={addEvent}>Add</Btn>
        </div>
        <small className="dim">Tip: or just chat — “schedule dentist friday 9am”.</small>
      </Panel>
      <div className="grid2">
        {[...byDay.entries()].map(([day, evs]) => (
          <Panel key={day} icon="cal" title={day} sub={`${evs.length} events`}>
            {evs.map((e) => (
              <Row key={e.id} icon="clock" title={`${nboTime(e.starts_at)} — ${e.title}`}
                sub={`${e.calendar_name || ""}${e.location ? ` · ${e.location}` : ""}${e.description ? ` · ${e.description.slice(0, 60)}` : ""}`}
                right={<button className="xbtn" onClick={async () => { if (confirm("Delete event?")) { await api.cal.deleteEvent(e.id); rweek(); } }}><Icon n="trash" s={13} /></button>} />
            ))}
          </Panel>
        ))}
      </div>
      {events.length === 0 && <Empty title="Clear week" sub="Add an event above or connect CalDAV/Google." />}
      <ChatThread compact /><Composer />
    </div>
  );
}

/* ============================== BRIEFINGS ============================== */
export function BriefingsPanel() {
  const { toast, refresh } = useStore();
  const { data, reload } = useFetch(() => api.brief.list());
  const { data: runsData, reload: rruns } = useFetch(() => api.brief.runs());
  const [name, setName] = useState("");
  const [kind, setKind] = useState("morning");
  const [prompt, setPrompt] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [running, setRunning] = useState(false);
  const briefs: Briefing[] = data?.briefings || [];
  const runs: BriefRun[] = runsData?.runs || [];
  const run = async (fn: () => Promise<{ output: string; model: string; ms: number }>) => {
    setRunning(true);
    try { await fn(); reload(); rruns(); refresh(); toast("Briefing ready", "success"); }
    catch (e) { toast(`Run failed: ${e instanceof Error ? e.message : e}`, "error"); }
    finally { setRunning(false); }
  };
  return (
    <Panel icon="spark" title="Briefings" sub="LLM digests on demand or on schedule" right={<Pill c="violet">{runs.length} runs</Pill>}>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <Btn small kind="violet" disabled={running} onClick={() => run(() => api.brief.runNow("morning"))}>☀️ Morning now</Btn>
        <Btn small disabled={running} onClick={() => run(() => api.brief.runNow("evening"))}>🌙 Evening now</Btn>
        <Btn small disabled={running} onClick={() => run(() => api.brief.runNow("weekly"))}>📅 Weekly now</Btn>
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
        <Field value={name} onChange={(e) => setName(e.target.value)} placeholder="Briefing name (for schedules)…" />
        <select aria-label="Briefing type" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="morning">morning</option><option value="evening">evening</option><option value="weekly">weekly</option><option value="custom">custom</option>
        </select>
        <Btn small kind="green" onClick={async () => {
          await api.brief.create({ name: name || `${kind} briefing`, kind, prompt });
          setName(""); setPrompt(""); reload(); toast("Briefing saved", "success");
        }}>Save</Btn>
      </div>
      <Field value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Extra instruction (optional) e.g. focus on ShopLite…" />
      {briefs.length > 0 && <small className="secttl2">Saved briefings</small>}
      {briefs.map((b) => (
        <Row key={b.id} icon="spark" title={b.name} sub={`${b.kind} · last ${b.last_run ? nboDay(b.last_run) : "never"}${b.last_model ? ` · ${b.last_model}` : ""}`}
          right={<span style={{ display: "inline-flex", gap: 6 }}>
            <Btn small kind="violet" disabled={running} onClick={() => run(() => api.brief.run(b.id))}>Run</Btn>
            <Btn small onClick={async () => { if (confirm("Delete briefing?")) { await api.brief.remove(b.id); reload(); } }}><Icon n="trash" s={13} /></Btn>
          </span>} />
      ))}
      {runs.length > 0 && <small className="secttl2">Recent runs</small>}
      {runs.slice(0, 5).map((r: BriefRun) => (
        <div key={r.id} className="entitycard slim">
          <header onClick={() => setOpen(open === r.id ? null : r.id)} style={{ cursor: "pointer" }}>
            <div><strong>{r.briefing_name || r.kind}</strong><small>{nboDay(r.created_at)} {nboTime(r.created_at)} · {r.model} · {r.ms}ms</small></div>
            <Pill c="blue">{r.kind}</Pill>
          </header>
          {open === r.id && <div className="md" dangerouslySetInnerHTML={{ __html: md(r.output) }} />}
        </div>
      ))}
      <small className="dim">To schedule: create an automation below with action <code>brief</code> — pick kind + saved briefing.</small>
    </Panel>
  );
}

/* ============================== SESSIONS ============================== */
export function SessionsView() {
  const { t } = useLang();
  const { toast, loadSession, newChat } = useStore();
  const [q, setQ] = useState("");
  const [sessions, setSessions] = useState<Session[]>([]);
  const load = async () => {
    try { const r = await api.sessions.list(q); setSessions(r.sessions); }
    catch { /* offline */ }
  };
  useEffect(() => { load(); }, [q]); // eslint-disable-line react-hooks/exhaustive-deps
  const act = async (fn: () => Promise<unknown>, msg: string) => {
    try { await fn(); await load(); toast(msg, "success"); }
    catch { toast("Action failed", "warn"); }
  };
  return (
    <div className="view">
      <div className="vhead"><h2><Icon n="chat" s={20} /> {t("title.sessions")}</h2>
        <Btn small kind="violet" onClick={() => newChat()}>New</Btn></div>
      <div className="toolbar"><input className="grow" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search conversations…" /></div>
      {sessions.length === 0 && <Empty title="No conversations" sub="Start chatting — sessions appear here." />}
      {sessions.map((s) => (
        <Row key={s.id} icon={s.pinned ? "pin" : "chat"} title={`${s.starred ? "★ " : ""}${s.title}`}
          sub={`${s.n} msgs · ${s.domain}${s.has_summary ? " · summarized" : ""}`}
          onClick={() => loadSession(s.id)}
          right={<>
            <button className="xbtn" title={s.pinned ? "Unpin" : "Pin"} onClick={(e) => { e.stopPropagation(); act(() => api.sessions.pin(s.id), s.pinned ? "Unpinned" : "Pinned"); }}><Icon n="pin" s={14} /></button>
            <button className="xbtn" title={s.starred ? "Unstar" : "Star"} onClick={(e) => { e.stopPropagation(); act(() => api.sessions.star(s.id), s.starred ? "Unstarred" : "Starred"); }}><Icon n="star" s={14} /></button>
            <button className="xbtn" title="Compact now" onClick={(e) => { e.stopPropagation(); api.sessions.compact(s.id).then((r) => { load(); toast(r.compacted ? `Compacted ${r.chunk || ""} msgs` : "Already compact", r.compacted ? "success" : "warn"); }).catch(() => toast("Action failed", "warn")); }}><Icon n="spark" s={14} /></button>
            <button className="xbtn" title="Branch" onClick={(e) => { e.stopPropagation(); act(() => api.sessions.branch(s.id), "Branched"); }}><Icon n="plus" s={14} /></button>
            <button className="xbtn" title="Rename" onClick={(e) => { e.stopPropagation(); const v = prompt("Rename conversation", s.title); if (v && v.trim()) act(() => api.sessions.update(s.id, { title: v.trim() }), "Renamed"); }}><Icon n="edit" s={14} /></button>
            <button className="xbtn" title="Delete" onClick={(e) => { e.stopPropagation(); if (confirm("Delete this conversation?")) act(() => api.sessions.remove(s.id), "Deleted"); }}><Icon n="trash" s={14} /></button>
          </>} />
      ))}
    </div>
  );
}

/* ============================== ANALYTICS ============================== */
function Bars({ rows, suffix = "" }: { rows: { label: string; value: number }[]; suffix?: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div>{rows.map((r, i) => (
      <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12, padding: "2px 0" }}>
        <span style={{ width: 58, flexShrink: 0, color: "var(--dim)" }}>{r.label}</span>
        <div style={{ flex: 1, background: "var(--bg2)", borderRadius: 4, height: 10 }}>
          <div style={{ width: `${Math.max(2, Math.round((r.value / max) * 100))}%`, height: "100%", borderRadius: 4, background: "var(--cyan)" }} />
        </div>
        <b style={{ minWidth: 56, textAlign: "right" }}>{r.value.toLocaleString()}{suffix}</b>
      </div>))}</div>
  );
}

export function AnalyticsView() {
  const { t } = useLang();
  const { data, reload } = useFetch(() => api.analytics.overview());
  if (!data) return (<div className="view"><div className="vhead"><h2><Icon n="chart" s={20} /> {t("title.analytics")}</h2></div><Skel /><Skel /></div>);
  const sp = data.spending, tk = data.tasks;
  const cur0 = sp.by_currency[0];
  const dayLbl = (iso: string) => (iso || "").slice(5);
  return (
    <div className="view">
      <div className="vhead"><h2><Icon n="chart" s={20} /> {t("title.analytics")}</h2>
        <Btn small onClick={() => reload()}>Refresh</Btn></div>
      <div className="grid2">
        <Panel icon="wallet" title="Spending" sub={cur0 ? `${cur0.currency} · this month` : "No expenses yet"}
          right={cur0?.delta_pct !== null && cur0?.delta_pct !== undefined
            ? <Pill c={cur0.delta_pct > 0 ? "red" : "green"}>{cur0.delta_pct > 0 ? "↑" : "↓"} {Math.abs(cur0.delta_pct)}% vs last mo</Pill> : undefined}>
          {sp.by_currency.length === 0 && <Empty title="No spending data" sub="Log expenses in Personal to light this up." />}
          {sp.by_currency.map((c) => (
            <div key={c.currency} style={{ marginBottom: 8 }}>
              <Row icon="wallet" title={`${c.currency} ${c.month.toLocaleString()}`} sub={`last month ${c.last_month.toLocaleString()}`} />
              <Bars rows={sp.by_day.filter((d) => d.currency === c.currency).map((d) => ({ label: dayLbl(d.day), value: d.total }))} />
              {sp.by_category.filter((x) => x.currency === c.currency).map((x) => (
                <div key={x.category} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "2px 0" }}>
                  <span style={{ color: "var(--dim)" }}>{x.category || "uncategorized"}</span>
                  <span>{x.total.toLocaleString()}</span>
                </div>))}
            </div>))}
        </Panel>
        <Panel icon="check" title="Tasks" sub={tk.completion_rate !== null ? `${Math.round(tk.completion_rate * 100)}% done · 30d` : "No tasks yet"}
          right={tk.overdue_now > 0 ? <Pill c="red">{tk.overdue_now} overdue</Pill> : <Pill c="green">clear</Pill>}>
          {tk.done_14d.length === 0 && tk.created_30 === 0 && <Empty title="No task activity" sub="Completed tasks show up here." />}
          {tk.done_14d.length > 0 && <Bars rows={tk.done_14d.map((d) => ({ label: dayLbl(d.day), value: d.n }))} />}
          <div style={{ display: "flex", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
            {Object.entries(tk.by_status).map(([s, n]) => <Pill key={s} c="blue">{s} · {n}</Pill>)}
          </div>
        </Panel>
        <Panel icon="heart" title="Habits & Sleep" sub={data.sleep.avg_7d !== null ? `avg ${data.sleep.avg_7d}h sleep · 7d` : "Habits + rest"}>
          {data.habits.length === 0 && <Empty title="No habits" sub="Add habits in Personal to track streaks." />}
          {data.habits.map((h) => (
            <Row key={h.name} icon={h.done_today ? "check" : "clock"} title={h.name}
              sub={h.done_today ? `🔥 ${h.streak}-day streak · done today` : `streak ${h.streak} · last ${h.last_done || "never"}`} />))}
          {data.sleep.nights.length > 0 && (
            <div style={{ marginTop: 8 }}><div style={{ fontSize: 12, color: "var(--dim)", marginBottom: 4 }}>Sleep hours</div>
              <Bars rows={data.sleep.nights.map((n) => ({ label: dayLbl(n.date), value: n.hours }))} suffix="h" /></div>)}
        </Panel>
        <Panel icon="spark" title="Mood & Activity" sub={data.mood.avg_14d !== null ? `avg mood ${data.mood.avg_14d}/10 · 14d` : "Mind + momentum"}>
          {data.mood.points.length === 0 && <Empty title="No mood data" sub="Journal with a mood score (e.g. 8/10)." />}
          {data.mood.points.length > 0 && <Bars rows={data.mood.points.map((p) => ({ label: dayLbl(p.day), value: p.score }))} suffix="/10" />}
          {data.activity.runs_14d.length > 0 && (
            <div style={{ marginTop: 8 }}><div style={{ fontSize: 12, color: "var(--dim)", marginBottom: 4 }}>AURA runs / day</div>
              <Bars rows={data.activity.runs_14d.map((r) => ({ label: dayLbl(r.day), value: r.n }))} /></div>)}
        </Panel>
        <Panel icon="chart" title="Forecast" sub={data.forecast ? "Honest projections — blank until there's enough history" : ""}>
          {(() => {
            const f = data.forecast;
            const rows: { k: string; v: string; s: string }[] = [];
            if (!f) return <Empty title="Not enough history" sub="Log expenses, tasks, sleep, and mood — forecasts appear once there are 3+ data points." />;
            if (f.spending_next_7d) rows.push({ k: `Next 7d spend`, v: `${f.spending_next_7d.currency} ${Math.round(f.spending_next_7d.amount).toLocaleString()}`, s: f.spending_next_7d.basis });
            if (f.tasks_next_7d !== null) rows.push({ k: "Tasks next 7d", v: `≈ ${f.tasks_next_7d}`, s: `${f.task_velocity_per_day} completed/day` });
            if (f.sleep_trend !== null) rows.push({ k: "Sleep trend", v: `${f.sleep_trend > 0 ? "↑" : f.sleep_trend < 0 ? "↓" : "→"} ${Math.abs(f.sleep_trend).toFixed(2)}h/night`, s: "last 7 nights" });
            if (f.mood_trend !== null) rows.push({ k: "Mood trend", v: `${f.mood_trend > 0 ? "↑" : f.mood_trend < 0 ? "↓" : "→"} ${Math.abs(f.mood_trend).toFixed(2)}/day`, s: "last 14 days" });
            if (rows.length === 0) return <Empty title="Not enough history" sub="Log expenses, tasks, sleep, and mood — forecasts appear once there are 3+ data points." />;
            return rows.map((r) => <Row key={r.k} icon="chart" title={r.k} sub={r.s || ""} right={<strong>{r.v}</strong>} />);
          })()}
        </Panel>
      </div>
    </div>
  );
}
