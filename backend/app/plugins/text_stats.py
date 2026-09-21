"""Example plugin: text statistics (R0, read-only)."""
import re

TOOL_MANIFEST = {
    "name": "plugin.text_stats",
    "risk": "R0",
    "description": "Count words, characters, sentences, and reading time of a text.",
    "domain": "general",
}


def run(args: dict, ctx: dict) -> dict:
    text = str(args.get("text", ""))
    words = re.findall(r"\S+", text)
    sents = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    return {
        "ok": True,
        "words": len(words),
        "characters": len(text),
        "sentences": len(sents),
        "reading_seconds": round(len(words) / 200 * 60),
    }
