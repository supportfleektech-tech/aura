# AURA OS — Plugin tools

Hermes loads drop-in tools from two folders (in order):

| Folder | Purpose |
|---|---|
| `backend/app/plugins/` | Shipped examples (overwritten on upgrade) |
| `$DATA_DIR/plugins/` | Your files (survive upgrades, included in backups) |

A filename present in both loads from the shipped folder only. Restart the
backend to pick up new/changed files (loading is hot-reload safe). Loading
is failure-safe: a broken file is reported in
`/api/tools → plugins.failed` and never breaks boot or the builtins.

## Minimal plugin

`$DATA_DIR/plugins/word_count.py`:

```python
TOOL_MANIFEST = {
    "name": "plugin.word_count",   # must start with "plugin."
    "risk": "R0",                  # R0, R1, or R2 only (R3+ rejected)
    "description": "Count words in a text.",
    "domain": "general",
}

def run(args: dict, ctx: dict) -> dict:
    text = str(args.get("text", ""))
    return {"ok": True, "words": len(text.split())}
```

Call it: `POST /api/hermes/tools/plugin.word_count {"args": {"text": "hi"}}`
(R0/R1 only — R2 tools still go through the approval flow).

## Rules

- `TOOL_MANIFEST` needs `name` + `run(args, ctx)`; names must start with
  `plugin.` and must not collide with builtin tools.
- Risk `R0` (read-only) / `R1` (local write) / `R2` (external, gated).
  Anything else fails to load with a recorded error.
- Keep plugins dependency-free (stdlib only) — a missing import fails that
  plugin, not the server. No network calls except through `ctx` helpers.
- Shipped examples: `plugin.text_stats` (word/char/sentence counts) and
  `plugin.unit_convert` (`{"value": 10, "from": "km", "to": "mi"}` or
  free-form `"10 km to mi"`).

## Risk review policy

Plugins run in-process with full tool privileges at their declared risk
level. Only install plugin files you trust; review diffs before restarting
after an edit. R2 plugins can message the outside world — they are always
approval-gated in chat/automation paths, same as builtins.
