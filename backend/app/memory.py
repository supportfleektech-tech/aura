"""AURA Memory Engine.

Pipeline: Input -> Extraction -> Candidates -> Sensitivity -> Dedupe ->
Contradiction -> Confidence/Importance -> Policy -> SQLite + vector index.

Vector backend: ChromaDB when installed, else built-in hashed-embedding
store persisted in SQLite (memories.embedding_json). SQLite is always the
source of truth; the vector index is a retrieval accelerator.
"""
from __future__ import annotations

import hashlib
import math
import re
import time
from typing import Any

from . import db

DIM = 192
_SENSITIVE_PATTERNS = [
    r"\b(password|passwd|secret|api[\s_-]?key|token|ssn|national\s+id|id\s+number)\b",
    r"\b\d{3,4}[\s-]?\d{3,4}[\s-]?\d{3,4}\b",  # possible card/ID numbers
    r"\b(mental health|diagnos|therapy|medication|hiv|std)\b",
]
# Shareability order, weakest to strongest. `private` outranks `sensitive`
# because `inference.filter_cloud_memories` withholds `private` under BOTH the
# strict and the relaxed policy, while `sensitive` is strict-only — so a
# `sensitive` row is still cloud-groundable under `relaxed` and a `private` one
# never is. Used to merge a re-confirmed row's label with the incoming one
# without ever weakening it.
_SENSITIVITY_RANK = {"normal": 0, "sensitive": 1, "private": 2}
_STOP = set("the a an and or of to in on for with is are was were be been it its this that you your i my me we our they their he she him her at as by from about into over after before between out up down off over under again once here there when where which who whom what how why can could should would do does did have has had not no yes if than so very just also more most other some such only own same than too".split())


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9']+", text.lower()) if t not in _STOP and len(t) > 1]


def _tag(fn, name: str):
    fn._emb_name = name  # noqa: SLF001 — embedder identity for lazy migration
    return fn


def hashed_embed(text: str, dim: int = DIM) -> list[float]:
    """Deterministic char/word-hash embedding (fallback when no LFM embedder)."""
    vec = [0.0] * dim
    toks = _tokens(text)
    if not toks:
        return vec
    for t in toks:
        h = int(hashlib.sha256(t.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
        vec[(h >> 16) % dim] += 0.5
    # bigrams add a little phrase sensitivity
    for a, b in zip(toks, toks[1:]):
        h = int(hashlib.sha256(f"{a} {b}".encode()).hexdigest(), 16)
        vec[h % dim] += 0.75
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class Embedding(list):
    def __init__(self, values: list[float], model: str):
        super().__init__(values)
        self._emb_name = model


def valid_embedding(vector: Any) -> bool:
    return (isinstance(vector, list) and bool(vector)
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                    for v in vector))


def _embed(text: str, embedder=None) -> tuple[list[float], str]:
    vector = embedder(text) if embedder else hashed_embed(text)
    if not valid_embedding(vector):
        return hashed_embed(text), "hashed:192"
    return vector, getattr(vector, "_emb_name", getattr(embedder, "_emb_name", "hashed:192"))


def _cosine(a: list[float], b: list[float]) -> float:
    """True cosine, i.e. both sides normalised.

    This was a bare dot product, which is only a cosine when both vectors are
    unit length. `hashed_embed` normalises, so the hashed path looked correct
    and hid the bug — but `OllamaClient.embed` returns raw vectors with norm
    ~20, so on any real deployment the score was a dot product: a *perfect*
    match scored ~230 instead of 1.0, which swamped the FTS term and made
    ranking effectively "longest vector wins". The UI then rendered
    `relevance * 100` as a percentage, so a good result displayed as "23000%".

    Unit tests cannot catch this, because they run with Ollama unreachable and
    therefore always take the normalised hashed path.
    """
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def sensitivity_scan(text: str) -> str:
    low = text.lower()
    for p in _SENSITIVE_PATTERNS:
        if re.search(p, low):
            return "sensitive"
    if re.search(r"\b(private|confidential|personal|family|relationship|salary|income)\b", low):
        return "private"
    return "normal"


def _fts_query(text: str) -> str:
    toks = [t for t in _tokens(text)][:12]
    return " OR ".join(toks) if toks else ""


def _topic_fts(topic: str) -> str:
    """FTS5 MATCH expression for the *destructive* topic path. Tokens AND-ed.

    `_fts_query` OR-joins, which is right for recall — "any of these words" — but
    for a topic-delete it is the wrong operation entirely: `/forget old address`
    came to mean "every memory containing *either* word". Measured on the
    reviewer's own example, the command's registered invocation
    (`/forget old address confirm`) deleted 5 of 6 rows, including
    "Cheap wine — an old vintage from 2011" and "The old boiler needs replacing
    before winter" (matched on `old` alone) and "New address is Riverside
    Drive" (matched on `address` alone). A user typing the documented example
    destroyed unrelated memories; the confirm listing was the only thing between
    them and the loss.

    AND is what the words mean: memories about the old address, not every memory
    ever containing "old". A one-word topic is unchanged (an `AND` of one term is
    that term), so `/forget meeting` and `/forget lease` still behave as before.

    Tokens are double-quoted for the reason `_fts_query`'s caller gives:
    `_tokens` admits apostrophes and digits, and an unquoted FTS5 token is
    syntax, not a word.
    """
    toks = [t for t in _tokens(topic)][:12]
    return " AND ".join('"' + t.replace('"', '""') + '"' for t in toks)


# Admission criterion for the *destructive* topic-delete path.
#
# It is deliberately FTS-membership-only, and the semantic half of the usual
# `lex > 0 or sem >= T` rule is deliberately absent. Two measurements:
#
#   * `search()` derives its lexical score as `-bm25/8 + 0.35`. SQLite's bm25
#     here returns -1e-06 for a term in most of the corpus, so every genuine
#     weak FTS hit measures *exactly* 0.350. A `lex >= 0.35` predicate sits on
#     its own floor with zero margin: one point of drift in bm25, in the /8, or
#     in the constant flips every weak hit to a non-deletion. "The row came back
#     from MATCH" cannot drift.
#
#   * The hashed fallback embedder is a bag of token-hash buckets and has no
#     usable notion of "close". Genuine semantic-only pairs (topic vs a memory
#     about it sharing no literal token) measured cos 0.000-0.078, while
#     *unrelated* pairs reached 0.243 and short colliding memories reached 0.67
#     ("Pharmacy is broken" vs "vimlish tarb"). The two populations overlap, so
#     no threshold separates them: a semantic branch here buys false deletions
#     and rescues no true ones.
#
# The cost is that a row about the topic which uses entirely different words is
# not offered as a candidate. For a destructive command that is the right way
# round — the caller lists candidates and the user confirms, so re-asking with
# better words is cheap, while deleting an unrelated memory is not.
def _is_topic_match(fts_hit: bool) -> bool:
    """Did this row carry the topic's words literally?

    Membership, not a magnitude. See the comment above for the two
    measurements that rule out a threshold here. For a multi-word topic the
    membership is against `_topic_fts`'s `AND` — every token, not one of them.
    """
    return bool(fts_hit)


class MemoryEngine:
    # ---------- write pipeline ----------
    def extract_candidates(self, text: str, domain: str, source: str) -> list[dict]:
        """Heuristic extraction: durable facts/preferences/commitments become candidates."""
        cands: list[dict] = []
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.strip()) > 12]
        pref = re.compile(r"\b(i prefer|i like|i love|i hate|i dislike|my favorite|favourite|i want|i need|remind me|don't forget|remember that|note that)\b", re.I)
        fact = re.compile(r"\b(my|our)\s+\w+\s+(is|are|was)\b", re.I)
        commit = re.compile(r"\b(will|going to|by (monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|next week)|deadline|due)\b", re.I)
        for s in sentences[:20]:
            mtype, conf, imp = None, 0.55, 0.4
            if pref.search(s):
                mtype, conf, imp = "preference", 0.75, 0.6
            elif commit.search(s):
                mtype, conf, imp = "episodic", 0.65, 0.65
            elif fact.search(s):
                mtype, conf, imp = "semantic", 0.6, 0.5
            if mtype:
                title = (s[:72] + "…") if len(s) > 72 else s
                cands.append({"title": title, "content": s, "mtype": mtype,
                              "confidence": conf, "importance": imp, "domain": domain, "source": source})
        return cands[:5]

    def _duplicate_of(self, content: str) -> int | None:
        fq = _fts_query(content)
        if not fq:
            return None
        try:
            rows = db.q(
                "SELECT m.id, m.content FROM memories_fts f JOIN memories m ON m.id=f.rowid "
                "WHERE memories_fts MATCH ? AND m.deleted_at IS NULL LIMIT 8", (fq,))
        except Exception:
            rows = []
        a = set(_tokens(content))
        for r in rows:
            b = set(_tokens(r.get("content", "")))
            if not a or not b:
                continue
            jacc = len(a & b) / max(1, len(a | b))
            if jacc > 0.55:
                return r["id"]
        return None

    def store(self, title: str, content: str, domain: str = "general", mtype: str = "semantic",
              source: str = "conversation", confidence: float = 0.7, importance: float = 0.5,
              sensitivity: str | None = None, embedder=None) -> dict:
        sensitivity = sensitivity or sensitivity_scan(f"{title}\n{content}")
        dup = self._duplicate_of(content)
        # Read the pre-image in the same breath as the dedupe decision. `_duplicate_of`
        # matches through an FTS join, so the row it names can be deleted between the
        # two reads. There is then nothing left to re-confirm or to merge a
        # sensitivity label onto, so the honest answer is to fall through and store
        # the memory fresh (`deduped: False`) rather than dereference None — the
        # caller only ever sees a real row either way.
        _before = db.qone("SELECT * FROM memories WHERE id=?", (dup,)) if dup else None
        if dup and _before is not None:
            # A re-confirmation must never weaken an existing label. Otherwise a
            # fact that arrives as `private` (e.g. a client contact — the
            # scanner has no email/phone pattern) and dedupes onto a row an
            # earlier `observe` stored as `normal` would inherit that weaker
            # label and stay cloud-groundable, silently undoing the marking.
            existing = _before.get("sensitivity") or "normal"
            if _SENSITIVITY_RANK.get(sensitivity, 0) > _SENSITIVITY_RANK.get(existing, 0):
                merged_sens = sensitivity
            else:
                merged_sens = existing
            db.run("UPDATE memories SET last_confirmed=strftime('%Y-%m-%dT%H:%M:%fZ','now'), "
                   "importance=MIN(1.0, importance+0.05), sensitivity=? WHERE id=?",
                   (merged_sens, dup))
            from . import undo as _u
            _u.record("memory.store", "update", "memories", dup, _before,
                      f"memories#{dup} re-confirmed (dedup)")
            # Same race as above, one step later: the row can also be deleted between
            # the UPDATE and this read. `_before` is non-None here, so falling back to
            # the pre-image keeps the unpack total; in the normal case `row` wins and
            # the return value is unchanged.
            row = db.qone("SELECT * FROM memories WHERE id=?", (dup,)) or _before
            return {"id": dup, "deduped": True, **row}
        emb, emb_name = _embed(content if embedder else f"{title}\n{content}", embedder)
        mid = db.run(
            "INSERT INTO memories (user_id, domain, mtype, title, content, source, confidence, importance, sensitivity, embedding_json, embedding_model)"
            " VALUES (1,?,?,?,?,?,?,?,?,?,?)",
            (domain, mtype, title, content, source, confidence, importance, sensitivity, db.jdump(emb), emb_name),
        )
        db.log_activity("memory", f"Memory stored: {title[:60]}", f"type={mtype} domain={domain}", domain)
        row = db.qone("SELECT * FROM memories WHERE id=?", (mid,))
        from . import undo as _u
        _u.record("memory.store", "create", "memories", mid, None, f"memories#{mid} {title[:60]}")
        return {"id": mid, "deduped": False, **row}

    def observe(self, text: str, domain: str = "general", source: str = "conversation") -> list[dict]:
        """Evaluate a message for durable memories; store what passes policy."""
        stored = []
        for c in self.extract_candidates(text, domain, source):
            if len(c["content"]) < 16:
                continue
            stored.append(self.store(c["title"], c["content"], c["domain"], c["mtype"],
                                     source, c["confidence"], c["importance"]))
        return stored

    # ---------- retrieval pipeline ----------
    def search(self, query: str, domain: str | None = None, mtype: str | None = None,
               limit: int = 8, embedder=None) -> list[dict]:
        t0 = time.time()
        fq = _fts_query(query)
        filters = ["m.deleted_at IS NULL"]
        params: list[Any] = []
        if domain:
            filters.append("m.domain IN (?, 'general')")
            params.append(domain)
        if mtype:
            filters.append("m.mtype = ?")
            params.append(mtype)
        where = " AND ".join(filters)
        candidates: dict[int, dict] = {}
        fts_hits: dict[int, float] = {}
        if fq:
            try:
                rows = db.q(
                    "SELECT m.*, bm25(memories_fts) AS rank FROM memories_fts f "
                    "JOIN memories m ON m.id=f.rowid WHERE memories_fts MATCH ? "
                    f"AND {where} ORDER BY rank ASC, m.id DESC LIMIT 30", (fq, *params))
                for r in rows:
                    rank = r.pop("rank", 0)
                    candidates[r["id"]] = r
                    fts_hits[r["id"]] = max(0.0, min(1.0, -float(rank or 0) / 8.0 + 0.35))
            except Exception:
                pass
        qvec, qname = _embed(query, embedder)
        migrated = 0
        recent = db.q(f"SELECT m.* FROM memories m WHERE {where} ORDER BY m.id DESC LIMIT 400", tuple(params))
        candidates.update((m["id"], m) for m in recent)
        scored: list[tuple[float, dict]] = []
        for m in sorted(candidates.values(), key=lambda row: -row["id"]):
            try:
                evec = db.jload(m.get("embedding_json"), [])
            except Exception:
                evec = []
            ename = m.get("embedding_model") or ""
            if (not valid_embedding(evec) or len(evec) != len(qvec) or ename != qname) \
                    and migrated < 5 and (m.get("title") or m.get("content")):
                try:
                    nvec, nname = _embed(f"{m.get('title', '')}\n{m.get('content', '')}", embedder)
                    db.run("UPDATE memories SET embedding_json=?, embedding_model=? WHERE id=?",
                           (db.jdump(nvec), nname, m["id"]))
                    evec, ename = nvec, nname
                    m["embedding_model"] = nname
                    migrated += 1
                except Exception:
                    pass
            sem = (_cosine(qvec, evec)
                   if valid_embedding(evec) and len(evec) == len(qvec) and ename == qname else 0.0)
            lex = fts_hits.get(m["id"], 0.0)
            score = 0.45 * sem + 0.35 * lex + 0.10 * float(m.get("importance") or 0) + 0.10 * float(m.get("confidence") or 0)
            # `match` is the *topical* signal only: how strongly the text itself
            # matched, with no importance/confidence terms. `score` is the wrong
            # axis for "which rows are about this topic" — its importance and
            # confidence terms put a ~0.12 floor under every row and dominate
            # the ranking. It is reported for the UI; `forget_candidates` does
            # not go through `search` at all (see there for why).
            m["_match"] = max(lex, sem)
            if score > 0.05:
                scored.append((score, m))
        scored.sort(key=lambda x: (-x[0], -x[1]["id"]))
        out = []
        for s, m in scored[:limit]:
            d = dict(m)
            d.pop("embedding_json", None)
            d.pop("_match", None)
            d["relevance"] = round(float(s), 3)
            d["match"] = round(float(m.get("_match") or 0.0), 3)
            d["why_used"] = ("matched your words" if fts_hits.get(m["id"]) else "semantically related")
            out.append(d)
        db.log_activity("tool", f"Memory search: “{query[:50]}”",
                            f"{len(out)} hits in {(time.time()-t0)*1000:.0f}ms" + (f" · migrated {migrated}" if migrated else ""),
                            domain or "general")
        return out

    # ---------- management ----------
    def get(self, mid: int) -> dict | None:
        r = db.qone("SELECT * FROM memories WHERE id=? AND deleted_at IS NULL", (mid,))
        if r:
            r.pop("embedding_json", None)
        return r

    def update(self, mid: int, **fields) -> dict | None:
        allowed = {"title", "content", "domain", "mtype", "confidence", "importance", "sensitivity"}
        _before = db.qone("SELECT * FROM memories WHERE id=?", (mid,))
        sets = ", ".join(f"{k}=?" for k in fields if k in allowed)
        if not sets:
            return self.get(mid)
        vals = [fields[k] for k in fields if k in allowed]
        if _before and any(k in fields and fields[k] != _before[k] for k in ("title", "content")):
            source = _before.get("source") or "unknown"
            sets += ", source=?"
            vals.append(source if source.startswith("user-corrected:") else f"user-corrected:{source}")
        db.run(f"UPDATE memories SET {sets}, updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (*vals, mid))
        from . import undo as _u
        _u.record("memory.update", "update", "memories", mid, _before,
                  f"memories#{mid} {(_before or {}).get('title', '')[:60]}")
        row = db.qone("SELECT * FROM memories WHERE id=?", (mid,))
        if row:
            db.run("UPDATE memories SET embedding_json=?, embedding_model='hashed:192' WHERE id=?",
                   (db.jdump(hashed_embed(f"{row['title']}\n{row['content']}")), mid))
        db.log_activity("memory", f"Memory updated (#{mid})", "", "general")
        return self.get(mid)

    def delete(self, mid: int) -> None:
        _before = db.qone("SELECT * FROM memories WHERE id=?", (mid,))
        db.run("UPDATE memories SET deleted_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?", (mid,))
        from . import undo as _u
        _u.record("memory.delete", "delete", "memories", mid, _before,
                  f"memories#{mid} {(_before or {}).get('title', '')[:60]}")
        db.log_activity("memory", f"Memory deleted (#{mid})", "", "general")

    def forget_candidates(self, topic: str) -> list[dict]:
        """Every live memory that is *about* `topic`. Read-only — deletes nothing.

        Deliberately not built on `search()`. Two reasons, both measured:

        1. `search` ranks by `score`, which is ~91% importance/confidence. That
           is the wrong axis for "which rows are about this topic" — a passing
           mention scores as high as the real thing.
        2. `search` windows its result (FTS LIMIT 30, then `LIMIT limit`), so a
           large corpus silently hides the genuinely on-topic row. Measured on
           the real engine with 61 memories: `/forget meeting` deleted 38
           incidental mentions and kept the one actually *about* the meeting,
           because that row fell outside the 50-row window.

        So this asks the question directly, with no ranking and no window: did
        FTS match every one of the topic's words? See `_topic_fts` for why the
        tokens are AND-ed here while `search` OR-joins them, and why the
        *caller* must still confirm before deleting — see `_mem_forget`.
        """
        fq = _topic_fts(topic)
        if not fq:
            return []
        fts_ids: set[int] = set()
        try:
            for r in db.q(
                "SELECT m.id, m.title FROM memories_fts f "
                "JOIN memories m ON m.id=f.rowid WHERE memories_fts MATCH ? "
                "AND m.deleted_at IS NULL", (fq,)):
                fts_ids.add(r["id"])
        except Exception:
            return []  # no FTS table: nothing is a candidate, which is the safe side
        if not fts_ids:
            return []
        out: list[dict] = []
        for r in db.q("SELECT id, title FROM memories WHERE deleted_at IS NULL"):
            if not _is_topic_match(r["id"] in fts_ids):
                continue
            out.append({"id": r["id"], "title": str(r.get("title") or "")[:120],
                        "why": "words"})
        return out

    def forget_topic(self, topic: str) -> int:
        """Soft-delete every memory that is actually about `topic`.

        Kept as the deleting entry point because `POST /api/memories/forget`
        returns `{"forgotten": <int>}`; that response shape is a contract.
        Selection itself lives in `forget_candidates`, which gates on the
        *topical* signal and never on `relevance`/`score`.
        """
        hits = self.forget_candidates(topic)
        for h in hits:
            self.delete(h["id"])
        db.log_activity("memory", f"Forgot topic: {topic}",
                        f"{len(hits)} memories removed", "general", "warn")
        return len(hits)

    def stats(self) -> dict:
        r = db.qone("SELECT COUNT(*) c FROM memories WHERE deleted_at IS NULL")
        by = db.q("SELECT domain, COUNT(*) c FROM memories WHERE deleted_at IS NULL GROUP BY domain")
        return {"total": (r or {}).get("c", 0), "by_domain": {x["domain"]: x["c"] for x in by}}


_tag(hashed_embed, "hashed:192")


memory_engine = MemoryEngine()
