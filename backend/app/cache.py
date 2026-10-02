"""In-process TTL + LRU cache (spec §6, FR-PERF-003).

The spec asks for a "Redis-compatible cache". This is deliberately not Redis.
AURA is a single process with one pooled SQLite connection; an in-process cache
with the same read-through semantics gives the same hit rates for the data that
matters here (the Ollama model catalog and the health probes) without a network
hop, without an extra process to supervise, and without a new failure mode in a
system whose premise is "one box, one process, no external services".

Only cache what is expensive to compute and trivially re-derivable. Never cache
anything a mutation can invalidate — a stale approval list is a safety problem,
not a latency win — and never cache a value a caller is expected to re-validate
against (`set_default` checks a model against the catalog; a stale catalog would
let it point at a model Ollama no longer has).

Two rules for call sites:

* `get()` returning a hit hands back the *same* object every time. Copy it
  before mutating, or the next reader sees your edit — and copy *deeply*, not
  `dict(...)`: a shallow copy shares every nested list and dict with the cached
  value, so `hit["models"][0]["name"] = …` still poisons the next reader.
* Cache only what a *reader* asks for. An explicit refresh (a sync, a validate)
  must bypass the cache or it silently stops refreshing. Key on every input that
  can change the answer (e.g. a base URL read from Settings), so a settings
  change is a miss rather than a stale hit.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable

DEFAULT_MAX_ENTRIES = 256
DEFAULT_TTL_S = 30.0


class TTLCache:
    """Thread-safe LRU with a per-entry TTL. `ttl_s <= 0` disables reads.

    `stats()` takes the same lock as `get`/`set` and never calls back into
    them, so it cannot deadlock against a concurrent reader or writer (including
    the tool thread pool in `workers.drain`).
    """

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES, ttl_s: float = DEFAULT_TTL_S):
        self._max = max(1, int(max_entries))
        self._ttl = float(ttl_s)
        self._data: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
        self._lock = threading.RLock()
        self._hits = self._misses = self._evictions = 0

    def get(self, key: str) -> Any | None:
        """Value for `key`, or None on a miss, an expired entry, or ttl<=0."""
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                self._misses += 1
                return None
            expires_at, value = hit
            if self._ttl <= 0 or time.monotonic() >= expires_at:
                # Expired (or caching switched off): drop it rather than leave
                # it to be re-checked on every read.
                self._data.pop(key, None)
                self._misses += 1
                return None
            self._data.move_to_end(key)  # most recently *used* goes last
            self._hits += 1
            return value

    def set(self, key: str, value: Any, ttl_s: float | None = None) -> None:
        """Store `value`. `ttl_s` overrides the cache default for this entry
        only — used to keep a *failure* result for seconds, not a full TTL."""
        with self._lock:
            ttl = self._ttl if ttl_s is None else float(ttl_s)
            self._data[key] = (time.monotonic() + ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)
                self._evictions += 1

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def set_ttl(self, ttl_s: float) -> None:
        """Retune in place. Read per call so a Settings change takes effect
        without a restart; existing entries keep the TTL they were stored with."""
        with self._lock:
            self._ttl = float(ttl_s)

    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {"entries": len(self._data), "hits": self._hits, "misses": self._misses,
                    "hit_rate": round(self._hits / total, 3) if total else 0.0,
                    "evictions": self._evictions, "ttl_s": self._ttl}


def tuned_ttl(default: float = DEFAULT_TTL_S) -> float:
    """Resolve the TTL from Settings (`cache_ttl_s`), else `default`.

    0 is a real answer, not "unset": it means don't cache. Never baked in at
    import time — Settings changes must apply without a restart.
    """
    try:
        from . import prefs

        return max(0.0, float(prefs.get("cache_ttl_s")))
    except Exception:
        return float(default)


def cached(ttl_s: float = DEFAULT_TTL_S,
           max_entries: int = DEFAULT_MAX_ENTRIES) -> Callable[[Callable], Callable]:
    """Memoize a function on a private TTLCache, keyed by its arguments.

    Only successful returns are cached: an exception propagates instead of
    being stored as a value, so a transient failure is never pinned for a TTL.
    """
    store = TTLCache(max_entries=max_entries, ttl_s=ttl_s)

    def deco(fn: Callable) -> Callable:
        def wrapper(*args, **kwargs) -> Any:
            key = f"{fn.__name__}:{args!r}:{tuple(sorted(kwargs.items()))!r}"
            hit = store.get(key)
            if hit is not None:
                return hit
            out = fn(*args, **kwargs)
            store.set(key, out)
            return out

        wrapper.__name__ = getattr(fn, "__name__", "cached")
        wrapper.__doc__ = getattr(fn, "__doc__", None)
        wrapper.cache = store  # type: ignore[attr-defined]
        wrapper.__wrapped__ = fn  # type: ignore[attr-defined]
        return wrapper

    return deco
