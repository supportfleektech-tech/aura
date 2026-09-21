#!/usr/bin/env python3
"""Router eval harness — locks classify() behavior across ~200 utterances.

Run:  python3 scripts/eval_router.py [--min 1.0]
Exit 1 when accuracy drops below --min (default 1.0: any misroute fails).

When ADDING intents or tuning INTENT_RULES, update backend/tests/router_cases.json
first (cases encode INTENDED behavior), then make the router pass.
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.orchestrator import classify  # noqa: E402

CASES = json.loads((ROOT / "backend" / "tests" / "router_cases.json").read_text())


def main() -> int:
    min_acc = float(sys.argv[sys.argv.index("--min") + 1]) if "--min" in sys.argv else 1.0
    total, fails, per = 0, [], Counter()
    for intent, texts in CASES["cases"].items():
        for text in texts:
            total += 1
            got, _ = classify(text)
            per[intent] += 1
            if got != intent:
                fails.append((intent, got, text))
                per[intent + "!"] = per.get(intent + "!", 0) + 1
    for spot in CASES.get("domain_spots", []):
        total += 1
        got_i, got_d = classify(spot["text"])
        if got_i != spot["intent"] or got_d != spot["domain"]:
            fails.append((f"{spot['intent']}/{spot['domain']}", f"{got_i}/{got_d}", spot["text"]))
    acc = (total - len(fails)) / total if total else 0
    print(f"router eval: {total - len(fails)}/{total} correct ({acc:.1%})")
    for want, got, text in fails:
        print(f"  FAIL want={want} got={got} :: {text!r}")
    intents = sorted(set(CASES["cases"]))
    worst = [(i, per.get(i + "!", 0), per[i]) for i in intents if per.get(i + "!", 0)]
    if worst:
        print("  weakest:", ", ".join(f"{i} {f}/{n} wrong" for i, f, n in worst))
    return 0 if acc >= min_acc else 1


if __name__ == "__main__":
    sys.exit(main())
