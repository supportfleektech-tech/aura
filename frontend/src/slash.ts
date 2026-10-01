/* Slash command matcher — pure so it is directly unit-testable, no React. */

export type SlashCommand = { name: string; category: string; summary: string; example: string; arg: string };

/** Score one command against a query. Higher is better; 0 means no match.
 *  `q` arrives with its leading slash already stripped, so the name is stripped
 *  too — comparing "/task" against "task" makes the exact and prefix branches
 *  unreachable and silently demotes every hit to a substring match. */
function score(c: SlashCommand, q: string): number {
  if (!q) return 1;
  const n = c.name.replace(/^\//, "").toLowerCase();
  if (n === q) return 1000;
  if (n.startsWith(q)) return 500 - n.length;
  if (c.name.toLowerCase().includes(q)) return 200 - n.length;
  if (c.summary.toLowerCase().includes(q)) return 100;
  if (c.category.toLowerCase().includes(q)) return 50;
  return 0;
}

export function matchCommands(cat: SlashCommand[], query: string): SlashCommand[] {
  const q = (query || "").replace(/^\//, "").trim().toLowerCase();
  // A bare "/" is a browse, not a search. Keep the backend's curated order
  // (Navigation → Memory → Tasks → …) instead of re-sorting by name: grouping
  // by category is the thing that makes 27 commands findable without typing.
  if (!q) return cat.slice();
  return cat
    .map((c) => [score(c, q), c] as const)
    .filter(([s]) => s > 0)
    .sort((a, b) => b[0] - a[0] || a[1].name.localeCompare(b[1].name))
    .map(([, c]) => c);
}

/** Narrow an untrusted `/api/slash` payload to renderable commands. */
export function catalogFrom(res: unknown): SlashCommand[] {
  const out: SlashCommand[] = [];
  const cmds = (res as { commands?: unknown })?.commands;
  if (!Array.isArray(cmds)) return out;
  for (const raw of cmds) {
    if (!raw || typeof raw !== "object") continue;
    const r = raw as Record<string, unknown>;
    if (typeof r.name !== "string") continue;
    out.push({
      name: r.name, category: String(r.category || "Other"), summary: String(r.summary || ""),
      example: String(r.example || ""), arg: String(r.arg || ""),
    });
  }
  return out;
}