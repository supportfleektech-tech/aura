"""Example plugin: unit conversion (R0, read-only)."""
import re

TOOL_MANIFEST = {
    "name": "plugin.unit_convert",
    "risk": "R0",
    "description": "Convert km/mi, m/ft, kg/lb, C/F. Args: value, from, to.",
    "domain": "general",
}

_M = {"km": 1000.0, "m": 1.0, "mi": 1609.344, "ft": 0.3048,
      "kg": 1.0, "g": 0.001, "lb": 0.45359237}


def run(args: dict, ctx: dict) -> dict:
    raw = str(args.get("value", args.get("text", ""))).strip()
    frm = str(args.get("from", "")).lower()
    to = str(args.get("to", "")).lower()
    if not frm or not to:  # "10 km to mi" free-form
        m = re.match(r"([\d.]+)\s*([a-z°]+)\s+to\s+([a-z°]+)", raw.lower())
        if not m:
            raise ValueError("need value/from/to, e.g. {'value': 10, 'from': 'km', 'to': 'mi'}")
        raw, frm, to = m.group(1), m.group(2), m.group(3)
    val = float(raw)
    f, t = frm.rstrip("°"), to.rstrip("°")
    if f in ("c", "celsius") and t in ("f", "fahrenheit"):
        out = val * 9 / 5 + 32
    elif f in ("f", "fahrenheit") and t in ("c", "celsius"):
        out = (val - 32) * 5 / 9
    elif f in _M and t in _M:
        out = val * _M[f] / _M[t]
    else:
        raise ValueError(f"unsupported conversion: {frm} → {to}")
    return {"ok": True, "value": round(val, 4), "from": frm, "to": to,
            "result": round(out, 4)}
