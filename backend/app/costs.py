"""Cloud LLM spend tracking + budget enforcement (v1.6.0 WS5).

Every model call is journaled to `llm_usage` with tokens, cost, and purpose.
Day/month boundaries are UTC. A cap of 0 means unlimited. Unknown pricing
(free-tier rotation, custom endpoints) records tokens with NULL cost and is
surfaced honestly as `unknown_pricing` instead of $0.
"""
from . import db, prefs


class BudgetExceeded(RuntimeError):
    pass


# Static per-1M-token USD (prompt, completion) for well-known non-OpenRouter
# models, as of 2026-09. OpenRouter pricing comes from the live catalog;
# anything unknown records NULL cost, never a guess.
KNOWN_PRICES: dict[tuple[str, str], tuple[float, float]] = {
    ("openai", "gpt-4o-mini"): (0.15, 0.60),
    ("openai", "gpt-4o"): (2.50, 10.00),
}

_pricing_cache: dict[tuple[str, str], tuple[float, float]] = {}


def cache_openrouter_pricing(raw_models: list[dict]) -> None:
    """Snapshot per-token USD pricing from a live OpenRouter catalog fetch."""
    for m in raw_models:
        mid = m.get("id", "")
        price = m.get("pricing") or {}
        try:
            p = float(price.get("prompt", "") or 0) * 1e6
            c = float(price.get("completion", "") or 0) * 1e6
        except (TypeError, ValueError):
            continue
        _pricing_cache[("openrouter", mid)] = (p, c)


def unit_price(provider: str, model: str) -> tuple[float, float] | None:
    """Per-1M-token (prompt, completion) USD, or None when unknown."""
    if provider == "ollama":
        return (0.0, 0.0)
    key = (provider, model)
    if key in _pricing_cache:
        return _pricing_cache[key]
    if provider == "openrouter" and model.endswith(":free"):
        return (0.0, 0.0)
    return KNOWN_PRICES.get(key)


def cost_of(provider: str, model: str, prompt_tok: int, comp_tok: int) -> float | None:
    u = unit_price(provider, model)
    if u is None:
        return None
    return round((prompt_tok * u[0] + comp_tok * u[1]) / 1e6, 6)


def record(provider: str, model: str, purpose: str, prompt_tok: int, comp_tok: int,
           ms: int, ok: bool = True, error: str = "") -> float | None:
    cost = cost_of(provider, model, prompt_tok, comp_tok) if ok else None
    try:
        db.run("INSERT INTO llm_usage (provider, model, purpose, prompt_tokens, completion_tokens,"
               " cost_usd, ms, ok, error) VALUES (?,?,?,?,?,?,?,?,?)",
               (provider, model, purpose, int(prompt_tok or 0), int(comp_tok or 0),
                cost, int(ms or 0), 1 if ok else 0, (error or "")[:200]))
    except Exception:
        pass
    return cost


def _spent(where: str) -> dict:
    r = db.qone(f"SELECT COUNT(*) calls, COALESCE(SUM(prompt_tokens),0) pt,"
                f" COALESCE(SUM(completion_tokens),0) ct, COALESCE(SUM(cost_usd),0) cost,"
                f" SUM(cost_usd IS NULL AND ok=1) unknown_n FROM llm_usage WHERE ok=1 AND {where}") or {}
    return {"calls": r.get("calls", 0), "prompt_tokens": r.get("pt", 0),
            "completion_tokens": r.get("ct", 0), "cost_usd": round(r.get("cost", 0) or 0, 4),
            "unknown_pricing": bool(r.get("unknown_n"))}


def summary() -> dict:
    today = _spent("date(at)=date('now')")
    month = _spent("strftime('%Y-%m',at)=strftime('%Y-%m','now')")
    by_model = db.q("SELECT provider, model, COUNT(*) calls, COALESCE(SUM(prompt_tokens),0) pt,"
                    " COALESCE(SUM(completion_tokens),0) ct, COALESCE(SUM(cost_usd),0) cost,"
                    " SUM(cost_usd IS NULL) unknown_n FROM llm_usage WHERE ok=1"
                    " GROUP BY provider, model ORDER BY cost DESC LIMIT 20")
    by_day = db.q("SELECT date(at) day, COUNT(*) calls, COALESCE(SUM(cost_usd),0) cost"
                  " FROM llm_usage WHERE ok=1 AND date(at) >= date('now','-6 days')"
                  " GROUP BY day ORDER BY day")
    dcaps = float(prefs.get("cost_daily_cap_usd") or 0)
    mcaps = float(prefs.get("cost_monthly_cap_usd") or 0)
    return {"today": today, "month": month,
            "by_model": [{"provider": r["provider"], "model": r["model"], "calls": r["calls"],
                          "prompt_tokens": r["pt"], "completion_tokens": r["ct"],
                          "cost_usd": round(r["cost"] or 0, 4),
                          "unknown_pricing": bool(r["unknown_n"])} for r in by_model],
            "by_day": [{"day": r["day"], "calls": r["calls"], "cost_usd": round(r["cost"] or 0, 4)}
                       for r in by_day],
            "budgets": {"daily_cap_usd": dcaps, "monthly_cap_usd": mcaps,
                        "daily_over": bool(dcaps > 0 and today["cost_usd"] >= dcaps),
                        "monthly_over": bool(mcaps > 0 and month["cost_usd"] >= mcaps)}}


def check() -> tuple[bool, str]:
    """Budget gate for cloud calls. (True, '') when spend is within caps."""
    dcaps = float(prefs.get("cost_daily_cap_usd") or 0)
    mcaps = float(prefs.get("cost_monthly_cap_usd") or 0)
    if dcaps > 0:
        spent = _spent("date(at)=date('now')")["cost_usd"]
        if spent >= dcaps:
            return (False, f"daily cloud budget exceeded (${spent:.2f} / ${dcaps:.2f}). "
                           "Raise it in Settings → Cloud costs, or wait for UTC midnight.")
    if mcaps > 0:
        spent = _spent("strftime('%Y-%m',at)=strftime('%Y-%m','now')")["cost_usd"]
        if spent >= mcaps:
            return (False, f"monthly cloud budget exceeded (${spent:.2f} / ${mcaps:.2f}). "
                           "Raise it in Settings → Cloud costs.")
    return (True, "")
