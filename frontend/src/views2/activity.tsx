import { useState } from "react";
import { ago, api } from "../api";
import { useLang } from "../i18n";
import { useFetch } from "../views1";
import { ApprovalCard, Dot, Empty, Icon, Panel, Pill } from "../ui";

export function ActivityView() {
  const { t } = useLang();
  const [kind, setKind] = useState("");
  const { data, reload } = useFetch(() => api.activity(kind ? `?kind=${kind}` : ""), [kind]);
  const { data: ap, reload: rap } = useFetch(() => api.approvals.list());
  const sev = (s: string) => (s === "success" ? "green" : s === "warn" ? "amber" : s === "error" ? "red" : "blue");
  return (
    <div className="view">
      <div className="vhead"><h2><Icon n="clock" s={20} /> {t("title.activity")}</h2>
        <select aria-label="Filter activity by type" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">all types</option>{["message", "run", "tool", "memory", "task", "project", "client", "integration", "automation", "approval", "backup", "system"].map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
      </div>
      {(ap?.approvals?.length || 0) > 0 && (
        <Panel icon="shield" title={`Pending Approvals (${ap!.approvals.length})`} sub="R2/R3 actions wait for you">
          {ap!.approvals.map((a) => <ApprovalCard key={a.id} approval={{ id: a.id, risk: a.risk, title: a.title, drafts: a.detail.drafts || [] }} onDone={() => { rap(); reload(); }} />)}
        </Panel>
      )}
      <Panel icon="clock" title="Unified Feed" sub="Messages \u00b7 runs \u00b7 tools \u00b7 memory \u00b7 entities \u00b7 system">
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
