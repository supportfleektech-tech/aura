/* Slash command palette — opened by a leading "/" in the Composer. */
import { useEffect, useMemo, useState } from "react";
import { SlashCommand, matchCommands } from "./slash";
import { Pill } from "./ui";

export function SlashPalette({ catalog, query, onClose, onPick }: {
  catalog: SlashCommand[];
  query: string;
  onClose: () => void;
  onPick: (c: SlashCommand) => void;
}) {
  const [q, setQ] = useState(query);
  const [sel, setSel] = useState(0);
  const results = useMemo(() => matchCommands(catalog, q), [catalog, q]);
  // Sync the incoming query. Without this the prop is write-only after mount:
  // `fireEvent.change` in a test delivers the whole string in one event, so the
  // palette looked fine, but a real browser delivers "/" first and then "h" one
  // keystroke at a time — and the local state never saw any of them.
  useEffect(() => { setQ(query); }, [query]);

  useEffect(() => setSel(0), [q]);
  // Clamp only when the *catalog* changes. `results` is derived from
  // [catalog, q], so keying a second effect on its length made it fire on the
  // same render as the reset above — the stale `sel` closure then overwrote the
  // reset and Enter picked the wrong row. The functional form keeps the two
  // effects order-independent.
  useEffect(() => {
    setSel((s) => (results.length ? Math.min(s, results.length - 1) : 0));
  }, [catalog, results.length]);

  return (
    <div className="cmdpalette" role="dialog" aria-label="Command palette"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <input
        className="cmdinput"
        role="combobox"
        aria-expanded="true"
        aria-label="Command"
        autoFocus
        value={q}
        placeholder="Type a command…"
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") { e.preventDefault(); onClose(); }
          else if (e.key === "ArrowDown") { e.preventDefault(); setSel((s) => Math.min(s + 1, results.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
          else if (e.key === "Enter") { e.preventDefault(); if (results[sel]) onPick(results[sel]); }
        }}
      />
      <ul className="cmdlist" role="listbox">
        {results.map((c, i) => (
          <li key={c.name} role="option" aria-selected={i === sel}
            className={`cmditem ${i === sel ? "sel" : ""}`}
            onMouseEnter={() => setSel(i)}
            onClick={() => onPick(c)}>
            <code>{c.name}</code>
            <span>{c.summary}</span>
            {c.arg ? <Pill c="blue">{c.arg}</Pill> : null}
          </li>
        ))}
        {results.length === 0 && <li className="cmdempty">No command matches “{q}”</li>}
      </ul>
      <small className="dim">↑↓ to move · Enter to run · Esc to close</small>
    </div>
  );
}
