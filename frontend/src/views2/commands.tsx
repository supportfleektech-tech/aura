/* Slash command cheat sheet + custom-command CRUD (spec §3, FR-CMD-004/005). */
import { useState } from "react";
import { api, SlashCommandT } from "../api";
import { useStore, VIEWS } from "../store";
import { Field, useFetch } from "../views1";
import { Btn, Empty, Icon, Panel, Pill, Row } from "../ui";

export function CommandsView() {
  const { toast } = useStore();
  const { data, reload } = useFetch(() => api.slash.catalog());
  const [q, setQ] = useState("");
  const [name, setName] = useState("/");
  const [prompt, setPrompt] = useState("");
  const [target, setTarget] = useState("");

  const cmds: SlashCommandT[] = data?.commands || [];
  const needle = q.trim().toLowerCase();
  const shown = cmds.filter((c) => !needle
    || c.name.toLowerCase().includes(needle)
    || c.summary.toLowerCase().includes(needle)
    || c.category.toLowerCase().includes(needle));

  const byCat = new Map<string, SlashCommandT[]>();
  for (const c of shown) byCat.set(c.category, [...(byCat.get(c.category) || []), c]);

  const save = async () => {
    try {
      await api.slash.saveCustom(name.trim(), prompt.trim(), target.trim());
      setPrompt(""); setTarget("");
      reload();
      toast("Custom command saved", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  const remove = async (c: SlashCommandT) => {
    try {
      await api.slash.deleteCustom(c.name);
      reload();
      toast(`${c.name} deleted`, "warn");
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), "error");
    }
  };

  return (
    <div className="view">
      <div className="vhead">
        <h2><Icon n="zap" s={20} /> Commands</h2>
        <Pill c="violet">{cmds.length} commands</Pill>
      </div>
      <div className="actionstrip">
        <input className="grow" aria-label="Search commands" value={q}
          onChange={(e) => setQ(e.target.value)} placeholder="Search commands…" />
      </div>
      {[...byCat.entries()].map(([cat, list]) => (
        <Panel key={cat} icon="zap" title={cat} sub={`${list.length} command${list.length === 1 ? "" : "s"}`}>
          {list.map((c) => (
            <Row key={c.name} icon="chev" title={<code>{c.name}</code>} sub={`${c.summary} — e.g. ${c.example}`}
              right={c.category === "Custom"
                ? <Btn small onClick={() => { void remove(c); }}>Delete</Btn>
                : <Pill c="blue">{c.arg || "no arg"}</Pill>} />
          ))}
        </Panel>
      ))}
      {shown.length === 0 && <Empty title="No command matches" sub="Try a different search." />}
      <Panel icon="plus" title="Add a custom command" sub="Map a slash name to a prompt">
        <Field aria-label="Command name" value={name} onChange={(e) => setName(e.target.value)} placeholder="/brief" />
        <textarea className="ta" rows={3} aria-label="Command prompt" value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder="What should /brief ask AURA to do?" />
        <Field aria-label="Jump to view" value={target} onChange={(e) => setTarget(e.target.value)}
          list="slash-view-targets" placeholder="Optional: jump to a view" />
        {/* Free text is validated against the real union server-side (400), but
            offering the valid names keeps a typo from being possible at all.
            The list is `store.VIEWS`, the same source the `View` type derives
            from, so it cannot go stale. */}
        <datalist id="slash-view-targets">{VIEWS.map((v) => <option key={v} value={v} />)}</datalist>
        <div style={{ display: "flex", gap: 8 }}>
          <Btn small kind="green" onClick={save}>Save command</Btn>
        </div>
        <small className="dim">
          Custom names must start with /, contain no spaces, and cannot shadow a built-in.
          A jump target must be one of: {VIEWS.join(", ")}.
        </small>
      </Panel>
    </div>
  );
}
