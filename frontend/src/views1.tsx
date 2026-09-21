/* AURA OS workspaces I — Career & Work, Clients & Projects, Personal Life. */
import { useEffect, useState } from "react";
import { ago, api, Client, Project, Task } from "./api";
import { useStore } from "./store";
import { useLang } from "./i18n";
import { Btn, ChatThread, Composer, Dot, Empty, fmtDate, Icon, Panel, Pill, Progress, Row, Skel } from "./ui";

export const Field = (p: React.InputHTMLAttributes<HTMLInputElement> & { label?: string }) => (
  <label className="field">{p.label && <small>{p.label}</small>}<input {...p} /></label>
);
export const useFetch = <T,>(fn: () => Promise<T>, deps: unknown[] = []) => {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const load = () => { setLoading(true); fn().then(setData).catch(() => undefined).finally(() => setLoading(false)); };
  useEffect(load, deps); // eslint-disable-line react-hooks/exhaustive-deps
  return { data, loading, reload: load };
};

/* ============================== CAREER ============================== */
export function CareerView() {
  const { t } = useLang();
  const { data, loading, reload } = useFetch(() => api.career.overview());
  const { toast, refresh, send } = useStore();
  const [tab, setTab] = useState("dash");
  const [resume, setResume] = useState("");
  const [jd, setJd] = useState("");
  const [analysis, setAnalysis] = useState<{ ats_score: number; recommendations: string[]; word_count: number } | null>(null);
  const [qs, setQs] = useState<string[]>([]);
  const [company, setCompany] = useState(""); const [role, setRole] = useState("");
  const [blkTitle, setBlkTitle] = useState("");
  if (loading && !data) return (<div className="view"><div className="vhead"><h2><Icon n="brief" s={20} /> {t("title.career")}</h2></div><Skel /><Skel /></div>);
  const plan = async () => { await api.career.planBlocks(); toast("Focus blocks generated from your tasks", "success"); reload(); refresh(); };
  return (
    <div className="view">
      <div className="vhead"><h2><Icon n="brief" s={20} /> {t("title.career")}</h2>
        <div className="tabs">{[["dash", "Dashboard"], ["resume", "Resume"], ["interview", "Interviews"], ["time", "Time Blocking"], ["apps", "Applications"]].map(([v, l]) => <button key={v} className={tab === v ? "on" : ""} onClick={() => setTab(v)}>{l}</button>)}</div>
      </div>
      {tab === "dash" && (
        <div className="grid2">
          <Panel icon="target" title="Today's Priorities" sub="AI-ranked career tasks">
            {(data?.tasks || []).map((t) => <TaskRow key={t.id} t={t} onDone={reload} />)}
            {(data?.tasks || []).length === 0 && <Empty title="No career tasks" sub="AURA can plan your next move." action={<Btn small kind="violet" onClick={() => send("plan my day")}>Plan my day</Btn>} />}
          </Panel>
          <Panel icon="chart" title="Applications Pipeline" sub={`${(data?.applications || []).length} applications`}>
            <div className="stages">{["saved", "applied", "screen", "interview", "offer"].map((s) => (
              <div key={s} className="stage"><strong>{data?.pipeline[s] || 0}</strong><small>{s}</small></div>
            ))}</div>
            <small className="secttl">Today's blocks</small>
            {(data?.today_blocks || []).map((b) => <Row key={b.id} icon="clock" title={b.title} sub={`${b.starts_at.slice(11, 16)} – ${b.ends_at.slice(11, 16)}`} />)}
            {(data?.today_blocks || []).length === 0 && <Empty title="No blocks today" sub="Generate focus blocks from tasks." action={<Btn small kind="green" onClick={plan}>AI Plan Day</Btn>} />}
          </Panel>
        </div>
      )}
      {tab === "resume" && (
        <div className="grid2">
          <Panel icon="file" title="Resume Workspace" sub="ATS analysis & tailoring">
            <textarea className="ta" rows={8} value={resume} onChange={(e) => setResume(e.target.value)} placeholder="Paste your resume text here…" />
            <textarea className="ta" rows={4} value={jd} onChange={(e) => setJd(e.target.value)} placeholder="Paste the job description (optional, for keyword matching)…" />
            <div style={{ display: "flex", gap: 8 }}>
              <Btn kind="violet" onClick={async () => { if (resume.length < 50) { toast("Paste your resume first", "warn"); return; } const r = await api.career.analyze({ text: resume, job_description: jd }); setAnalysis(r); toast(`ATS score: ${r.ats_score}/100`, "success"); }}>Analyze Resume</Btn>
              <Btn onClick={() => send("optimize my resume for a senior developer role")}>Ask AURA to Rewrite</Btn>
            </div>
            {analysis && <div className="analysis"><div className="score"><strong>{analysis.ats_score}</strong><small>/100 ATS</small></div>
              <ul>{analysis.recommendations.map((r, i) => <li key={i}>{r}</li>)}</ul></div>}
          </Panel>
          <Panel icon="folder" title="Versions" sub="Every analysis is versioned">
            {(data?.resumes || []).map((r) => <Row key={r.id} icon="file" title={`${r.name} · v${r.version}`} sub={`${ago(r.created_at)}`} right={<span style={{ display: "flex", gap: 6, alignItems: "center" }}><Pill c={r.ats_score >= 75 ? "green" : "amber"}>{r.ats_score}</Pill><a className="btn sm" href={`/api/career/resumes/${r.id}/download`}>Export</a></span>} />)}
            {(data?.resumes || []).length === 0 && <Empty title="No resumes yet" sub="Paste your resume to create v1." />}
          </Panel>
        </div>
      )}
      {tab === "interview" && (
        <div className="grid2">
          <Panel icon="chat" title="Mock Interview" sub="AI question bank + scoring">
            <div style={{ display: "flex", gap: 8 }}>
              <Field label="Role" value={role} onChange={(e) => setRole(e.target.value)} placeholder="Senior Developer" />
              <Field label="Company" value={company} onChange={(e) => setCompany(e.target.value)} placeholder="Safaricom" />
            </div>
            <Btn kind="violet" onClick={async () => { const r = await api.career.questions(role || "Software Engineer"); setQs(r.questions); }}>Generate Questions</Btn>
            {qs.map((x, i) => <div key={i} className="q"><strong>Q{i + 1}.</strong> {x}</div>)}
            {qs.length > 0 && <Btn small onClick={async () => { await api.career.addInterview({ company: company || "Practice", role: role || "Software Engineer", feedback: "Mock session" }); toast("Session logged", "success"); reload(); }}>Log Practice Session</Btn>}
          </Panel>
          <Panel icon="chart" title="History & Scores" sub="Improvement tracking">
            {(data?.interviews || []).map((iv) => <Row key={iv.id} icon="mic" title={`${iv.role} @ ${iv.company}`} sub={iv.feedback || "session"} right={iv.score != null ? <Pill c="green">{iv.score}</Pill> : undefined} />)}
            {(data?.interviews || []).length === 0 && <Empty title="No sessions yet" sub="Run your first mock interview." />}
          </Panel>
        </div>
      )}
      {tab === "time" && (
        <Panel icon="cal" title="Time Blocking" sub="Protect deep work">
          <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
            <Field value={blkTitle} onChange={(e) => setBlkTitle(e.target.value)} placeholder="Block title…" />
            <Btn kind="green" onClick={plan}>AI Plan Day</Btn>
            <Btn onClick={async () => { if (!blkTitle) return; const d = new Date().toISOString().slice(0, 10); await api.career.addBlock({ title: blkTitle, starts_at: `${d}T11:00:00`, ends_at: `${d}T12:00:00` }); setBlkTitle(""); reload(); }}>Add 11:00 Block</Btn>
          </div>
          {(data?.today_blocks || []).map((b) => (
            <Row key={b.id} icon="clock" title={b.title} sub={`${b.starts_at.slice(11, 16)} – ${b.ends_at.slice(11, 16)} · ${b.kind}`}
              right={<button className="xbtn" onClick={async () => { await api.career.delBlock(b.id); reload(); }}><Icon n="trash" s={14} /></button>} />
          ))}
        </Panel>
      )}
      {tab === "apps" && (
        <Panel icon="brief" title="Applications" sub="Track every opportunity">
          <AddApp onAdd={reload} />
          {(data?.applications || []).map((a) => (
            <Row key={a.id} icon="brief" title={`${a.role} @ ${a.company}`} sub={a.notes}
              right={<select value={a.stage} onChange={async (e) => { await api.career.updateApp(a.id, { stage: e.target.value }); reload(); }}>
                {["saved", "applied", "screen", "interview", "offer", "rejected"].map((s) => <option key={s} value={s}>{s}</option>)}
              </select>} />
          ))}
        </Panel>
      )}
      <ChatThread compact /><Composer />
    </div>
  );
}

function AddApp({ onAdd }: { onAdd: () => void }) {
  const [c, setC] = useState(""); const [r, setR] = useState("");
  return (
    <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
      <Field value={c} onChange={(e) => setC(e.target.value)} placeholder="Company" />
      <Field value={r} onChange={(e) => setR(e.target.value)} placeholder="Role" />
      <Btn small kind="violet" onClick={async () => { if (!c || !r) return; await api.career.addApp({ company: c, role: r }); setC(""); setR(""); onAdd(); }}>Track</Btn>
    </div>
  );
}

export function TaskRow({ t, onDone }: { t: Task; onDone?: () => void }) {
  const { refresh } = useStore();
  const cycle = async () => {
    const next = t.status === "completed" ? "in_progress" : "completed";
    await api.tasks.update(t.id, { status: next });
    onDone?.(); refresh();
  };
  return (
    <div className={`taskrow ${t.status}`} onClick={cycle} title="Click to toggle complete">
      <span className={`checkbox ${t.status === "completed" ? "on" : ""}`}>{t.status === "completed" && <Icon n="check" s={13} />}</span>
      <span className="rtitles"><strong>{t.title}</strong><small>{t.client_name || t.project_name || t.domain}{t.due_at ? ` · due ${fmtDate(t.due_at)}` : ""}</small></span>
      <Pill c={t.priority === "urgent" ? "red" : t.priority === "high" ? "amber" : "blue"}>{t.priority}</Pill>
    </div>
  );
}

/* ============================== CLIENTS ============================== */
export function ClientsView() {
  const { t } = useLang();
  const { data: cdata, loading: cload, reload: rc } = useFetch(() => api.clients.list());
  const { data: pdata, reload: rp } = useFetch(() => api.projects.list());
  const { data: bdata, reload: rb } = useFetch(() => api.backup.history());
  const { toast, refresh, send } = useStore();
  const [tab, setTab] = useState("projects");
  const [name, setName] = useState(""); const [cname, setCname] = useState("");
  if (cload && !cdata) return (<div className="view"><div className="vhead"><h2><Icon n="users" s={20} /> {t("title.clients")}</h2></div><Skel /><Skel /></div>);
  const reload = () => { rc(); rp(); refresh(); };
  return (
    <div className="view">
      <div className="vhead"><h2><Icon n="users" s={20} /> {t("title.clients")}</h2>
        <div className="tabs">{[["projects", "Project Tracker"], ["clients", "Client Directory"], ["backup", "Backup Manager"]].map(([v, l]) => <button key={v} className={tab === v ? "on" : ""} onClick={() => setTab(v)}>{l}</button>)}</div>
      </div>
      <div className="actionstrip">
        <Btn small kind="violet" onClick={() => send("review my client workload")}>AI Workload Review</Btn>
        <Btn small onClick={() => send("draft follow-up messages for overdue tasks")}>Draft Follow-ups</Btn>
        <Btn small onClick={async () => { const r = await api.backup.run(); toast(r.ok ? `Backup saved: ${r.file}` : `Backup failed`, r.ok ? "success" : "error"); rb(); }}>Backup Now</Btn>
      </div>
      {tab === "projects" && (
        <div className="grid2">
          <Panel icon="chart" title="Projects" sub={`${(pdata?.projects || []).length} total`}>
            <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
              <Field value={name} onChange={(e) => setName(e.target.value)} placeholder="New project name…" />
              <Btn small kind="green" onClick={async () => { if (!name.trim()) return; await api.projects.create({ name: name.trim() }); setName(""); reload(); toast("Project created", "success"); }}>Create</Btn>
            </div>
            {(pdata?.projects || []).map((p) => <ProjectCard key={p.id} p={p} onDone={reload} />)}
          </Panel>
          <Panel icon="users" title="At-risk & Reviews" sub="Needs attention">
            {(pdata?.projects || []).filter((p) => p.health !== "on_track" || p.status === "review").map((p) => (
              <Row key={p.id} icon="alert" title={p.name} sub={`${p.status} · ${p.progress}%`} right={<Pill c="amber">{p.health.replace("_", " ")}</Pill>} />
            ))}
            <small className="secttl">All projects</small>
            {(pdata?.projects || []).map((p) => <Row key={p.id} icon="brief" title={p.name} sub={`${p.client_name || "no client"} · ${fmtDate(p.deadline)}`} right={<Pill c={p.status === "completed" ? "green" : "blue"}>{p.progress}%</Pill>} />)}
          </Panel>
        </div>
      )}
      {tab === "clients" && (
        <Panel icon="users" title="Client Directory" sub="Relationships & health">
          <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
            <Field value={cname} onChange={(e) => setCname(e.target.value)} placeholder="New client name…" />
            <Btn small kind="green" onClick={async () => { if (!cname.trim()) return; await api.clients.create({ name: cname.trim() }); setCname(""); reload(); toast("Client added", "success"); }}>Add Client</Btn>
          </div>
          <div className="cards">
            {(cdata?.clients || []).map((c) => (
              <div key={c.id} className="entitycard">
                <header><span className="aface">{c.name[0]}</span><div><strong>{c.name}</strong><small>{c.org || c.email || "—"}</small></div>
                  <Dot c={c.health === "good" ? "green" : c.health === "watch" ? "amber" : "red"} /></header>
                <div className="estat"><span>{c.open_projects || 0} open projects</span><span>{c.open_tasks || 0} open tasks</span></div>
                {c.notes && <p>{c.notes}</p>}
                <div style={{ display: "flex", gap: 6 }}>
                  <Btn small onClick={() => send(`prepare a meeting brief for ${c.name}`)}>Meeting Prep</Btn>
                  <Btn small onClick={async () => { if (confirm(`Delete ${c.name}?`)) { await api.clients.remove(c.id); reload(); } }}><Icon n="trash" s={13} /></Btn>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      )}
      {tab === "backup" && (
        <Panel icon="db" title="Backup Manager" sub="Snapshots with integrity hashes">
          <Btn kind="green" onClick={async () => { const r = await api.backup.run(); toast(r.ok ? "Backup completed" : "Backup failed", r.ok ? "success" : "error"); rb(); }}>Run Backup Now</Btn>
          {(bdata?.files || []).map((f) => (
            <Row key={f.name} icon="db" title={f.name} sub={`${ago(f.created_at)} · ${(f.size_bytes / 1024).toFixed(0)} KB`}
              right={<Btn small onClick={async () => { if (!confirm(`Restore ${f.name}? Your current data is snapshotted first, then replaced.`)) return; const r = await api.backup.restore(f.name); if (r.ok) { toast("Backup restored — reloading", "success"); setTimeout(() => location.reload(), 900); } else toast(`Restore failed: ${r.error || "unknown error"}`, "error"); }}>Restore</Btn>} />
          ))}
          {(bdata?.files || []).length === 0 && (bdata?.backups || []).length === 0 && <Empty title="No backups yet" sub="Run your first backup to protect AURA data." />}
          {(bdata?.backups || []).length > 0 && <small className="secttl">Run log</small>}
          {(bdata?.backups || []).slice(0, 5).map((b) => (
            <Row key={b.id} icon="db" title={b.target + " · " + (b.size_bytes / 1024).toFixed(0) + " KB"} sub={`${ago(b.created_at)} · ${b.note}`}
              right={<Pill c={b.status === "ok" ? "green" : b.status === "running" ? "amber" : "red"}>{b.status}</Pill>} />
          ))}
        </Panel>
      )}
      <ChatThread compact /><Composer />
    </div>
  );
}

function ProjectCard({ p, onDone }: { p: Project; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [ms, setMs] = useState("");
  return (
    <div className="entitycard">
      <header onClick={() => setOpen(!open)} style={{ cursor: "pointer" }}>
        <div><strong>{p.name}</strong><small>{p.client_name || "No client"} · {p.status} · due {fmtDate(p.deadline)}</small></div>
        <Pill c={p.health === "on_track" ? "green" : "amber"}>{p.progress}%</Pill>
      </header>
      <Progress v={p.progress} c={p.health === "on_track" ? "" : "amber"} />
      {open && (
        <div className="pdetail">
          <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <input type="range" min={0} max={100} value={p.progress} onChange={async (e) => { await api.projects.update(p.id, { progress: parseInt(e.target.value, 10) }); onDone(); }} />
            <select value={p.status} onChange={async (e) => { await api.projects.update(p.id, { status: e.target.value }); onDone(); }}>
              {["active", "paused", "review", "completed", "cancelled"].map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <small className="secttl">Milestones</small>
          {(p.milestones || []).map((m) => <Row key={m.id} icon={m.status === "done" ? "check" : "target"} title={m.title} sub={fmtDate(m.due_at)} />)}
          <div style={{ display: "flex", gap: 6 }}>
            <Field value={ms} onChange={(e) => setMs(e.target.value)} placeholder="New milestone…" />
            <Btn small onClick={async () => { if (!ms.trim()) return; await api.projects.milestone(p.id, { title: ms.trim() }); setMs(""); onDone(); }}>Add</Btn>
          </div>
        </div>
      )}
    </div>
  );
}

/* ============================== PERSONAL ============================== */
export function PersonalView() {
  const { t } = useLang();
  const { data, loading, reload } = useFetch(() => api.personal.overview());
  const { toast, send } = useStore();
  const [tab, setTab] = useState("dash");
  const [journal, setJournal] = useState(""); const [mood, setMood] = useState("");
  const [amt, setAmt] = useState(""); const [cat, setCat] = useState("food");
  const [goal, setGoal] = useState("");
  const [sleepH, setSleepH] = useState("");
  if (loading && !data) return (<div className="view"><div className="vhead"><h2><Icon n="heart" s={20} /> {t("title.personal")}</h2></div><Skel /><Skel /></div>);
  return (
    <div className="view">
      <div className="vhead"><h2><Icon n="heart" s={20} /> {t("title.personal")}</h2>
        <div className="tabs">{[["dash", "Dashboard"], ["journal", "Journal"], ["finance", "Finance"], ["goals", "Goals & Habits"]].map(([v, l]) => <button key={v} className={tab === v ? "on" : ""} onClick={() => setTab(v)}>{l}</button>)}</div>
      </div>
      <div className="actionstrip">
        <Btn small kind="violet" onClick={() => send("log mood 8 feeling great")}>Log Mood</Btn>
        <Btn small onClick={() => send("how is my spending this month?")}>Spending Review</Btn>
        <Btn small onClick={() => { setTab("journal"); }}>New Journal Entry</Btn>
      </div>
      {(tab === "dash" || tab === "journal") && (
        <div className="grid2">
          <Panel icon="book" title="Journal & Reflection" sub="Private to your Personal domain">
            <div style={{ display: "flex", gap: 8 }}>
              <Field value={mood} onChange={(e) => setMood(e.target.value)} placeholder="Mood (e.g. grateful, 8/10)" />
              <Btn small kind="violet" onClick={async () => { if (!mood) return; await api.personal.mood({ mood, note: "quick check-in" }); setMood(""); reload(); toast("Mood logged", "success"); }}>Log</Btn>
            </div>
            <textarea className="ta" rows={4} value={journal} onChange={(e) => setJournal(e.target.value)} placeholder="Reflect on your day…" />
            <Btn small kind="green" onClick={async () => { if (!journal.trim()) return; await api.personal.journal({ body: journal.trim(), mood }); setJournal(""); reload(); toast("Journaled", "success"); }}>Save Entry</Btn>
            {(data?.journal || []).slice(0, 4).map((j) => <Row key={j.id} icon="book" title={(j.body || "").slice(0, 60)} sub={`${ago(j.created_at)}${j.mood ? ` · mood: ${j.mood}` : ""}`} />)}
          </Panel>
          <Panel icon="zap" title="Habits" sub="Streaks compound">
            {(data?.habits || []).map((h) => (
              <Row key={h.id} icon="zap" title={h.name} sub={`🔥 ${h.streak} day streak`} right={<Btn small onClick={async () => { await api.personal.habitDone(h.id); reload(); }}>Done today</Btn>} />
            ))}
            <small className="secttl">Spending: KES {(data?.spending_total || 0).toLocaleString()}</small>
            {(data?.expenses || []).slice(0, 4).map((e) => <Row key={e.id} icon="wallet" title={`${e.category} · KES ${Number(e.amount).toLocaleString()}`} sub={e.note} />)}
          </Panel>
          <Panel icon="moon" title="Sleep" sub="Log nights, spot patterns">
            <div style={{ display: "flex", gap: 8 }}>
              <Field value={sleepH} onChange={(e) => setSleepH(e.target.value)} placeholder="7.5 or 23:00-06:30" />
              <Btn small kind="violet" onClick={async () => {
                const v = sleepH.trim(); if (!v) return;
                const m = v.match(/(\d{1,2}:\d{2})\s*(?:-|to)\s*(\d{1,2}:\d{2})/);
                const body = m ? { bedtime: m[1], wake_at: m[2] } : { hours: parseFloat(v) };
                if (!m && !(body.hours > 0)) { toast("Enter hours or a time range", "warn"); return; }
                try { await api.personal.sleep(body); setSleepH(""); reload(); toast("Sleep logged", "success"); }
                catch (e) { toast(`Log failed: ${e instanceof Error ? e.message : e}`, "error"); }
              }}>Log</Btn>
            </div>
            {(data?.sleep || []).slice(0, 5).map((x) => <Row key={x.id} icon="moon" title={`${x.hours}h · ${x.date}`} sub={`${x.bedtime && x.wake_at ? `${x.bedtime} → ${x.wake_at}` : "duration only"}${x.quality ? ` · ${x.quality}` : ""}`} />)}
            {(data?.sleep || []).length === 0 && <Empty title="No sleep logs" sub="Log your first night above, or chat: slept 11pm to 6am" />}
          </Panel>
        </div>
      )}
      {tab === "finance" && (
        <Panel icon="wallet" title="Finance" sub={`Total tracked: KES ${(data?.spending_total || 0).toLocaleString()}`}>
          <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
            <Field value={amt} onChange={(e) => setAmt(e.target.value)} placeholder="Amount" />
            <select value={cat} onChange={(e) => setCat(e.target.value)}>{["food", "transport", "rent", "airtime", "health", "shopping", "travel", "other"].map((c) => <option key={c} value={c}>{c}</option>)}</select>
            <Btn small kind="green" onClick={async () => { if (!amt) return; await api.personal.expense({ category: cat, amount: parseFloat(amt), currency: "KES" }); setAmt(""); reload(); toast("Expense added", "success"); }}>Add Expense</Btn>
          </div>
          {(data?.expenses || []).map((e) => <Row key={e.id} icon="wallet" title={`${e.category} · KES ${Number(e.amount).toLocaleString()}`} sub={`${e.note} · ${ago(e.created_at)}`} />)}
        </Panel>
      )}
      {tab === "goals" && (
        <Panel icon="target" title="Goals" sub="Aim, track, achieve">
          <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
            <Field value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="New goal…" />
            <Btn small kind="violet" onClick={async () => { if (!goal.trim()) return; await api.personal.goal({ title: goal.trim() }); setGoal(""); reload(); }}>Set Goal</Btn>
          </div>
          {(data?.goals || []).map((g) => (
            <div key={g.id} className="entitycard">
              <header><div><strong>{g.title}</strong><small>{g.target || g.domain}</small></div><Pill c="violet">{g.progress}%</Pill></header>
              <input type="range" min={0} max={100} value={g.progress} onChange={async (e) => { await api.personal.goalUpdate(g.id, { progress: parseInt(e.target.value, 10) }); reload(); }} />
            </div>
          ))}
        </Panel>
      )}
      <ChatThread compact /><Composer />
    </div>
  );
}
