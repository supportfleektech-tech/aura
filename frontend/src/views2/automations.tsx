import { useState } from "react";
import { ago, api, Mission } from "../api";
import { useStore } from "../store";
import { useLang } from "../i18n";
import { useFetch } from "../views1";
import { BriefingsPanel } from "../views3";
import { Btn, Empty, Icon, Panel, Pill, Row } from "../ui";
import { Field } from "../views1";

function BriefKindPick({ action, kind, setKind, bid, setBid }: { action: string; kind: string; setKind: (v: string) => void; bid: string; setBid: (v: string) => void }) {
  const { data } = useFetch(() => api.brief.list());
  if (action !== "brief") return null;
  return (<>
    <select aria-label="Briefing type" value={kind} onChange={(e) => setKind(e.target.value)}>
      <option value="morning">morning</option><option value="evening">evening</option><option value="weekly">weekly</option><option value="custom">custom</option>
    </select>
    <select aria-label="Saved briefing" value={bid} onChange={(e) => setBid(e.target.value)}>
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
      <header><div><strong>{m.goal}</strong><small>{done}/{m.steps.length} steps \u00b7 {ago(m.created_at)}{m.needs_review ? " \u00b7 needs review" : ""}</small></div>
        <Pill c={pill}>{m.status}</Pill></header>
      <small className="dim">Review tools and arguments before Start. R0/R1 steps run without further approval; R2/R3 and draft sends pause. Starting is not approval to send.</small>
      {m.steps.map((s, i) => {
        const risk = riskFor(s);
        const approval = s.status === "awaiting" ? approvals.find((a) => a.id === s.approval_id && a.status === "pending") : undefined;
        return <div key={i}>
          <Row icon={s.status === "done" ? "check" : s.status === "failed" ? "x" : s.status === "awaiting" ? "clock" : s.status === "skipped" ? "minus" : i === m.step_idx && m.status === "running" ? "play" : "circle"}
            title={`${i + 1}. ${s.label}`} sub={[s.tool || s.kind, s.status, s.note].filter(Boolean).join(" \u00b7 ")} />
          <small>{risk ? `${risk} \u00b7 ${MISSION_RISKS[risk] || "Risk unavailable"}` : "Risk unavailable \u2014 reload the tool catalog before starting."}</small>
          {s.kind === "send_drafts" ? <p>Drafts from step {(s.drafts_from ?? 0) + 1}. Exact recipients and messages are available for review when this step pauses, before sending.</p> : <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(s.args || {}, null, 2)}</pre>}
          {approval && <div><strong>Approval #{approval.id} \u00b7 {approval.risk} \u00b7 {approval.title}</strong><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{JSON.stringify(approval.detail, null, 2)}</pre></div>}
        </div>;
      })}
      {m.status === "awaiting" && <><small className="amber">Waiting on you \u2014 resolve the approval in Activity \u2192 Approvals. No pending action is auto-approved.</small><Btn small onClick={() => setView("activity")}>Review approvals</Btn></>}
      {m.status === "done" && m.result && <small className="dim">{m.result.slice(0, 200)}</small>}
      {m.status === "failed" && m.result && <small className="red">{m.result.slice(0, 200)}</small>}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        <small className="dim">repeat</small>
        <select value={every} onChange={(e) => void sched(e.target.value)} aria-label="repeat schedule">
          {["off", "hourly", "daily", "weekly"].map((o) => <option key={o} value={o}>{o}</option>)}
        </select>
        {m.next_run_at ? <small className="dim">next {m.next_run_at.slice(0, 16).replace("T", " ")}</small> : null}
        {lastRun ? <small className="dim">{`last run: ${lastRun.status}${lastRun.summary ? ` \u00b7 ${lastRun.summary.slice(0, 60)}` : ""}`}</small> : null}
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
      <Panel icon="plus" title="New Automation" sub="Trigger \u2192 action with history & retry">
        <div style={{ display: "flex", gap: 8 }}>
          <Field value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Evening shutdown review" />
          <select value={every} onChange={(e) => setEvery(e.target.value)}><option value="hourly">hourly</option><option value="daily">daily</option><option value="weekly">weekly</option></select>
          <select value={action} onChange={(e) => setAction(e.target.value)}><option value="notify">notify</option><option value="backup">backup</option><option value="chat">log</option><option value="brief">LLM brief</option><option value="proactive">proactive scan</option><option value="webhook">webhook</option></select>
          <BriefKindPick action={action} kind={briefKind} setKind={setBriefKind} bid={briefId} setBid={setBriefId} />
          <Btn small kind="violet" onClick={async () => { if (!name.trim()) return; if (action === "webhook" && !whUrl.trim()) { toast("Webhook needs a URL", "warn"); return; } try { const act = action === "webhook" ? { url: whUrl.trim(), secret: whSecret.trim() } : action === "brief" ? { kind: briefKind, ...(briefId ? { briefing_id: Number(briefId) } : {}) } : {}; await api.automations.create({ name: name.trim(), trigger_kind: "schedule", trigger: { every }, action_kind: action, action: act, next_run: new Date(Date.now() + 864e5).toISOString() }); setName(""); setWhUrl(""); setWhSecret(""); reload(); toast("Automation created", "success"); } catch (e) { toast(`Create failed: ${e instanceof Error ? e.message : e}`, "error"); } }}>{t("c.create")}</Btn>
        </div>
        {action === "webhook" && <div style={{ display: "flex", gap: 8, marginTop: 8 }}><Field value={whUrl} onChange={(e) => setWhUrl(e.target.value)} placeholder="https://... (signed POST on fire)" /><Field value={whSecret} onChange={(e) => setWhSecret(e.target.value)} placeholder="Signing secret (optional)" /></div>}
      </Panel>
      <Panel icon="zap" title="Automations" sub="Status \u00b7 next run \u00b7 success rate">
        {(data?.automations || []).map((a) => {
          const total = a.success_count + a.fail_count;
          return (
            <div key={a.id} className="entitycard">
              <header><div><strong>{a.name}</strong><small>{a.trigger_kind} \u00b7 {a.action_kind} \u00b7 next {a.next_run ? ago(a.next_run) : "\u2014"} \u00b7 last {a.last_run ? ago(a.last_run) : "never"}</small></div>
                <Pill c={a.status === "active" ? "green" : "amber"}>{a.status}</Pill></header>
              <small className="dim">{a.success_count} ok \u00b7 {a.fail_count} failed{total > 0 ? ` \u00b7 ${Math.round((a.success_count / total) * 100)}% success` : ""}</small>
              <div style={{ display: "flex", gap: 6 }}>
                <Btn small onClick={async () => { await api.automations.run(a.id); reload(); toast("Automation fired", "success"); }}><Icon n="play" s={13} /> {t("c.runnow")}</Btn>
                <Btn small onClick={async () => { try { const r = await api.automations.dryRun(a.id); toast(`Dry run ${r.fired?.ok ? "would fire" : "would fail"}${(r.blocked || []).length ? ` \u2014 ${(r.blocked || [])[0]}` : ""}`, r.fired?.ok ? "success" : "warn"); } catch { toast("Dry run failed", "warn"); } }}>Dry</Btn>
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
