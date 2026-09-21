"""Web reader — fetch a page and extract readable text, with SSRF guards.

Used two ways: paste any link in chat and AURA reads it into the grounding
(`web_read` intent), or call the `web.fetch` Hermes tool from a mission step.
"""
from __future__ import annotations
import ipaddress
import os
import re
import socket
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse

import httpx

URL_RE = re.compile(r"https?://[^\s<>\"]+")
MAX_BYTES = 1500000
TIMEOUT_S = 15
TEXT_CAP = 6000
LINKS_CAP = 20


def extract_urls(text: str, limit: int = 2) -> list[str]:
    seen: list[str] = []
    for m in URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(").,;!?")
        if u not in seen:
            seen.append(u)
        if len(seen) >= limit:
            break
    return seen


def _host_ok(host: str) -> bool:
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False
    return True


class _Reader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title: str = ""
        self._in_title = False
        self._skip = 0
        self.chunks: list[str] = []
        self.links: list[dict] = []
        self._cur_href: str | None = None
        self._cur_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template"):
            self._skip += 1
        if tag == "title":
            self._in_title = True
        if tag == "a":
            href = dict(attrs).get("href", "")
            self._cur_href = href
            self._cur_text = []

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template") and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        if tag == "a":
            if self._cur_href and len(self.links) < LINKS_CAP:
                txt = " ".join(" ".join(self._cur_text).split())
                if txt:
                    self.links.append({"text": txt[:120], "href": self._cur_href})
            self._cur_href = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        t = data.strip()
        if t and self._cur_href is not None:
            self._cur_text.append(t)
        if t:
            self.chunks.append(t)


def fetch(url: str) -> dict:
    """Fetch a URL and return {url, title, text, links} or {url, error}."""
    url = (url or "").strip()
    try:
        parts = urlparse(url)
    except Exception:
        return {"url": url, "error": "bad URL"}
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return {"url": url, "error": "only http(s) URLs are supported"}
    if not _host_ok(parts.hostname):
        return {"url": url, "error": "blocked: private or unresolvable host"}
    try:
        r = httpx.get(url, timeout=TIMEOUT_S, follow_redirects=True,
                      headers={"User-Agent": "AURA-reader/1.0"})
    except Exception as e:
        return {"url": url, "error": f"fetch failed: {e.__class__.__name__}"}
    final_host = urlparse(str(r.url)).hostname or ""
    if not _host_ok(final_host):
        return {"url": url, "error": "blocked: redirect target is private"}
    if r.status_code >= 400:
        return {"url": url, "error": f"HTTP {r.status_code}"}
    ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype not in ("text/html", "application/xhtml+xml", "text/plain"):
        return {"url": url, "error": f"not a readable page ({ctype or 'unknown type'})"}
    raw = r.content[:MAX_BYTES]
    if ctype == "text/plain":
        text = raw.decode("utf-8", "replace")
        return {"url": str(r.url), "title": "", "text": " ".join(text.split())[:TEXT_CAP], "links": []}
    try:
        html = raw.decode("utf-8", "replace")
    except Exception:
        return {"url": url, "error": "could not decode page"}
    rd = _Reader()
    try:
        rd.feed(html)
    except Exception:
        return {"url": url, "error": "could not parse page"}
    text = " ".join(" ".join(rd.chunks).split())
    links = [{"text": l["text"], "href": urljoin(str(r.url), l["href"])}
             for l in rd.links if l["href"].startswith(("http", "/"))]
    return {"url": str(r.url), "title": " ".join(rd.title.split())[:200],
            "text": text[:TEXT_CAP], "links": links[:LINKS_CAP]}


# ------------------------------------------------------------------ search ---
SEARCH_URL = os.environ.get("AURA_SEARCH_URL", "https://html.duckduckgo.com/html/")
SEARCH_TIMEOUT_S = 10
SEARCH_CAP = 6


class _SearchParser(HTMLParser):
    """Collect (title, link, snippet) triples from DuckDuckGo HTML results.

    DDG renders the title link (`a.result__a`) and the snippet
    (`a.result__snippet`) as *sibling* anchors, so the snippet is appended to
    the most recently completed result rather than to a single open anchor.
    """

    def __init__(self):
        super().__init__()
        self.results: list[dict] = []
        self._cur: dict | None = None   # title anchor currently being built
        self._last: dict | None = None  # most recently completed result
        self._in_a = False
        self._a_class = ""

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        cls = dict(attrs).get("class", "") or ""
        self._in_a = True
        self._a_class = cls
        if "result__a" in cls:
            self._cur = {"title": "", "link": dict(attrs).get("href", ""), "snippet": ""}

    def handle_endtag(self, tag):
        if tag == "a":
            if self._cur is not None and (self._cur.get("title") or "").strip():
                self.results.append(self._cur)
                self._last = self._cur
            self._cur = None
            self._in_a = False
            self._a_class = ""

    def handle_data(self, data):
        if not self._in_a:
            return
        if "result__snippet" in self._a_class:
            if self._last is not None:
                self._last["snippet"] += data
        elif "result__a" in self._a_class and self._cur is not None:
            self._cur["title"] += data


def _decode_uddg(href: str) -> str:
    """DDG HTML links are redirects: //duckduckgo.com/l/?uddg=<url>."""
    if "uddg=" in href:
        m = re.search(r"uddg=([^&]+)", href)
        if m:
            return unquote(m.group(1))
    return href


def parse_search_html(html: str) -> list[dict]:
    """Parse DDG HTML into [{title, link, snippet}] — pure, for tests."""
    p = _SearchParser()
    try:
        p.feed(html or "")
    except Exception:
        return []
    out = []
    for r in p.results:
        link = _decode_uddg((r.get("link") or "").strip())
        title = " ".join((r.get("title") or "").split())[:160]
        snippet = " ".join((r.get("snippet") or "").split())[:300]
        if not title or not link:
            continue
        if link.startswith("//"):
            link = "https:" + link
        if not link.startswith("http"):
            continue
        out.append({"title": title, "link": link, "snippet": snippet})
    return out[:SEARCH_CAP]


def search(query: str, limit: int = 5) -> dict:
    """Keyless web search. Returns {query, results, provider} or a honest error.

    Read-only, time-boxed, capped; on any failure returns results: [] plus an
    error string — never fabricates results.
    """
    q = (query or "").strip()
    if not q:
        return {"query": "", "results": [], "error": "query is empty"}
    try:
        parts = urlparse(SEARCH_URL)
    except Exception:
        return {"query": q, "results": [], "error": "search provider misconfigured"}
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return {"query": q, "results": [], "error": "search provider misconfigured"}
    try:
        r = httpx.get(SEARCH_URL, params={"q": q[:300]}, timeout=SEARCH_TIMEOUT_S,
                      follow_redirects=True, headers={"User-Agent": "AURA-search/1.0"})
    except Exception as e:
        return {"query": q, "results": [], "error": f"search failed: {e.__class__.__name__}"}
    if r.status_code >= 400:
        return {"query": q, "results": [], "error": f"search HTTP {r.status_code}"}
    results = parse_search_html(r.text)[:max(1, min(limit, SEARCH_CAP))]
    if not results:
        return {"query": q, "results": [], "error": "no results parsed"}
    return {"query": q, "results": results, "provider": "duckduckgo"}
