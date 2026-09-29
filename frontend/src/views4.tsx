/* AURA OS workspaces IV — the v1.14 machine room: Model Room (Ollama sync),
 * Terminal (run commands on the fortress + ssh peers), Feeds (RSS watcher),
 * and the hands-free Voice Call overlay. */
import { useEffect, useRef, useState } from "react";
import { ago, api, chatStream, Feed, FeedItem, MachineCheck, MachineInfo, OllamaModel, SavedScript, TermRunRow, WatchState } from "./api";
import { useStore } from "./store";
import { TKey, useLang } from "./i18n";
import { Field, useFetch } from "./views1";
import { Btn, Dot, Empty, Icon, Panel, Pill, Row, Skel } from "./ui";
import { getServer, setServerCache } from "./prefs";

/* ============================== MODEL ROOM ============================== */
export function ModelsView() {
  const { toast } = useStore();
  const { t } = useLang();
  const { data: st, reload } = useFetch(() => api.ollama.status());
  const { data: cat, reload: rcat } = useFetch(() => api.ollama.models());
  const { data: cloud, reload: rcloud } = useFetch(() => api.cloud.models());
  const [busy, setBusy] = useState(false);
  const [free, setFree] = useState(false);

  async function sync() {
    setBusy(true);
    try {
      const r = await api.ollama.sync();
      toast(`Synced ${r.models} model(s) from ${r.base_url}`, "success");
      reload(); rcat();
    } catch (e) { toast(`Sync failed: ${e instanceof Error ? e.message : e}`, "error"); }
    setBusy(false);
  }
  function use(name: string, role: "chat" | "vision" | "embed") {
    api.ollama.setDefault(role, name)
      .then(() => { toast(`${name} is now the ${role} model`, "success"); setServerCache({ [`ollama_${role}_model`]: name }); reload(); })
      .catch((e) => toast(`${e instanceof Error ? e.message : e}`, "error"));
  }

  const models: OllamaModel[] = cat?.models || [];
  return (
    <div className="view">
      <div className="vhead">
        <h2><Icon n="cpu" s={20} /> {t("nav.models")}</h2>
        {st && <Pill c={st.reachable ? "green" : st.model_count ? "amber" : "red"}>
          <Dot c={st.reachable ? "green" : st.model_count ? "amber" : "red"} />
          {st.reachable ? "ollama online" : st.model_count ? "cached catalog (stale)" : "ollama offline"}
        </Pill>}
        <Btn small kind="violet" onClick={sync} disabled={busy}>{busy ? "Syncing…" : "Sync models"}</Btn>
      </div>
      <div className="grid2">
        <Panel icon="db" title="Ollama inventory" sub={st ? `${st.base_url} · synced ${st.synced_at ? ago(st.synced_at) : "never"}` : "loading…"}>
          {!cat && <Skel />}
          {cat && !cat.reachable && !models.length && (
            <Empty icon="alert" title="No Ollama reachable"
              sub={`Start Ollama on this machine (or point AURA at it in Settings → AI Engine). Base: ${cat.base_url}`} />)}
          {cat && cat.reachable && !models.length && <Empty icon="db" title="Ollama online, no models yet" sub="Run `ollama pull llama3.1`, then hit Sync models." />}
          {models.map((m) => {
            const isChat = st?.chat_model === m.name, isVis = st?.vision_model === m.name, isEmb = st?.embed_model === m.name;
            return (
              <div className="mcard" key={m.name} data-testid={`mcard-${m.name}`}>
                <div className="mrow">
                  <strong>{m.name}</strong>
                  {m.capabilities.map((c) => <Pill key={c} c={c === "vision" ? "violet" : c === "embed" ? "green" : "blue"}>{c}</Pill>)}
                </div>
                <small className="dim">{m.size} · {m.parameter_size} {m.quantization}{m.note ? ` · ${m.note}` : ""}</small>
                <div className="macts">
                  <Btn small kind={isChat ? "green" : ""} onClick={() => use(m.name, "chat")}>{isChat ? "✓ chat" : "use for chat"}</Btn>
                  {m.capabilities.includes("vision") && <Btn small kind={isVis ? "green" : ""} onClick={() => use(m.name, "vision")}>{isVis ? "✓ vision" : "use for vision"}</Btn>}
                  {m.capabilities.includes("embed") && <Btn small kind={isEmb ? "green" : ""} onClick={() => use(m.name, "embed")}>{isEmb ? "✓ embed" : "use for embeddings"}</Btn>}
                </div>
              </div>
            );
          })}
          {st && !st.reachable && models.length > 0 && <p className="dim">Showing the last synced catalog — Ollama isn't answering right now.</p>}
        </Panel>
        <Panel icon="cloud" title="Cloud catalog (OpenRouter)" sub={cloud?.cached ? "cached 1h" : "live fetch"}
          right={<Btn small onClick={() => { setFree(!free); rcloud(); }}>{free ? "show all" : "free only"}</Btn>}>
          {!cloud && <Skel />}
          {cloud && (cloud.error || cloud.note) && <p className="dim">{cloud.error || cloud.note}</p>}
          <FeedModelList models={cloud?.models || []} onlyFree={free} current={String(getServer("openrouter_model", ""))}
            onPick={(id) => api.settings.update({ openrouter_model: id })
              .then((r) => { setServerCache(r.values); toast(`${id} selected`, "success"); })
              .catch((e) => toast(`${e instanceof Error ? e.message : e}`, "error"))} />
        </Panel>
      </div>
      <Panel icon="shield" title="What sync does" sub="the honest fine print">
        <Row icon="db" title="Inventory, not install" sub="AURA reads Ollama's local model list (/api/tags). Nothing is downloaded — pull models with `ollama pull …` (try it from the Terminal)." />
        <Row icon="refresh" title="Background auto-sync" sub={`Interval from Settings · ${st?.auto_sync ? "on" : "off"} · keeps the catalog warm even when Ollama sleeps.`} />
        <Row icon="eye" title="Capabilities are inferred" sub="vision/embed/tool hints come from the model family — AURA probes before trusting a model." />
      </Panel>
    </div>
  );
}

function FeedModelList({ models, onlyFree, current, onPick }: {
  models: { id: string; name: string; context_length: number; free: boolean; reasoning?: boolean; vision?: boolean; multimodal?: boolean }[];
  onlyFree: boolean; current: string; onPick: (id: string) => void;
}) {
  const rows = models.filter((m) => !onlyFree || m.free).slice(0, 60);
  if (!rows.length) return <Empty title="No models listed" sub="Offline? AURA keeps curated presets in Settings → AI Engine." />;
  return (
    <div className="modellist">
      {rows.map((m) => (
        <button key={m.id} className={`modelrow ${m.id === current ? "on" : ""}`} onClick={() => onPick(m.id)}
          title={`${m.context_length} ctx · click to make this the cloud model`}>
          <span style={{ display: "flex", alignItems: "center", gap: 4, flex: 1, minWidth: 0 }}>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.name}</span>
            {m.reasoning && <span className="modelbadge violet">think</span>}
            {m.vision && <span className="modelbadge blue">vision</span>}
            {m.multimodal && <span className="modelbadge green">multi</span>}
          </span>
          <span className="dim" style={{ whiteSpace: "nowrap" }}>{m.free ? "free" : "paid"} · {(m.context_length / 1000).toFixed(0)}k</span>
        </button>
      ))}
    </div>
  );
}

/* ================================ TERMINAL =============================== */
const QUICK = ["ollama list", "git status", "df -h", "uptime"];

export function TerminalView() {
  const { toast } = useStore();
  const { t } = useLang();
  const { data: cfg } = useFetch(() => api.terminal.config());
  const { data: mh, reload: rmh } = useFetch(() => api.terminal.machines());
  const { data: hist, reload: rhist } = useFetch(() => api.terminal.history(40));
  const [cmd, setCmd] = useState("");
  const [machine, setMachine] = useState("local");
  const [out, setOut] = useState<{ text: string; exit: number | null; ms: number; denied?: boolean; trunc?: boolean; risk?: string } | null>(null);
  const [running, setRunning] = useState(false);
  const [cwd, setCwd] = useState("");
  const [newName, setNewName] = useState("");
  const [newHost, setNewHost] = useState("");
  const [checks, setChecks] = useState<Record<string, MachineCheck | "…">>({});
  const termRef = useRef<HTMLDivElement>(null);
  const histRef = useRef<string[]>([]);
  const histIdxRef = useRef(-1);

  useEffect(() => { if (termRef.current) termRef.current.scrollTop = termRef.current.scrollHeight; }, [out, hist]);
  useEffect(() => { if (cfg?.cwd) setCwd(cfg.cwd); }, [cfg]);
  useEffect(() => { if (hist?.runs?.length && !histRef.current.length) histRef.current = hist.runs.map((r) => r.command); }, [hist]);

  function recall(up: boolean) {
    const list = histRef.current;
    if (!list.length) return;
    const i = up ? Math.min(list.length - 1, histIdxRef.current + 1) : Math.max(-1, histIdxRef.current - 1);
    histIdxRef.current = i;
    setCmd(i < 0 ? "" : list[i]);
  }

  function run(c?: string) {
    const command = (c ?? cmd).trim();
    if (!command || running) return Promise.resolve();
    histRef.current = [command, ...histRef.current.filter((x) => x !== command)].slice(0, 100);
    histIdxRef.current = -1;
    setRunning(true);
    return api.terminal.exec(command, machine)
      .then((r) => {
        setOut({ text: r.output || (r as { error?: string }).error || "(no output)", exit: r.exit_code ?? null,
                 ms: r.duration_ms, denied: r.denied, trunc: r.truncated, risk: r.risk });
        if (r.denied) toast("Command refused by safety policy", "warn");
        rhist();
        if (!c) setCmd("");
      })
      .catch((e) => toast(`${e instanceof Error ? e.message : e}`, "error"))
      .finally(() => setRunning(false));
  }

  function addMachine() {
    const rows = (mh?.machines || []).filter((m) => m.kind === "ssh").map((m) => ({ name: m.name, host: m.host }));
    api.terminal.saveMachines([...rows, { name: newName.trim(), host: newHost.trim() }])
      .then(() => { toast(`Machine “${newName}” saved — your ssh key must already log into it`, "success"); setNewName(""); setNewHost(""); rmh(); })
      .catch((e) => toast(`${e instanceof Error ? e.message : e}`, "error"));
  }
  function removeMachine(name: string) {
    const rows = (mh?.machines || []).filter((m) => m.kind === "ssh" && m.name !== name).map((m) => ({ name: m.name, host: m.host }));
    api.terminal.saveMachines(rows).then(() => { toast(`Removed ${name}`, "info"); rmh(); })
      .catch((e) => toast(`${e instanceof Error ? e.message : e}`, "error"));
  }

  if (cfg && !cfg.enabled) return (
    <div className="view"><div className="vhead"><h2><Icon n="term" s={20} /> {t("nav.terminal")}</h2></div>
      <Panel icon="shield" title="Terminal is off" sub="safety first">
        <Empty icon="term" title="Disabled in settings"
          sub="Turn it on under Settings → Terminal (or the toggle below). Commands run as your user on the machine AURA lives on — every one of them is audited." />
      </Panel></div>);

  return (
    <div className="view">
      <div className="vhead">
        <h2><Icon n="term" s={20} /> {t("nav.terminal")}</h2>
        <select value={machine} onChange={(e) => setMachine(e.target.value)} aria-label="machine" style={{ minWidth: 130 }}>
          {(mh?.machines || [{ name: "local", host: "local", kind: "local" }]).map((m) => (
            <option key={m.name} value={m.name}>{m.kind === "ssh" ? `${m.name} · ${m.host}` : `this machine (${m.name})`}</option>
          ))}
        </select>
        <Pill c="blue">{machine === "local" ? "local shell" : `ssh → ${machine}`}</Pill>
      </div>
      <Panel icon="term" title="Run a command" sub={cfg ? `cwd ${cfg.cwd} · timeout ${cfg.timeout_s}s · output cap ${cfg.max_out_kb}KB · dangerous ${cfg.allow_dangerous ? "allowed (you toggled it)" : "refused"}` : "…"}>
        <div className="termline">
          <span className="termprompt">{machine === "local" ? "aura:~$" : `${machine}:~$`}</span>
          <input className="terminput" value={cmd} aria-label="terminal command" data-testid="term-input"
            onChange={(e) => setCmd(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void run();
              else if (e.key === "ArrowUp") { e.preventDefault(); recall(true); }
              else if (e.key === "ArrowDown") { e.preventDefault(); recall(false); }
            }} placeholder="git status — Enter to run, ↑ for history" />
          <Btn kind="violet" small onClick={() => void run()} disabled={running || !cmd.trim()}>{running ? "Running…" : "Run"}</Btn>
        </div>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 8 }}>
          {QUICK.map((q) => <button key={q} className="chip" onClick={() => void run(q)}>{q}</button>)}
        </div>
        <div className="termout" ref={termRef} data-testid="term-out">
          {out ? (
            <>
              <div className={`termmeta ${out.denied ? "bad" : out.exit === 0 ? "ok" : "warn"}`} data-testid="term-meta">
                {out.denied ? "🛑 refused by safety policy" : `exit ${out.exit} · ${out.ms} ms · risk: ${out.risk}`}{out.trunc ? " · output truncated" : ""}
              </div>
              <pre>{out.text}</pre>
            </>
          ) : <span className="dim">Output lands here. Dangerous patterns (rm -rf /, mkfs, curl|sh…) are refused unless you explicitly allow them.</span>}
        </div>
      </Panel>
      <div className="grid2">
        <Panel icon="folder" title="Working directory" sub="where commands run">
          <div style={{ display: "flex", gap: 8 }}>
            <Field value={cwd} onChange={(e) => setCwd(e.target.value)} placeholder="~/projects" />
            <Btn small onClick={() => api.terminal.setCwd(cwd)
              .then((r) => { toast(`cwd → ${r.cwd}`, "success"); })
              .catch((e) => toast(`${e instanceof Error ? e.message : e}`, "error"))}>Save</Btn>
          </div>
          <p className="dim" style={{ marginTop: 6 }}>Home by default. This is your machine — guarded by the deny-list, logged in full.</p>
        </Panel>
        <Panel icon="link" title="Other machines" sub={mh && !mh.ssh_available ? "⚠ ssh binary missing on the AURA host" : "ssh with key auth · BatchMode (never prompts for passwords)"}>
          {(mh?.machines || []).filter((m: MachineInfo) => m.kind === "ssh").map((m) => {
            const chk = checks[m.name];
            return (
              <Row key={m.name} icon="link" title={m.name}
                sub={`${m.host} · ${chk === "…" ? "checking…" : chk ? (chk.ok ? `alive · ${chk.ms}ms` : `down · ${chk.detail}`) : "unchecked"}`}
                right={<span style={{ display: "inline-flex", gap: 6 }}>
                  <Btn small onClick={() => { setChecks({ ...checks, [m.name]: "…" }); api.machineCheck(m.name).then((r) => setChecks((c) => ({ ...c, [m.name]: r }))).catch(() => setChecks((c) => ({ ...c, [m.name]: { machine: m.name, ok: false, detail: "check failed" } }))); }}>Check</Btn>
                  <Btn small onClick={() => removeMachine(m.name)}>×</Btn>
                </span>} />
            );
          })}
          <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
            <input className="inp" placeholder="name (buildbox)" value={newName} aria-label="machine name" onChange={(e) => setNewName(e.target.value)} style={{ flex: 1 }} />
            <input className="inp" placeholder="user@host or ip" value={newHost} aria-label="machine host" onChange={(e) => setNewHost(e.target.value)} style={{ flex: 1.4 }} />
            <Btn small onClick={addMachine} disabled={!newName.trim() || !newHost.trim()}>Add</Btn>
          </div>
        </Panel>
      </div>
      <ScriptsPanel />
      <Panel icon="clock" title="Execution log" sub="every run, audited" right={<Btn small onClick={() => rhist()}>Refresh</Btn>}>
        {(!hist || !hist.runs.length) && <Empty icon="clock" title="Nothing run yet" sub="Commands appear here with exit codes — the audit trail is the trust contract." />}
        {hist?.runs.map((r: TermRunRow) => (
          <div key={r.id} className="runrow">
            <span className={`statdot ${r.status === "ok" ? "ok" : r.status === "denied" ? "bad" : "warn"}`} />
            <code title={r.cwd}>{r.command.length > 68 ? r.command.slice(0, 68) + "…" : r.command}</code>
            <span className="dim">{r.machine === "local" ? "" : `@${r.machine} · `}{r.source}{r.exit_code !== null ? ` · exit ${r.exit_code}` : ""} · {r.duration_ms}ms · {ago(r.created_at)}</span>
          </div>
        ))}
      </Panel>
    </div>
  );
}

/* ----------------------------- script library ---------------------------- */
export function ScriptsPanel() {
  const { toast } = useStore();
  const { data, reload } = useFetch(() => api.scripts.list());
  const { data: mh } = useFetch(() => api.terminal.machines());
  const [name, setName] = useState(""); const [command, setCommand] = useState("");
  const [desc, setDesc] = useState(""); const [machine, setMachine] = useState("local");
  const [busy, setBusy] = useState<number | null>(null);
  const [lastOut, setLastOut] = useState<Record<number, string>>({});
  const scripts: SavedScript[] = data?.scripts || [];

  function save() {
    api.scripts.save({ name: name.trim(), command: command.trim(), machine, description: desc.trim() })
      .then(() => { toast(`Script “${name}” saved`, "success"); setName(""); setCommand(""); setDesc(""); reload(); })
      .catch((e) => toast(`${e instanceof Error ? e.message : e}`, "error"));
  }
  function run(s: SavedScript) {
    setBusy(s.id);
    api.scripts.run(s.id)
      .then((r) => {
        setLastOut((m) => ({ ...m, [s.id]: r.denied ? "🛑 refused — " + (r.error || "") : `exit ${r.exit_code} · ${(r.output || "").slice(0, 300)}` }));
        toast(r.ok ? `${s.name} ran clean` : `${s.name} → exit ${r.exit_code}`, r.ok ? "success" : "warn");
        reload();
      })
      .catch((e) => toast(`${e instanceof Error ? e.message : e}`, "error"))
      .finally(() => setBusy(null));
  }

  return (
    <Panel icon="play" title="Saved scripts" sub="your recurring commands — danger-checked at save AND run, fully audited"
      right={<Btn small onClick={() => reload()}>Refresh</Btn>}>
      {scripts.map((s) => (
        <div key={s.id} className="scriptrow" data-testid={`script-${s.name}`}>
          <div className="scriptinfo">
            <strong>{s.name}</strong>
            <code title={s.description || s.command}>{s.command.slice(0, 74)}{s.command.length > 74 ? "…" : ""}</code>
            <small className="dim">{s.machine !== "local" ? `@${s.machine} · ` : ""}ran {s.run_count}×{s.last_run ? ` · last ${s.last_status} ${ago(s.last_run)}` : ""}</small>
            {lastOut[s.id] && <pre className="scriptout">{lastOut[s.id]}</pre>}
          </div>
          <span className="scriptacts">
            <Btn small kind="violet" onClick={() => run(s)} disabled={busy === s.id}>{busy === s.id ? "…" : "Run"}</Btn>
            <Btn small onClick={() => api.scripts.remove(s.id).then(reload).catch(() => undefined)}>×</Btn>
          </span>
        </div>
      ))}
      {!scripts.length && <Empty icon="play" title="No saved scripts" sub='Save your rituals here — or tell AURA: “save a script called health-check that runs uptime”.' />}
      <div className="scriptnew">
        <input className="inp" placeholder="name (deploy-staging)" aria-label="script name" value={name} onChange={(e) => setName(e.target.value)} />
        <input className="inp" style={{ flex: 2 }} placeholder="command — supports {placeholders} filled at run time" aria-label="script command" value={command} onChange={(e) => setCommand(e.target.value)} />
        <input className="inp" placeholder="description (optional)" aria-label="script description" value={desc} onChange={(e) => setDesc(e.target.value)} />
        <select value={machine} onChange={(e) => setMachine(e.target.value)} aria-label="script machine">
          {(mh?.machines || [{ name: "local", host: "local", kind: "local" }]).map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
        </select>
        <Btn small onClick={save} disabled={!name.trim() || !command.trim()}>Save</Btn>
      </div>
      <p className="dim" style={{ marginTop: 6 }}>Automations can fire these too (action kind <code>script</code>) — and the danger gate applies at save, at every run, and for unattended rules.</p>
    </Panel>
  );
}

/* ================================= FEEDS ================================= */
const SUGGEST = [
  { name: "Hacker News frontpage", url: "https://hnrss.org/frontpage" },
  { name: "Lobsters", url: "https://lobste.rs/rss" },
  { name: "BBC World", url: "https://feeds.bbci.co.uk/news/world/rss.xml" },
];

export function FeedsView() {
  const { toast } = useStore();
  const { t } = useLang();
  const { data, reload } = useFetch(() => api.feeds.list());
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);

  function add(u: string) {
    if (!u.trim()) return;
    setBusy(true);
    api.feeds.add(u.trim())
      .then(() => { toast("Feed followed — first items pulled", "success"); setUrl(""); reload(); })
      .catch((e) => toast(`${e instanceof Error ? e.message : e}`, "error"))
      .finally(() => setBusy(false));
  }
  function refreshAll() {
    setBusy(true);
    api.feeds.refresh()
      .then((r) => { toast(`Refreshed ${r.feeds} feed(s) · ${r.new_items} new${r.errors ? ` · ${r.errors} error(s)` : ""}`, r.errors ? "warn" : "success"); reload(); })
      .catch((e) => toast(`${e instanceof Error ? e.message : e}`, "error"))
      .finally(() => setBusy(false));
  }

  const feeds: Feed[] = data?.feeds || [];
  const items: FeedItem[] = data?.items || [];
  const unread = items.filter((i) => !i.read).length;
  return (
    <div className="view">
      <div className="vhead">
        <h2><Icon n="rss" s={20} /> {t("nav.feeds")}</h2>
        {data && <Pill c={unread ? "violet" : "blue"}>{unread ? `${unread} unread` : "all caught up"}</Pill>}
        <Btn small kind="violet" disabled={busy} onClick={refreshAll}>{busy ? "Refreshing…" : "Refresh all"}</Btn>
      </div>
      <div className="grid2">
        <Panel icon="plus" title="Follow a feed" sub="RSS 2.0 or Atom · zero credentials">
          <div style={{ display: "flex", gap: 8 }}>
            <Field value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/rss" />
            <Btn small onClick={() => add(url)} disabled={busy || !url.trim()}>Follow</Btn>
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 10 }}>
            {SUGGEST.map((s) => <button key={s.url} className="chip" onClick={() => add(s.url)} title={s.url}>+ {s.name}</button>)}
          </div>
          <p className="dim" style={{ marginTop: 8 }}>New items land as notifications, feed the morning brief, and can trigger automations (Automations → trigger: feed). The scheduler re-checks every 30 min.</p>
        </Panel>
        <Panel icon="grid" title="Following" sub={`${feeds.length} feed(s)`}>
          {!feeds.length && <Empty icon="rss" title="No feeds yet" sub="Follow one on the left — or tell AURA: “follow https://hnrss.org/frontpage”." />}
          {feeds.map((f) => (
            <Row key={f.id} icon="rss" title={f.title || f.url}
              sub={`${f.n_items} item(s)${f.n_unread ? ` · ${f.n_unread} unread` : ""} · fetched ${f.last_fetched ? ago(f.last_fetched) : "never"}${f.error ? ` · ⚠ ${f.error.slice(0, 60)}` : ""}`}
              right={<Btn small onClick={() => api.feeds.remove(f.id).then(reload).then(() => toast("Feed unfollowed", "info")).catch(() => undefined)}>Unfollow</Btn>} />
          ))}
        </Panel>
      </div>
      <Panel icon="book" title="Latest items" sub="newest first">
        {!items.length && <Empty icon="book" title="Nothing yet" sub="Follow a feed, hit Refresh — items appear here and ride into your morning brief." />}
        {items.map((i) => (
          <div key={i.id} className={`feeditem ${i.read ? "" : "unread"}`}>
            <a href={i.link || "#"} target="_blank" rel="noreferrer" onClick={() => { if (!i.read) api.feeds.read(i.id).then(reload).catch(() => undefined); }}>
              {i.title || "(untitled)"}
            </a>
            <span className="dim"> · {i.feed_title || i.feed_url} · {i.published ? new Date(i.published).toLocaleDateString() : ago(i.fetched_at)}</span>
          </div>
        ))}
      </Panel>
    </div>
  );
}

/* ============================== FOLDER WATCH ============================== */
export function WatchPanel() {
  const { toast } = useStore();
  const { data, reload } = useFetch(() => api.watch.state());
  const [busy, setBusy] = useState(false);
  const [newPath, setNewPath] = useState("");
  const w = data as WatchState | null;

  function toggle(on: boolean) {
    api.settings.update({ watch_enabled: on }).then(() => { toast(on ? "Folder watch on" : "Folder watch off", "info"); reload(); }).catch(() => undefined);
  }
  function toggleIngest(on: boolean) {
    api.settings.update({ watch_ingest: on }).then(() => { toast(on ? "Watched files will be indexed into memory" : "Watch will only notify + fire rules", "info"); reload(); }).catch(() => undefined);
  }
  function addPath() {
    const paths = [...(w?.paths || []), newPath.trim()];
    api.watch.setPaths(paths).then(() => { setNewPath(""); toast("Folder added to watch", "success"); reload(); })
      .catch((e) => toast(`${e instanceof Error ? e.message : e}`, "error"));
  }

  return (
    <Panel icon="eye" title="Drop-zone watch" sub={w ? `${w.enabled ? "active" : "off"} · scans every ${w.interval_s}s` : "loading…"}
      right={<span style={{ display: "inline-flex", gap: 6 }}>
        <Btn small onClick={() => { setBusy(true); api.watch.scan().then((r) => { toast(`Scan: ${r.new} new · ${r.changed} changed`, "success"); reload(); }).catch((e) => toast(String(e), "error")).finally(() => setBusy(false)); }}>{busy ? "Scanning…" : "Scan now"}</Btn>
      </span>}>
      <div style={{ display: "flex", gap: 14, alignItems: "center", flexWrap: "wrap", marginBottom: 8 }}>
        <label style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={!!w?.enabled} onChange={(e) => toggle(e.target.checked)} aria-label="watch enabled" /> Enabled
        </label>
        <label style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
          <input type="checkbox" checked={!!w?.ingest} onChange={(e) => toggleIngest(e.target.checked)} aria-label="watch ingest" /> Index into memory
        </label>
        <small className="dim">default inbox: <code>{w?.default_dir}</code></small>
      </div>
      {(w?.paths || []).map((p) => (
        <Row key={p} icon="folder" title={p} sub="watched"
          right={<Btn small onClick={() => api.watch.setPaths((w?.paths || []).filter((x) => x !== p)).then(reload).catch(() => undefined)}>Remove</Btn>} />
      ))}
      <div style={{ display: "flex", gap: 8, margin: "6px 0 10px" }}>
        <input className="inp" style={{ flex: 1 }} placeholder="/absolute/path/to/folder" aria-label="watch path" value={newPath} onChange={(e) => setNewPath(e.target.value)} />
        <Btn small onClick={addPath} disabled={!newPath.trim()}>Watch</Btn>
      </div>
      <small className="secttl">Recent events</small>
      {!(w?.recent || []).length && <p className="dim">Nothing seen yet — drop a file in a watched folder (or run Scan now). New + changed files get indexed, announced, and can trigger automations (trigger kind <code>file</code>).</p>}
      {(w?.recent || []).slice(0, 8).map((r) => (
        <div key={r.path} className="runrow">
          <span className={`statdot ${r.ingested ? "ok" : "warn"}`} />
          <code title={r.path}>{r.path.split("/").slice(-2).join("/")}</code>
          <span className="dim">{r.last_event} · {(r.size / 1024).toFixed(0)} KB{r.file_id ? ` · file #${r.file_id}` : ""}</span>
        </div>
      ))}
      <div style={{ marginTop: 8 }}><Btn small onClick={() => api.watch.reset().then((x) => { toast(`Re-armed (${x.cleared} paths)`, "info"); reload(); })}>Reset state</Btn></div>
    </Panel>
  );
}

/* ============================== CALL HISTORY ============================== */
export function CallHistoryPanel() {
  const { toast, setCall } = useStore();
  const { data, reload } = useFetch(() => api.calls.list(10));
  const calls = data?.calls || [];
  return (
    <Panel icon="phone" title="Recent calls" sub="transcripts land in your conversations + memory"
      right={<Btn small onClick={() => setCall(true)}>Start a call</Btn>}>
      {!calls.length && <Empty icon="phone" title="No calls yet" sub="Hit “Call AURA” — talk hands-free, hang up, and the summary shows up here." />}
      {calls.map((c) => (
        <Row key={c.id} icon="phone" title={`${Math.floor(c.seconds / 60)}:${String(c.seconds % 60).padStart(2, "0")} · ${c.turns} turn(s) · ${c.mode}`}
          sub={`${c.summary.slice(0, 130)}${c.summary.length > 130 ? "…" : ""} · ${ago(c.started_at || c.ended_at)}`}
          right={<Btn small onClick={() => api.calls.remove(c.id).then(reload).then(() => toast("Call deleted", "info")).catch(() => undefined)}>×</Btn>} />
      ))}
    </Panel>
  );
}

/* ============================ VOICE CALL MODE ============================ */
export type CallState = "ready" | "listening" | "thinking" | "speaking" | "saved";

export interface SRLike {
  lang: string; interimResults: boolean; continuous: boolean;
  onresult: ((e: { resultIndex: number; results: { length: number; [i: number]: { isFinal: boolean; 0: { transcript: string } } } }) => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onend: (() => void) | null; start: () => void; stop: () => void; abort: () => void;
}

export function makeRecognizer(): { rec: SRLike | null; kind: "web-speech" | "tap" } {
  try {
    const W = window as unknown as { SpeechRecognition?: new () => SRLike; webkitSpeechRecognition?: new () => SRLike };
    const Ctor = W.SpeechRecognition || W.webkitSpeechRecognition;
    if (!Ctor) return { rec: null, kind: "tap" };
    const rec = new Ctor();
    rec.lang = String(getServer("voice_lang", "en-KE"));
    rec.interimResults = true;
    rec.continuous = true;
    return { rec, kind: "web-speech" };
  } catch { return { rec: null, kind: "tap" }; }
}

export function CallOverlay() {
  const { setCall, toast, speak, stopSpeak } = useStore();
  const { t } = useLang();
  const [state, setState] = useState<CallState>("ready");
  const [caption, setCaption] = useState("");
  const [log, setLog] = useState<{ you: string; aura: string }[]>([]);
  const [secs, setSecs] = useState(0);
  const [summary, setSummary] = useState("");
  const [muted, setMuted] = useState(false);
  const recRef = useRef<SRLike | null>(null);
  const kindRef = useRef<"web-speech" | "tap">("web-speech");
  const sessionRef = useRef<string | null>(null);
  const stopRef = useRef(false);
  const busyRef = useRef(false);
  const mutedRef = useRef(false);
  const turnRef = useRef(0);
  const chatAbortRef = useRef<AbortController | null>(null);
  const captureRef = useRef<{ recorder: MediaRecorder; stream: MediaStream; timer: ReturnType<typeof setTimeout> } | null>(null);
  const mountedRef = useRef(true);
  const logRef = useRef<{ you: string; aura: string }[]>([]);
  const startedRef = useRef(new Date());

  useEffect(() => {
    const iv = setInterval(() => { if (!stopRef.current) setSecs(Math.floor((Date.now() - startedRef.current.getTime()) / 1000)); }, 1000);
    return () => clearInterval(iv);
  }, []);

  function interrupt() {
    turnRef.current += 1;
    chatAbortRef.current?.abort();
    chatAbortRef.current = null;
    busyRef.current = false;
    stopSpeak();
    const capture = captureRef.current;
    captureRef.current = null;
    if (capture) {
      clearTimeout(capture.timer);
      capture.recorder.onstop = null;
      capture.recorder.ondataavailable = null;
      try { capture.recorder.stop(); } catch {}
      capture.stream.getTracks().forEach((tr) => tr.stop());
    }
  }

  useEffect(() => {
    mountedRef.current = true;
    stopRef.current = false;
    const { rec, kind } = makeRecognizer();
    kindRef.current = kind;
    const cleanup = () => {
      mountedRef.current = false;
      stopRef.current = true;
      interrupt();
      if (rec) { rec.onresult = null; rec.onend = null; rec.onerror = null; try { rec.abort(); } catch {} }
      recRef.current = null;
    };
    if (!rec) { setState("ready"); return cleanup; }
    rec.onresult = (e) => {
      if (stopRef.current || mutedRef.current || recRef.current !== rec) return;
      let interim = "", final = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) final += r[0].transcript; else interim += r[0].transcript;
      }
      if (interim) setCaption(interim);
      if (final.trim()) void handle(final.trim());
    };
    rec.onerror = (e) => { if (!stopRef.current && recRef.current === rec && e.error === "not-allowed") { stopRef.current = true; interrupt(); toast("Microphone permission denied", "error"); setCall(false); } };
    rec.onend = () => { if (!stopRef.current && recRef.current === rec && !mutedRef.current) { try { rec.start(); } catch {} } };
    recRef.current = rec;
    try { rec.start(); setState("listening"); } catch { /* autoplay policy / already started */ }
    return cleanup;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handle(heard: string) {
    if (stopRef.current || mutedRef.current || busyRef.current) return Promise.resolve();
    interrupt();
    const generation = turnRef.current;
    const current = () => !stopRef.current && generation === turnRef.current;
    const controller = new AbortController();
    chatAbortRef.current = controller;
    busyRef.current = true;
    setState("thinking"); setCaption(heard);
    let reply = "";
    return chatStream(heard, sessionRef.current, {
      onToken: (tk) => { if (current()) reply += tk; },
      onDone: (d) => { if (current()) sessionRef.current = d.session_id; },
      onError: (err) => { if (current()) toast(`Call error: ${err}`, "error"); },
    }, [], controller.signal).then(() => {
      if (!current()) return;
      const text = reply.trim();
      if (!text) { busyRef.current = false; setState("listening"); return; }
      setLog((l) => { const nl = [...l, { you: heard, aura: text }]; logRef.current = nl; return nl; });
      setCaption(text);
      setState("speaking");
      speak(text, () => { if (current()) setState(mutedRef.current ? "ready" : "listening"); });
      busyRef.current = false;
    }).catch((e) => {
      if (!current()) return;
      busyRef.current = false;
      setState(mutedRef.current ? "ready" : "listening");
      toast(`Call failed: ${e instanceof Error ? e.message : e}`, "error");
    });
  }

  function hangup() {
    stopRef.current = true;
    interrupt();
    try { recRef.current?.stop(); } catch {}
    if (state === "saved") { setCall(false); return; }
    const lines = logRef.current;
    if (!lines.length) { setCall(false); return; }
    const transcript = lines.map((l) => `You: ${l.you}\nAURA: ${l.aura}`).join("\n");
    api.calls.save({ transcript, mode: kindRef.current === "web-speech" ? "browser" : "tap",
                     started_at: startedRef.current.toISOString(), ended_at: new Date().toISOString(),
                     seconds: Math.floor((Date.now() - startedRef.current.getTime()) / 1000) })
      .then((r) => { if (mountedRef.current) { setState("saved"); setSummary(r.summary); } })
      .catch(() => { if (mountedRef.current) { toast("Call ended (transcript not saved)", "warn"); setCall(false); } });
  }

  async function tapTalk() {
    if (stopRef.current || mutedRef.current) return;
    const generation = turnRef.current;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (stopRef.current || generation !== turnRef.current) { stream.getTracks().forEach((tr) => tr.stop()); return; }
      const mr = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      mr.ondataavailable = (e) => chunks.push(e.data);
      mr.onstop = () => {
        if (stopRef.current || generation !== turnRef.current) return;
        stream.getTracks().forEach((tr) => tr.stop());
        captureRef.current = null;
        setState("thinking");
        api.voice.transcribe(new Blob(chunks, { type: "audio/webm" }))
          .then((r) => handle(r.text))
          .catch((e) => { toast(`${e instanceof Error ? e.message : e}`, "error"); setState("ready"); });
      };
      captureRef.current = { recorder: mr, stream, timer: setTimeout(() => { try { mr.stop(); } catch {} }, 5000) };
      mr.start();
      setCaption("Recording up to 5s — then it transcribes…");
    } catch { toast("Microphone unavailable", "error"); }
  }

  const LABELS = { ready: "call.ready", listening: "call.listening", thinking: "call.thinking", speaking: "call.speaking", saved: "call.saved" } as const;
  const labelKey: TKey = LABELS[state];
  return (
    <div className="callwrap" role="dialog" aria-label="voice call">
      <div className="callinner">
        <div className={`callorb ${state}`} data-testid="call-orb"><Icon n="mic" s={46} /></div>
        <h3>{t(labelKey)}</h3>
        <p className="calltimer" data-testid="call-timer">{String(Math.floor(secs / 60)).padStart(2, "0")}:{String(secs % 60).padStart(2, "0")}</p>
        <p className="callcap" data-testid="call-caption">{caption || (state === "ready" ? "Press ● and just talk — I’ll listen" : "")}</p>
        {state === "saved" && <div className="callsum" data-testid="call-summary"><strong>Call saved</strong><p>{summary}</p></div>}
        <div className="calllog">
          {log.slice(-2).map((l, i) => <div key={i} className="callturn"><b>You:</b> {l.you.slice(0, 90)}<br /><b>AURA:</b> {l.aura.slice(0, 120)}</div>)}
        </div>
        <div className="callbtns">
          {state === "speaking" && <Btn onClick={() => { interrupt(); setState(mutedRef.current ? "ready" : "listening"); }}>Stop speaking</Btn>}
          {state === "ready" && kindRef.current === "tap" && <Btn kind="violet" onClick={tapTalk}>● Talk (5s)</Btn>}
          <button className="callmini" aria-label="mute" data-testid="call-mute"
            disabled={stopRef.current} aria-pressed={muted}
            onClick={() => { if (stopRef.current) return; const next = !mutedRef.current; mutedRef.current = next; setMuted(next); if (next) { interrupt(); try { recRef.current?.stop(); } catch {} setState("ready"); } else { try { recRef.current?.start(); } catch {} setState("listening"); } }}>
            <Icon n={muted ? "x" : "wave"} s={16} />
          </button>
          <button className="hangup" onClick={hangup} aria-label="hang up" data-testid="hangup"><Icon n="phone" s={22} /></button>
        </div>
      </div>
    </div>
  );
}
