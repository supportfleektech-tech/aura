"""Shipped example Hermes plugin tools.

Drop your own ``*.py`` files here (or in ``$DATA_DIR/plugins/`` — same format,
survives upgrades) and they load automatically on startup. Each plugin needs::

    TOOL_MANIFEST = {"name": "plugin.my_tool", "risk": "R0",
                     "description": "...", "domain": "general"}
    def run(args: dict, ctx: dict) -> dict: ...

Rules: name must start with ``plugin.``, risk R0–R2 only (R3+ needs core
review and is rejected at load), no network calls except via the ``ctx``
helpers. See docs/PLUGINS.md.
"""
