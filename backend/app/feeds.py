"""RSS / Atom feeds — a zero-credential integration + automation trigger.

Feeds are stored in SQLite; `refresh()` fetches every feed, upserts items by
(feed, guid) and — for genuinely new items — files a notification and fires
automations whose trigger_kind='feed' (optional contains/keyword filter).
Parsing is stdlib XML (RSS 2.0 + Atom); no feedparser dependency, no network
at import time, honest per-feed error fields (never a silent swallow).
"""
from __future__ import annotations

import hashlib
import html
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import httpx

from . import db

UA = "Mozilla/5.0 (compatible; AURA-OS/1.14; +personal feed reader)"
_ATOM = "{http://purl.org/atom/ns#}"


def _strip(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return html.unescape(re.sub(r"\s+", " ", s)).strip()


def _guid(title: str, link: str) -> str:
    raw = f"{title}|{link}".lower().strip()
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


def _pubdate(el, ns: str) -> str:
    for tag in ("published", "date", "updated", "pubDate"):
        node = el.find(f"{ns}{tag}") if ns else el.find(tag)
        if node is not None and (node.text or "").strip():
            txt = node.text.strip()
            try:  # RFC822 (RSS) or ISO (Atom)
                return parsedate_to_datetime(txt).strftime("%Y-%m-%dT%H:%M:%SZ")
            except (TypeError, ValueError):
                try:
                    return txt.replace("Z", "+00:00")[:19] + "Z"
                except Exception:
                    return txt[:20]
    return ""


def parse_feed(xml_text: str) -> dict:
    """(RSS 2.0 | Atom) → {title, items:[{guid,title,link,published}]}."""
    root = ET.fromstring(xml_text)
    chan = root.find("channel")
    items: list[dict] = []
    if chan is not None:  # RSS
        title = _strip((chan.findtext("title") or "").strip()) or "Untitled feed"
        for it in chan.findall("item")[:40]:
            link = (it.findtext("link") or "").strip()
            t = _strip(it.findtext("title") or "")
            guid = (it.findtext("guid") or "").strip() or _guid(t, link)
            items.append({"guid": guid[:200], "title": t[:300], "link": link[:600],
                          "published": _pubdate(it, "")})
        return {"title": title, "items": items}
    if root.tag.endswith("}feed") or root.tag == "feed":  # Atom (any ns)
        ns = root.tag[:root.tag.index("}") + 1] if "}" in root.tag else ""
        title = _strip(root.findtext(f"{ns}title") or "") or "Untitled feed"
        for e in (root.findall(f"{ns}entry") or [])[:40]:
            t = _strip(e.findtext(f"{ns}title") or "")
            link = ""
            for le in e.findall(f"{ns}link"):
                if (le.get("rel") in (None, "alternate")) and le.get("href"):
                    link = le.get("href")
                    break
            gid = (e.findtext(f"{ns}id") or "").strip() or _guid(t, link)
            items.append({"guid": gid[:200], "title": t[:300], "link": link[:600],
                          "published": _pubdate(e, ns)})
        return {"title": title, "items": items}
    raise ValueError("not an RSS/Atom feed (no <channel> or <feed> root)")


def list_feeds() -> list[dict]:
    rows = db.q("""SELECT f.*, (SELECT COUNT(*) FROM feed_items i WHERE i.feed_id=f.id) n_items,
                          (SELECT COUNT(*) FROM feed_items i WHERE i.feed_id=f.id AND i.read=0) n_unread
                   FROM feeds f ORDER BY f.id""")
    return rows


def recent_items(limit: int = 30, feed_id: int | None = None) -> list[dict]:
    sql = ("SELECT i.*, f.url feed_url, f.title feed_title FROM feed_items i "
           "JOIN feeds f ON f.id = i.feed_id")
    p: tuple = ()
    if feed_id:
        sql += " WHERE i.feed_id=?"
        p = (feed_id,)
    sql += " ORDER BY i.id DESC LIMIT ?"
    return db.q(sql, p + (min(max(int(limit or 30), 1), 200),))


def add(url: str) -> dict:
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("feed url must start with http(s)://")
    if len(url) > 600:
        raise ValueError("feed url too long")
    row = db.qone("SELECT id FROM feeds WHERE url=?", (url,))
    if row:
        return {"id": row["id"], "already_existed": True}
    fid = db.run("INSERT INTO feeds (url) VALUES (?)", (url,))
    db.audit("feeds.add", "feed", str(fid), url[:120])
    res = _refresh_one({"id": fid, "url": url})
    return {"id": fid, "title": res.get("title", ""), "items": res.get("new", 0)}


def remove(feed_id: int) -> bool:
    row = db.qone("SELECT id FROM feeds WHERE id=?", (feed_id,))
    if not row:
        return False
    db.run("DELETE FROM feed_items WHERE feed_id=?", (feed_id,))
    db.run("DELETE FROM feeds WHERE id=?", (feed_id,))
    db.audit("feeds.remove", "feed", str(feed_id))
    return True


def _fetch(url: str) -> str:
    r = httpx.get(url, timeout=12.0, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})
    r.raise_for_status()
    return r.text


def _fire_feed_automations(item: dict, feed: dict) -> int:
    """Event-kind automations with trigger_kind='feed' matching this item."""
    fired = 0
    for a in db.q("SELECT * FROM automations WHERE user_id=1 AND status='active' "
                  "AND trigger_kind='feed'"):
        trig = db.jload(a["trigger_config"], {}) or {}
        fid = trig.get("feed_id")
        if fid and int(fid) != int(feed["id"]):
            continue
        kw = str(trig.get("contains", "") or trig.get("keyword", "")).lower().strip()
        blob = f"{item['title']} {item['link']}".lower()
        if kw and kw not in blob:
            continue
        from .hermes import hermes
        # fire_event records last_run/success_count/fail_count; _fire_one alone would
        # silently skip the audit trail for every event-triggered automation.
        res = hermes.fire_event(a, fire_id=f"feed-{a['id']}-{item['link'][:80]}")
        fired += 1 if res.get("ok") else 0
    return fired


def _refresh_one(feed: dict) -> dict:
    if db.DRY_RUN:
        db.blocked(f"feeds: GET {feed['url'][:80]}")
        return {"dry_run": True, "feed_id": feed["id"]}
    try:
        parsed = parse_feed(_fetch(feed["url"]))
    except Exception as e:
        err = f"{type(e).__name__}: {str(e)[:140]}"
        db.run("UPDATE feeds SET error=?, last_fetched=? WHERE id=?",
               (err, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), feed["id"]))
        return {"feed_id": feed["id"], "error": err}
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not feed.get("title") and parsed.get("title"):
        db.run("UPDATE feeds SET title=? WHERE id=?", (parsed["title"][:200], feed["id"]))
    new = 0
    for it in parsed["items"]:
        seen = db.qone("SELECT 1 AS x FROM feed_items WHERE feed_id=? AND guid=?",
                       (feed["id"], it["guid"]))
        if seen:
            continue
        db.run("INSERT OR IGNORE INTO feed_items (feed_id,guid,title,link,published,fetched_at) "
               "VALUES (?,?,?,?,?,?)",
               (feed["id"], it["guid"], it["title"], it["link"], it["published"], now))
        new += 1
        _fire_feed_automations(it, feed)
    db.run("UPDATE feeds SET last_fetched=?, error='' WHERE id=?", (now, feed["id"]))
    if new:
        title = parsed.get("title") or feed.get("title") or feed["url"]
        db.notify(f"Feed: {title}", f"{new} new item(s) — latest: {parsed['items'][0]['title'][:120]}")
    return {"feed_id": feed["id"], "title": parsed.get("title", ""), "new": new,
            "total_seen": len(parsed["items"])}


def refresh_all() -> dict:
    feeds = db.q("SELECT * FROM feeds")
    results = [_refresh_one(f) for f in feeds]
    errs = [r for r in results if r.get("error")]
    return {"feeds": len(feeds), "new_items": sum(r.get("new", 0) for r in results),
            "errors": len(errs), "results": results}


_LAST = {"ts": 0.0}


def maybe_auto_refresh() -> dict | None:
    from . import prefs as _prefs
    every = int(_prefs.get("feeds_refresh_min") or 0)
    if every <= 0:
        return None
    if time.time() - _LAST["ts"] < every * 60:
        return None
    _LAST["ts"] = time.time()
    if db.qone("SELECT id FROM feeds LIMIT 1"):
        return refresh_all()
    return None
