"""Weather — Open-Meteo, the zero-key forecast integration.

Configure latitude/longitude (and a place label) in Settings → Weather.
Current conditions + 3-day outlook, cached 15 min in-process. Unconfigured
or unreachable returns {ok: False, reason} — the UI shows an honest empty
state, never a fake temperature. Used by the morning briefing and chat.
"""
from __future__ import annotations

import time

import httpx

from . import prefs

API = "https://api.open-meteo.com/v1/forecast"
_CACHE = {"ts": 0.0, "key": "", "data": None}
TTL = 900

_WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "depositing rime fog", 51: "light drizzle", 53: "drizzle",
    55: "dense drizzle", 56: "freezing drizzle", 57: "dense freezing drizzle",
    61: "slight rain", 63: "rain", 65: "heavy rain", 66: "freezing rain",
    67: "heavy freezing rain", 71: "slight snow", 73: "snow", 75: "heavy snow",
    77: "snow grains", 80: "slight rain showers", 81: "rain showers",
    82: "violent rain showers", 85: "slight snow showers", 86: "snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with heavy hail",
}


def configured() -> bool:
    if not prefs.get("weather_enabled"):
        return False
    lat, lon = float(prefs.get("weather_lat") or 0), float(prefs.get("weather_lon") or 0)
    return not (lat == 0 and lon == 0)


def current(force: bool = False) -> dict:
    """{ok, place, temp_c, feels_c, wind_kmh, condition, today:[…3 days]} — or honest off-state."""
    if not configured():
        return {"ok": False, "reason": "not configured — set latitude/longitude in Settings → Weather",
                "configured": False, "enabled": bool(prefs.get("weather_enabled"))}
    lat, lon = float(prefs.get("weather_lat")), float(prefs.get("weather_lon"))
    key = f"{lat},{lon}"
    now = time.time()
    if not force and _CACHE["data"] and _CACHE["key"] == key and now - _CACHE["ts"] < TTL:
        return dict(_CACHE["data"], cached=True)
    try:
        r = httpx.get(API, params={
            "latitude": lat, "longitude": lon, "timezone": "auto",
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "forecast_days": 3}, timeout=8.0)
        r.raise_for_status()
        d = r.json()
    except Exception as e:
        return {"ok": False, "reason": f"open-meteo unreachable: {type(e).__name__}", "configured": True}
    cur = d.get("current") or {}
    days = []
    daily = d.get("daily") or {}
    for i, date in enumerate(daily.get("time") or []):
        days.append({"date": date,
                     "high_c": (daily.get("temperature_2m_max") or [None] * 3 + [None])[i],
                     "low_c": (daily.get("temperature_2m_min") or [None] * 3 + [None])[i],
                     "rain_pct": (daily.get("precipitation_probability_max") or [None] * 3 + [None])[i],
                     "condition": _WMO.get((daily.get("weather_code") or [None] * 3 + [None])[i], "—")})
    out = {"ok": True, "configured": True,
           "place": str(prefs.get("weather_place") or "").strip() or f"{lat:.2f},{lon:.2f}",
           "temp_c": cur.get("temperature_2m"), "feels_c": cur.get("apparent_temperature"),
           "humidity_pct": cur.get("relative_humidity_2m"),
           "wind_kmh": cur.get("wind_speed_10m"),
           "condition": _WMO.get(cur.get("weather_code"), "—"),
           "today": days, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    _CACHE.update(ts=now, key=key, data=out)
    return dict(out, cached=False)


def brief_line() -> str:
    """One-line digest for briefings; '' when off/unreachable (never noise)."""
    w = current()
    if not w.get("ok"):
        return ""
    rain = next((d for d in w["today"] if (d.get("rain_pct") or 0) >= 50), None)
    umb = f" — rain likely {rain['date']} ({rain['rain_pct']}%), take an umbrella" if rain else ""
    return f"Weather · {w['place']}: {w['temp_c']}°C, {w['condition']}{umb}"
