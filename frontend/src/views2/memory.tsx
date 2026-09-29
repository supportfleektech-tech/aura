import { useEffect, useState } from "react";
import { ago, api, Memory } from "../api";
import { useStore } from "../store";
import { useLang } from "../i18n";
import { Field } from "../views1";
import { Btn, ChatThread, Composer, Empty, Icon, Panel, Pill, Row } from "../ui";

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
