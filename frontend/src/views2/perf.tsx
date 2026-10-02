/* Job-queue observability (spec §5, FR-WRK-003/004).
 *
 * Reads only what `workers.stats()` and `workers.dead_letters()` actually
 * return. Two honest-empties are load-bearing here rather than cosmetic:
 *
 * - Nothing in production calls `workers.enqueue`, so every counter is 0 on a
 *   fresh install and `drain()` is a no-op. The panel says so rather than
 *   dressing a permanent zero as "the queue is healthy".
 * - `error_rate` is `dead / (done + dead)`; with nothing settled it is 0.0 by
 *   construction, so a green 0.0% pill means "no failures", not "proven".
 */
import { useState } from "react";
import { api, DeadLetter } from "../api";
import { useStore } from "../store";
import { useFetch } from "../views1";
import { Btn, Empty, Icon, Panel, Pill, Row } from "../ui";

export function PerfView() {
  const { toast } = useStore();
  const { data, reload } = useFetch(() => api.workers.status());
  const { data: dl, reload: reloadDl } = useFetch(() => api.workers.dead());
  const { data: con, reload: reloadCon } = useFetch(() => api.consolidation.status());
  const [busy, setBusy] = useState(false);

  const s = data?.stats;
  const dead: DeadLetter[] = dl?.dead || [];
  const kinds = Object.entries(s?.by_kind || {});
  // Zero *and* nothing ever ran: a queue that has only ever been empty is a
  // different fact from a queue that has drained cleanly.
  const idle = !s || (s.queued === 0 && s.running === 0 && s.done === 0 && s.dead === 0 && kinds.length === 0);

  const drain = async () => {
    setBusy(true);
    try {
      const r = await api.workers.drain();
      reload(); reloadDl();
      toast(`Ran ${r.ran} job(s): ${r.done} done, ${r.retried} retrying, ${r.dead} dead`, r.dead ? "warn" : "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  const consolidate = async () => {
    setBusy(true);
    try {
      const r = await api.consolidation.run();
      reloadCon();
      toast(`Consolidation: ${r.merged} merged, ${r.archived} archived, ${r.rescored} re-scored in ${r.duration_ms}ms`, "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="view">
      <div className="vhead">
        <h2><Icon n="cpu" s={20} /> Performance</h2>
        <Pill c="violet">Pool {data?.pool_size ?? "—"}</Pill>
      </div>
      <Panel icon="zap" title="Job queue" sub="Worker pool health — FR-WRK-004">
        <Row icon="clock" title="Queued" right={<Pill c="blue">{s?.queued ?? "—"}</Pill>} />
        <Row icon="play" title="Running" right={<Pill c="violet">{s?.running ?? "—"}</Pill>} />
        <Row icon="check" title="Done" right={<Pill c="green">{s?.done ?? "—"}</Pill>} />
        <Row icon="alert" title="Dead" right={<Pill c={s?.dead ? "red" : "green"}>{s?.dead ?? "—"}</Pill>} />
        <Row icon="wave" title="Throughput / min" right={<Pill c="blue">{s?.throughput_per_min ?? "—"}</Pill>} />
        <Row icon="target" title="Error rate" right={<Pill c={s?.error_rate ? "amber" : "green"}>{((s?.error_rate ?? 0) * 100).toFixed(1)}%</Pill>} />
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <Btn small kind="violet" onClick={drain} disabled={busy}>Drain queue</Btn>
          <Btn small onClick={() => { reload(); reloadDl(); reloadCon(); }}>Refresh</Btn>
        </div>
      </Panel>
      {idle && (
        <Panel icon="alert" title="Nothing has ever been queued" sub="Read this before trusting the zeros">
          <small className="dim">
            Every counter above is zero because no job has ever been enqueued. Today the only
            periodic work (mission ticks, schedule ticks) runs inline on the scheduler thread,
            so it never enters this queue — the pool exists and is drained, but nothing submits to it.
            The numbers will stay at zero until a producer calls <code>workers.enqueue</code>.
          </small>
        </Panel>
      )}
      <Panel icon="alert" title="Dead letters" sub="Jobs that exhausted their retries — FR-WRK-003">
        {dead.map((j) => (
          <Row key={j.id} icon="x" title={`#${j.id} ${j.kind}`}
            sub={`${j.attempts}/${j.max_retries} attempts — ${j.last_error}`} />
        ))}
        {dead.length === 0 && <Empty title="No dead letters" sub="Every job settled." />}
      </Panel>
      <Panel icon="db" title="By kind" sub="Where the work comes from">
        {kinds.map(([k, c]) => (
          <Row key={k} icon="folder" title={k} right={<Pill c="blue">{c}</Pill>} />
        ))}
        {kinds.length === 0 && <Empty title="No jobs yet" sub="Nothing has ever been enqueued." />}
      </Panel>
      <Panel icon="db" title="Memory consolidation" sub="Dedupe, re-score and archive your memories">
        <Row icon="check" title="Enabled" right={<Pill c={con?.enabled ? "green" : "amber"}>{String(con?.enabled ?? "—")}</Pill>} />
        <Row icon="clock" title="Due now" right={<Pill c={con?.due ? "amber" : "green"}>{String(con?.due ?? "—")}</Pill>} />
        <Row icon="cal" title="Last pass" sub={String(con?.last_run?.created_at ?? "never")} />
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          <Btn small kind="violet" onClick={consolidate} disabled={busy}>Run now</Btn>
          <Btn small onClick={reloadCon}><Icon n="refresh" s={14} /> Refresh</Btn>
        </div>
      </Panel>
    </div>
  );
}