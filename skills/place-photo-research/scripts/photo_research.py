#!/usr/bin/env python3
"""Local helpers for the place-photo-research Codex skill.

Discovery and source interpretation are performed by Codex using its real tools.
This module provides deterministic date normalization, bounded public fetching,
record validation, conservative download gates and local reports.
It is not a multi-tenant security boundary or a copyright authentication service.
Python 3.10+; Pillow is required only for image validation/downloads.
"""
from __future__ import annotations

import argparse
import asyncio
import calendar
import hashlib
import html
from html.parser import HTMLParser
import http.client
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
from urllib import request as http_request
from urllib.error import HTTPError, URLError
import warnings
from zoneinfo import ZoneInfo

VERSION = "1.0.0"
UA = "PlacePhotoResearch/1.0"
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 40_000_000
CRAWL4AI_MAX_SEARCH_PAGES = 10
CRAWL4AI_MAX_SOURCE_PAGES = 24
CRAWL4AI_PAGE_TIMEOUT_MS = 30_000
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
NON_PHOTO = re.compile(r"\b(banknotes?|coins?|currency|stamps?|maps?|paintings?|illustrations?|drawings?|engravings?|logo|icon|avatar|qr)\b|纸币|鈔票|钞票|邮票|绘画|地圖|地图|图标|头像|二维码", re.I)
LICENSE_URLS = {
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-SA-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
}
EVIDENCE_KINDS = {"place", "scene_date", "license", "access_terms", "permission", "creator", "other"}
DATE_BASES = {"catalogue", "source_caption", "provider_date_taken", "original_exif", "album_caption", "unknown", "upload_date", "page_publication", "visual_guess"}
WEAK_DATE_BASES = {"unknown", "upload_date", "page_publication", "visual_guess"}

class ResearchError(Exception):
    pass


def _text(value) -> str:
    if isinstance(value, (list, tuple)):
        value = " ".join(str(item) for item in value)
    return html.unescape(re.sub(r"<[^>]*>", "", str(value or "")))[:4000]


def _configured_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    return "" if value.casefold() in {"", "null", "<null>", "none"} else value


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()

def fail(message: str) -> None:
    raise ResearchError(message)

def read_json(path: Path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)

def write_text(path: Path, text: str) -> None:
    """Atomic replace. Existing symlinks are rejected; parent is caller-scoped."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        fail(f"Refusing symlink output: {path}")
    fd, name = tempfile.mkstemp(prefix=".photo-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)

def write_json(path: Path, value) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")

def checked_path(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = root / relative
    if path.is_symlink():
        fail(f"Symlink output forbidden: {relative}")
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        fail(f"Path outside run folder: {relative}")
    return resolved

def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    result = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                item = json.loads(line)
            except json.JSONDecodeError as e:
                fail(f"{path.name}:{n}: {e}")
            if not isinstance(item, dict):
                fail(f"{path.name}:{n}: expected an object")
            result.append(item)
    return result

def append_jsonl(path: Path, value: dict) -> None:
    # This CLI is deliberately single-writer; do not run parallel writers.
    previous = path.read_text(encoding="utf-8") if path.exists() else ""
    write_text(path, previous + json.dumps(value, ensure_ascii=False) + "\n")

def subtract_months(d: date, months: int) -> date:
    ordinal = d.year * 12 + d.month - 1 - months
    year, month0 = divmod(ordinal, 12)
    return date(year, month0 + 1, min(d.day, calendar.monthrange(year, month0 + 1)[1]))

def normalize_period(period: str | None, as_of: date, recent_months: int = 24) -> dict:
    if not 1 <= recent_months <= 120:
        fail("recent_months must be 1..120")
    raw = period
    p = (period or "").strip().lower()
    current = {"", "now", "current", "present", "present-day", "today's view", "现在", "目前", "当下"}
    if p in current:
        return {"mode": "current", "basis": "absent_period_default" if not p else "explicit_current",
                "original_expression": raw, "start": subtract_months(as_of, recent_months).isoformat(),
                "end": as_of.isoformat(), "precision": "preferred_recent_window"}
    if p in {"today", "今天"}:
        return {"mode": "current", "basis": "explicit_current", "original_expression": raw,
                "start": as_of.isoformat(), "end": as_of.isoformat(), "precision": "day"}
    if p in {"this month", "本月"}:
        return {"mode": "current", "basis": "explicit_current", "original_expression": raw,
                "start": as_of.replace(day=1).isoformat(), "end": as_of.isoformat(), "precision": "month"}
    if p in {"old", "historical", "unspecified-historical", "老照片", "过去", "以前"}:
        return {"mode": "historical_unspecified", "basis": "explicit_historical", "original_expression": raw,
                "start": None, "end": None, "precision": "unknown"}
    if p in {"last year", "去年"}:
        start, end, precision = date(as_of.year - 1, 1, 1), date(as_of.year - 1, 12, 31), "year"
    elif re.fullmatch(r"\d{4}(?:s|年代)", p):
        year = int(p[:4])
        if year % 10:
            fail("A decade must start in a year divisible by 10")
        start, end, precision = date(year, 1, 1), date(year + 9, 12, 31), "decade"
    elif re.fullmatch(r"\d{4}\s*年?", p):
        year = int(re.search(r"\d{4}", p).group())
        start, end, precision = date(year, 1, 1), date(year + 9, 12, 31), "decade_from_year"
    elif re.fullmatch(r"\d{4}\s*[-–—:]\s*\d{4}", p):
        a, b = re.split(r"\s*[-–—:]\s*", p)
        start, end, precision = date(int(a), 1, 1), date(int(b), 12, 31), "range"
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", p):
        start = end = date.fromisoformat(p)
        precision = "day"
    elif re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\.\d{4}-\d{2}-\d{2}", p):
        a, b = p.split("..")
        start, end, precision = date.fromisoformat(a), date.fromisoformat(b), "range"
    else:
        fail("Unsupported period. Codex must resolve an explicit expression to YYYY (a ten-year window), YYYYs, YYYY-YYYY, "
             "YYYY-MM-DD..YYYY-MM-DD, current or historical; do not silently guess a century/range.")
    if start > end:
        fail("Period start is after its end")
    if start > as_of:
        fail("Future-only period: authentic photographs of a future scene cannot be retrieved")
    return {"mode": "historical_range", "basis": "explicit_period", "original_expression": raw,
            "start": start.isoformat(), "end": end.isoformat(), "precision": precision}

def valid_url(url: str):
    if not isinstance(url, str) or not url or len(url) > 8192:
        fail("Invalid URL")
    if any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url or "<" in url or ">" in url:
        fail("Control characters/backslashes are forbidden in URLs")
    p = urlsplit(url)
    if p.scheme not in {"http", "https"} or not p.hostname or p.username is not None or p.password is not None:
        fail("Only public HTTP(S) URLs without credentials are accepted")
    try:
        host = p.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        port = p.port or (443 if p.scheme == "https" else 80)
    except (ValueError, UnicodeError) as e:
        fail(str(e))
    if port != (443 if p.scheme == "https" else 80):
        fail("Only standard HTTP(S) ports are accepted")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or "%" in host:
        fail("Local/internal host forbidden")
    return p, host, port

def public_addresses(host: str, port: int) -> list[str]:
    try:
        rows = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        fail(f"DNS lookup failed: {e}")
    ips = sorted({row[4][0] for row in rows})
    if not ips:
        fail("No DNS addresses")
    for text in ips:
        ip = ipaddress.ip_address(text)
        if not ip.is_global:
            fail(f"Non-public destination blocked: {host}")
    return ips

class PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host: str, ip: str, port: int, timeout: float):
        super().__init__(host, port=port, timeout=timeout)
        self.ip = ip
    def connect(self):
        self.sock = socket.create_connection((self.ip, self.port), self.timeout)

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, ip: str, port: int, timeout: float):
        super().__init__(host, port=port, timeout=timeout, context=ssl.create_default_context())
        self.ip = ip
    def connect(self):
        sock = socket.create_connection((self.ip, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except Exception:
            sock.close()
            raise

class Fetcher:
    """Public-only direct sockets, no proxy/cookies/auth, per-hop host checks.

    Intended for a reviewed local Codex workflow. Does not bypass an egress proxy;
    environments requiring one must provide an approved different fetch tool.
    """
    def __init__(self):
        self.robots: dict[str, RobotFileParser | bool] = {}
        self.last_fetch: dict[str, float] = {}

    def robot_check(self, url: str, hosts: set[str]) -> None:
        p, host, _ = valid_url(url)
        origin = f"{p.scheme}://{p.netloc}"
        if origin not in self.robots:
            status, _, _, body = self.fetch(origin + "/robots.txt", 256_000, hosts,
                                             check_robots=False, deadline_seconds=20)
            if status in {404, 410}:
                self.robots[origin] = True
            elif status == 200:
                parser = RobotFileParser()
                parser.parse(body.decode("utf-8", errors="replace").splitlines())
                self.robots[origin] = parser
            else:
                fail(f"Cannot establish robots access (HTTP {status}); do not bypass")
        rule = self.robots[origin]
        if rule is not True and not rule.can_fetch(UA, url):
            fail("robots.txt disallows this URL")
        delay = 1.0
        if rule is not True:
            delay = max(delay, float(rule.crawl_delay(UA) or 0))
            rate = rule.request_rate(UA)
            if rate and rate.requests:
                delay = max(delay, rate.seconds / rate.requests)
        if delay > 15:
            fail("Source requires a longer crawl delay; use a permitted manual route")
        remaining = delay - (time.monotonic() - self.last_fetch.get(host, 0))
        if remaining > 0:
            time.sleep(remaining)

    def fetch(self, url: str, max_bytes: int, hosts: set[str], *, check_robots: bool = True,
              deadline_seconds: float = 30) -> tuple[int, str, dict, bytes]:
        hosts = {h.lower().rstrip(".") for h in hosts}
        deadline = time.monotonic() + deadline_seconds
        current = url
        for _ in range(5):
            p, host, port = valid_url(current)
            if host not in hosts:
                fail(f"Host not in the explicit allowed-host list: {host}")
            if check_robots:
                self.robot_check(current, hosts)
            ips = public_addresses(host, port)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                fail("Fetch deadline exceeded")
            klass = PinnedHTTPS if p.scheme == "https" else PinnedHTTP
            conn = klass(host, ips[0], port, min(15.0, remaining))
            path = quote(p.path or "/", safe="/%:@!$&'()*+,;=-._~")
            if p.query:
                path += "?" + quote(p.query, safe="/%?:@!$&'()*+,;=-._~[]")
            try:
                conn.request("GET", path, headers={"User-Agent": UA, "Accept-Encoding": "identity", "Accept": "*/*"})
                self.last_fetch[host] = time.monotonic()
                response = conn.getresponse()
                headers = {k.lower(): v for k, v in response.getheaders()}
                if response.status in {301, 302, 303, 307, 308}:
                    location = headers.get("location")
                    if not location:
                        fail("Redirect without location")
                    destination = urljoin(current, location)
                    if p.scheme == "https" and urlsplit(destination).scheme != "https":
                        fail("HTTPS downgrade blocked")
                    current = destination
                    continue
                encoding = headers.get("content-encoding", "identity").lower()
                if encoding not in {"", "identity"}:
                    fail("Compressed transport not accepted by this bounded fetcher")
                length = headers.get("content-length")
                if length and int(length) > max_bytes:
                    fail("Response exceeds byte limit")
                chunks, total = [], 0
                while True:
                    if time.monotonic() >= deadline:
                        fail("Fetch deadline exceeded")
                    chunk = response.read(min(65536, max_bytes - total + 1))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > max_bytes:
                        fail("Response exceeds byte limit")
                    chunks.append(chunk)
                return response.status, current, headers, b"".join(chunks)
            finally:
                conn.close()
        fail("Redirect limit exceeded")

class PageParser(HTMLParser):
    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base, self.title, self.text = base, [], []
        self.images, self.links, self.meta, self.jsonld = [], [], [], []
        self._title = False
        self._skip = 0
        self._json_buffer = None
        self._figures = []
        self._link = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in {"script", "style", "noscript"}:
            self._skip += 1
            if tag == "script" and a.get("type", "").lower() == "application/ld+json":
                self._json_buffer = []
        if tag == "title": self._title = True
        if tag == "meta" and len(self.meta) < 100:
            self.meta.append({k: v for k, v in a.items() if k in {"name", "property", "content", "charset"}})
        if tag == "figure": self._figures.append({"text": [], "indices": []})
        if tag == "a" and a.get("href"):
            self._link = {"url": urljoin(self.base, a["href"]), "text": []}
        if tag in {"img", "source"} and len(self.images) < 150:
            urls = []
            for key in ["src", "data-src", "data-original", "data-lazy-src"]:
                if a.get(key): urls.append(a[key])
            for key in ["srcset", "data-srcset"]:
                for part in (a.get(key) or "").split(","):
                    if part.strip(): urls.append(part.strip().split()[0])
            urls = list(dict.fromkeys(urljoin(self.base, u) for u in urls if not u.startswith(("data:", "blob:"))))
            if urls:
                record = {"candidate_urls": urls, "alt": a.get("alt", ""), "title": a.get("title", ""), "figure_text": ""}
                self.images.append(record)
                for figure in self._figures: figure["indices"].append(len(self.images)-1)

    def handle_endtag(self, tag):
        if tag == "title": self._title = False
        if tag in {"script", "style", "noscript"}:
            if tag == "script" and self._json_buffer is not None:
                try:
                    self.jsonld.append(json.loads("".join(self._json_buffer)))
                except (ValueError, RecursionError):
                    pass
                self._json_buffer = None
            self._skip = max(0, self._skip-1)
        if tag == "figure" and self._figures:
            f = self._figures.pop()
            for i in f["indices"]: self.images[i]["figure_text"] = " ".join(f["text"])[:1500]
        if tag == "a" and self._link:
            if len(self.links) < 150:
                self.links.append({"url": self._link["url"], "text": " ".join(self._link["text"])[:200]})
            self._link = None

    def handle_data(self, data):
        if self._json_buffer is not None: self._json_buffer.append(data)
        if self._skip: return
        t = " ".join(data.split())
        if not t: return
        if self._title: self.title.append(t)
        self.text.append(t)
        if self._link: self._link["text"].append(t)
        for f in self._figures: f["text"].append(t)

    def output(self) -> dict:
        return {"title": " ".join(self.title), "metadata": self.meta, "image_candidates": self.images,
                "links": self.links, "json_ld": self.jsonld[:20], "text_excerpt": " ".join(self.text)[:12000],
                "warning": "UNTRUSTED source data. Candidate URLs/nearby text are not verified photo identity, dates or licences."}


def parse_crawl4ai_image_results(source_html: str) -> list[dict]:
    html_source = source_html or ""
    starts = []
    for match in re.finditer(r"<div\b[^>]*class=[\"'][^\"']*[\"'][^>]*>", html_source, re.I | re.S):
        class_match = re.search(r"\bclass\s*=\s*([\"'])(.*?)\1", match.group(0), re.I | re.S)
        classes = set((class_match.group(2) if class_match else "").split())
        if {"gsc-imageResult", "gsc-result"}.issubset(classes):
            starts.append(match)
    results = []

    def attribute(tag: str, name: str) -> str:
        match = re.search(rf"\b{re.escape(name)}\s*=\s*([\"'])(.*?)\1", tag, re.I | re.S)
        return html.unescape(match.group(2)) if match else ""

    def inner_text(value: str) -> str:
        return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", value or "")).split())

    for index, match in enumerate(starts):
        chunk = html_source[match.start():starts[index + 1].start() if index + 1 < len(starts) else len(html_source)]
        link_match = re.search(r"<a\b(?=[^>]*\bclass=[\"'][^\"']*\bgs-previewLink\b)(?=[^>]*\bhref=)[^>]*>", chunk, re.I | re.S)
        image_match = re.search(r"<img\b(?=[^>]*\bclass=[\"'][^\"']*\bgs-image\b)[^>]*>", chunk, re.I | re.S)
        if not link_match or not image_match:
            continue
        title_match = re.search(r"<[^>]+class=[\"'][^\"']*\bgs-previewTitle\b[^\"']*[\"'][^>]*>(.*?)</", chunk, re.I | re.S)
        description_match = re.search(r"<[^>]+class=[\"'][^\"']*\bgs-previewDescription\b[^\"']*[\"'][^>]*>(.*?)</", chunk, re.I | re.S)
        title = inner_text(title_match.group(1) if title_match else "")
        description = inner_text(description_match.group(1) if description_match else "")
        alt = attribute(image_match.group(0), "alt") or attribute(image_match.group(0), "title")
        result = {"source_url": attribute(link_match.group(0), "href"),
                  "preview_url": attribute(image_match.group(0), "src"), "title": title,
                  "description": description, "alt": alt,
                  "width": attribute(image_match.group(0), "width") or None,
                  "height": attribute(image_match.group(0), "height") or None}
        result["text"] = " ".join(value for value in (title, description, alt) if value)
        if result["source_url"] and result["preview_url"]:
            results.append(result)
    return results


def _crawl4ai_place_groups(place: str) -> list[list[str]]:
    """Verified landmark aliases require their geographic anchor as well.

    Chengde Mountain Resort: https://whc.unesco.org/en/list/703/
    Summer Palace in Beijing is a different site: /en/list/880/.
    """
    parts = [part.strip() for part in re.split(r"[/|,，、]", place) if part.strip()]
    if not parts:
        return []
    target = parts[0]
    chengde = bool(re.search(r"\bchengde\b|承德", place, re.I))
    if chengde and re.search(r"离宫|避暑山庄|\bmountain resort\b|\bsummer palace\b|\bbishu shanzhuang\b", target, re.I):
        return [list(dict.fromkeys([target, "离宫", "避暑山庄", "Mountain Resort", "summer palace", "Bishu Shanzhuang"])),
                ["承德", "Chengde"]]
    if re.fullmatch(r"(?:河北(?:省)?\s*)?承德(?:市)?|Chengde", target, re.I):
        return [list(dict.fromkeys([target, "Chengde", "承德"]))]
    # Keep a parent locality as a separate required search term, never an
    # alternative to the actual landmark or neighbourhood being requested.
    return [[target]] + ([[parts[1]]] if len(parts) > 1 else [])


def _crawl4ai_place_query(place: str) -> str:
    return " ".join("(" + " OR ".join('"' + term.replace('"', ' ').strip() + '"'
                                          for term in group) + ")"
                    for group in _crawl4ai_place_groups(place))


def _crawl4ai_place_terms(place: str) -> list[str]:
    return list(dict.fromkeys(term for group in _crawl4ai_place_groups(place) for term in group))


def _crawl4ai_location_matches(text: str, place: str) -> bool:
    haystack = _text(text).casefold()
    groups = _crawl4ai_place_groups(place)
    # Only the verified alias group requires both site and city evidence.
    required = groups if len(groups) > 1 and "Mountain Resort" in groups[0] else groups[:1]
    def matches(term):
        pattern = re.escape(term.casefold())
        if term.isascii():
            pattern = r"(?<!\w)" + pattern + r"(?!\w)"
        return bool(re.search(pattern, haystack))
    return bool(required) and all(any(matches(term) for term in group) for group in required)


def _crawl4ai_years(text: str) -> list[int]:
    return [int(value) for value in re.findall(r"(?<!\d)((?:18|19|20)\d{2})(?!\d)", text or "")]


def _crawl4ai_scene_date(text: str, temporal: dict) -> dict | None:
    """Return a supported source assertion without treating upload dates as scene dates."""
    bounds = None
    if temporal.get("mode") == "historical_range":
        bounds = (date.fromisoformat(temporal["start"]).year, date.fromisoformat(temporal["end"]).year)
    years = _crawl4ai_years(text)
    if bounds:
        matching = [year for year in years if bounds[0] <= year <= bounds[1]]
        if matching:
            year = matching[0]
            return {"start": f"{year:04d}-01-01", "end": f"{year:04d}-12-31", "precision": "year",
                    "basis": "source_caption", "conflicting": False}
        if re.search(fr"\b{bounds[0]}s\b", text or "", re.I) or (
                bounds == (1980, 1989) and re.search(r"(?:上世纪|20世纪)?\s*(?:80|八十)年代", text or "", re.I)):
            return {"start": f"{bounds[0]:04d}-01-01", "end": f"{bounds[1]:04d}-12-31", "precision": "decade",
                    "basis": "source_caption", "conflicting": False}
    return None


def _crawl4ai_image_url(value: str) -> str | None:
    if not isinstance(value, str) or not value or value.startswith(("data:", "blob:")):
        return None
    try:
        p, host, _ = valid_url(value)
    except ResearchError:
        return None
    blocked_hosts = {"encrypted-tbn0.gstatic.com", "sync.intentiq.com", "www.google-analytics.com", "pixel.mathtag.com", "mixern.sina.cn"}
    blocked_path = re.search(r"profiles_engine|pixel|tracking|spacer|favicon|sprite|btn_|cancel|vote|service/buzz|auto/crop|(?:^|/)(?:default|mfp|view)(?:/|$)", p.path, re.I)
    if host in blocked_hosts or blocked_path:
        return None
    # A few public archives still emit HTTP image URLs from an HTTPS article
    # (for example Sina's k.sinaimg.cn CDN).  Keep the exact observed host/path
    # and upgrade only the scheme so the reference remains renderable in the
    # app's HTTPS-only image surface.  We never invent a path or follow a
    # redirect here; the source-page crawl supplied this URL verbatim.
    scheme = "https" if p.scheme == "http" else p.scheme
    return urlunsplit((scheme, p.netloc, p.path, p.query, ""))


def _crawl4ai_load_dotenv() -> None:
    """Load only missing, simple KEY=VALUE entries for local skill invocation."""
    roots = [Path.cwd(), Path(__file__).resolve().parents[3]]
    for root in dict.fromkeys(roots):
        path = root / ".env"
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip("\"'")
            if re.fullmatch(r"[A-Z][A-Z0-9_]{1,80}", key) and key not in os.environ:
                os.environ[key] = value
        return


def _crawl4ai_search_url(search_url: str | None, request: dict) -> str:
    _crawl4ai_load_dotenv()
    search_url = search_url or _configured_env("GOOGLE_CSE_URL")
    if not search_url:
        cx = _configured_env("GOOGLE_CSE_ID")
        if cx:
            search_url = f"https://cse.google.com/cse?cx={quote(cx, safe='')}"
    if not search_url:
        fail("Crawl4AI search requires --search-url or GOOGLE_CSE_ID")
    parsed = urlsplit(search_url)
    if parsed.scheme != "https" or parsed.hostname not in {"cse.google.com", "www.google.com"}:
        fail("Crawl4AI search URL must be a public Google Programmable Search page")
    params = parse_qs(parsed.query, keep_blank_values=True)
    if not params.get("cx", [""])[0]:
        fail("Crawl4AI search URL must include a Programmable Search cx")
    temporal = request["temporal"]
    place_query = _crawl4ai_place_query(request["place"])
    terms = [place_query, "老照片"]
    if temporal.get("mode") == "historical_range":
        start, end = date.fromisoformat(temporal["start"]).year, date.fromisoformat(temporal["end"]).year
        terms.insert(1, f"{start}年代" if start % 10 == 0 else f"{start}-{end}")
    query = " ".join(" ".join(str(term).split()) for term in terms if term)
    params["q"] = [query]
    params.pop("start", None)
    params.pop("page", None)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/cse", urlencode(params, doseq=True), ""))


def _crawl4ai_search_js(page_number: int) -> str:
    if page_number == 1:
        return """const deadline=Date.now()+12000;
const blocked=()=>/please verify that you are not a robot|unusual traffic from your computer network/i.test(document.body?.innerText||'');
while(Date.now()<deadline){
 if(blocked()) return {blocked:true};
 const tabs=[...document.querySelectorAll('.gsc-tabHeader')];
 const image=tabs.find(el=>/图片|image/i.test(el.textContent||''))||tabs[1];
 if(image){
  if(!image.classList.contains('gsc-tabhActive')) image.click();
  while(Date.now()<deadline && !document.querySelector('.gsc-results.gsc-imageResult .gsc-imageResult.gsc-result')){
   if(blocked()) return {blocked:true};
   await new Promise(r=>setTimeout(r,250));
  }
  return {clicked:true,results:document.querySelectorAll('.gsc-results.gsc-imageResult .gsc-imageResult.gsc-result').length};
 }
 await new Promise(r=>setTimeout(r,250));
}
return {clicked:false};"""
    return f"""const deadline=Date.now()+12000;
const roots=[...document.querySelectorAll('.gsc-results.gsc-imageResult')];
const root=roots.find(el=>el.offsetParent!==null)||roots.at(-1);
while(Date.now()<deadline){{
 const pages=[...(root?.querySelectorAll('.gsc-cursor-page')||[])];
 const target=pages.find(el=>el.textContent.trim()==='{page_number}'&&!el.classList.contains('gsc-cursor-current-page'));
 if(target){{
  target.click();
  while(Date.now()<deadline){{
   const current=root?.querySelector('.gsc-cursor-current-page');
   if(current&&current.textContent.trim()==='{page_number}'&&root.querySelectorAll('.gsc-imageResult.gsc-result').length)
    return {{page:{page_number},results:root.querySelectorAll('.gsc-imageResult.gsc-result').length}};
   await new Promise(r=>setTimeout(r,250));
  }}
  return {{page:{page_number},timeout:true}};
 }}
 await new Promise(r=>setTimeout(r,250));
}}
return {{page:{page_number},found:false}};"""


def _crawl4ai_run(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError as error:
        if "event loop" in str(error).lower():
            fail("Crawl4AI CLI must run outside an active asyncio event loop")
        raise


def _crawl4ai_search_pages(search_url: str, max_pages: int, before_page=None) -> list[dict]:
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    except ImportError:
        fail("Crawl4AI is required for this command. Install the optional crawl4ai dependency and run crawl4ai-setup.")

    async def collect():
        cards = []
        session_id = "place-photo-search-" + hashlib.sha256(f"{search_url}-{time.time_ns()}".encode()).hexdigest()[:16]
        async with AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=False)) as crawler:
            for page_number in range(1, max_pages + 1):
                if before_page:
                    before_page(page_number, search_url)
                config = CrawlerRunConfig(
                    cache_mode=CacheMode.BYPASS, page_timeout=CRAWL4AI_PAGE_TIMEOUT_MS,
                    delay_before_return_html=0.5, js_code=[_crawl4ai_search_js(page_number)],
                    session_id=session_id, js_only=page_number > 1,
                    # The user supplied this Programmable Search page explicitly. Google’s
                    # widget robots policy blocks browser rendering even though the same page
                    # is available interactively; source pages still use robots checks below.
                    check_robots_txt=False, verbose=False,
                )
                result = await crawler.arun(url=search_url, config=config)
                if not result.success:
                    if page_number == 1:
                        fail(f"Crawl4AI search failed: {result.error_message or result.status_code}")
                    break
                page_cards = parse_crawl4ai_image_results(result.html or "")
                for card in page_cards:
                    card["search_page"] = page_number
                cards.extend(page_cards)
                if not page_cards:
                    break
        return cards

    return _crawl4ai_run(collect())


def _crawl4ai_source_page(source_url: str) -> dict:
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
    except ImportError:
        fail("Crawl4AI is required for this command. Install the optional crawl4ai dependency and run crawl4ai-setup.")
    try:
        _, host, port = valid_url(source_url)
        public_addresses(host, port)
    except ResearchError:
        raise

    async def fetch():
        config = CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS, page_timeout=CRAWL4AI_PAGE_TIMEOUT_MS,
            wait_for="css:body", scan_full_page=True, scroll_delay=0.35, max_scroll_steps=24,
            delay_before_return_html=0.5, check_robots_txt=True, verbose=False,
        )
        async with AsyncWebCrawler(config=BrowserConfig(headless=True, verbose=False)) as crawler:
            result = await crawler.arun(url=source_url, config=config)
            if not result.success:
                fail(f"Crawl4AI source page failed: {result.error_message or result.status_code}")
            media = (result.media or {}).get("images", []) if isinstance(result.media, dict) else []
            return {"url": source_url, "html": result.html or "", "markdown": result.markdown or "",
                    "media": media, "status_code": result.status_code}

    return _crawl4ai_run(fetch())


def _crawl4ai_source_images(page: dict, card: dict, request: dict) -> list[dict]:
    source_url = page["url"]
    parsed = PageParser(source_url)
    parsed.feed(page.get("html", ""))
    page_record = parsed.output()
    page_title = page_record.get("title", "") or page.get("title", "")
    page_excerpt = page_record.get("text_excerpt", "") or page.get("text", "")
    identity_text = " ".join([page_title, page_excerpt[:2000]])
    if not _crawl4ai_location_matches(identity_text, request["place"]):
        return []
    if _crawl4ai_scene_date(identity_text, request["temporal"]) is None:
        return []
    page_text = " ".join([identity_text, page.get("markdown", ""), card.get("text", "")])
    if NON_PHOTO.search(page_text) and not re.search(r"照片|photo|photograph", page_text, re.I):
        return []
    if not _crawl4ai_location_matches(page_text, request["place"]):
        return []
    source_date = _crawl4ai_scene_date(page_text, request["temporal"])
    if source_date is None:
        return []
    media = page.get("media") if isinstance(page.get("media"), list) else []
    image_records = []
    for item in media:
        if not isinstance(item, dict):
            continue
        image_records.append({"url": item.get("src") or item.get("url"), "alt": item.get("alt", ""),
                              "description": item.get("desc", ""), "width": item.get("width"), "height": item.get("height", "")})
    for item in page_record.get("image_candidates", []):
        for image_url in item.get("candidate_urls", []):
            image_records.append({"url": image_url, "alt": item.get("alt", ""),
                                  "description": item.get("figure_text", ""), "width": None, "height": None})
    unique, seen = [], set()
    for image in image_records:
        observed_url = image.get("url")
        if isinstance(observed_url, str) and observed_url.startswith("//"):
            observed_url = urljoin(source_url, observed_url)
        image_url = _crawl4ai_image_url(observed_url)
        if not image_url or image_url in seen:
            continue
        seen.add(image_url)
        image_text = " ".join([str(image.get("alt", "")), str(image.get("description", "")),
                                card.get("title", ""), page_title])
        image_alt = _text(image.get("alt"))
        image_description = _text(image.get("description"))
        if image_alt and not (
                _crawl4ai_location_matches(image_alt, request["place"])
                or _crawl4ai_scene_date(image_alt, request["temporal"])):
            continue
        if not image_alt and image_description and not (
                _crawl4ai_location_matches(image_description, request["place"])
                or _crawl4ai_scene_date(image_description, request["temporal"])):
            # Related-video cards and recommendation thumbnails often appear in
            # Crawl4AI's media inventory. Keep them out even when the article
            # itself is a valid historical source.
            continue
        if NON_PHOTO.search(image_text):
            continue
        scene_date = _crawl4ai_scene_date(image_text, request["temporal"]) or source_date
        if scene_date is None:
            continue
        title = _text(image.get("alt")) or _text(image.get("description")) or _text(card.get("title")) or page_title or "Historical photo reference"
        unique.append({"image_url": image_url, "observed_image_url": observed_url,
                       "title": title[:1000], "scene_date": scene_date,
                       "source_excerpt": _text(image_text)[:1200]})
    return unique


def _crawl4ai_evidence_id(source_url: str, image_url: str, kind: str) -> str:
    return "c4a-" + hashlib.sha256(f"{source_url}\n{image_url}\n{kind}".encode()).hexdigest()[:24]


def llm_search(place: str, temporal: dict, *, timeout: float = 30) -> dict:
    """Require observable native search execution before accepting public leads."""
    _crawl4ai_load_dotenv()
    if _configured_env("MEMORY_SPARK_PHOTO_WEB_SEARCH").lower() not in {"1", "true", "yes"}:
        fail("llm_search_disabled")
    base = _configured_env("MEMORY_SPARK_LLM_BASE_URL").rstrip("/")
    model = _configured_env("MEMORY_SPARK_LLM_MODEL")
    key = _configured_env("MEMORY_SPARK_LLM_API_KEY")
    if not base or not model or not key:
        fail("llm_search_not_configured")
    endpoint = urlsplit(base)
    if (endpoint.scheme not in {"http", "https"} or not endpoint.hostname
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
        fail("llm_search_invalid_endpoint")
    window = (f'{temporal["start"]} through {temporal["end"]}'
              if temporal.get("start") else "historical photographs; capture period unspecified")
    prompt = ("Search for original public photograph pages and archive albums for the place "
              + json.dumps(place, ensure_ascii=False) + ". Requested scene capture period: " + window
              + ". Cite original source pages. Webpage publication and upload dates are not capture dates.")
    body = {"model": model, "input": prompt, "tools": [{"type": "web_search"}],
            "tool_choice": "required", "include": ["web_search_call.action.sources"],
            "max_tool_calls": 1, "max_output_tokens": 1024, "store": False}
    req = http_request.Request(base + "/responses", data=json.dumps(body).encode(),
                               headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    try:
        with http_request.urlopen(req, timeout=timeout) as response:
            raw = response.read(MAX_PAGE_BYTES + 1)
        if len(raw) > MAX_PAGE_BYTES:
            fail("llm_search_response_limit")
        data = json.loads(raw)
    except HTTPError as error:
        fail(f"llm_search_http_{error.code}")
    except http.client.HTTPException:
        fail("llm_search_network_error")
    except (TimeoutError, socket.timeout):
        fail("llm_search_timeout")
    except (URLError, OSError):
        fail("llm_search_network_error")
    except ValueError:
        fail("llm_search_invalid_response")
    if not isinstance(data, dict) or not isinstance(data.get("output"), list):
        fail("llm_search_invalid_response")
    def valid_receipt(value):
        return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value) and key not in value
    if not valid_receipt(data.get("id")):
        fail("llm_search_invalid_response")
    calls = [item for item in data["output"] if isinstance(item, dict)
             and item.get("type") == "web_search_call" and item.get("status") == "completed"
             and valid_receipt(item.get("id"))]
    if not calls:
        fail("llm_search_no_search_evidence")
    annotations = []
    for item in data["output"]:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content in item.get("content", []) if isinstance(item.get("content"), list) else []:
            if isinstance(content, dict) and isinstance(content.get("annotations"), list):
                annotations.extend(row for row in content["annotations"] if isinstance(row, dict)
                                   and row.get("type") == "url_citation")
    sources = []
    for call in calls:
        action = call.get("action")
        returned = action.get("sources", []) if isinstance(action, dict) else []
        returned = returned if isinstance(returned, list) else []
        for source in returned + (annotations if call is calls[0] else []):
            if not isinstance(source, dict):
                continue
            url = source.get("url")
            try:
                parsed, _, _ = valid_url(url)
                if any(re.search(r"key|token|secret|signature|password|credential", name, re.I)
                       for name in parse_qs(parsed.query)) or key in url:
                    continue
                public_addresses(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
            except (ResearchError, ValueError, TypeError):
                continue
            if any(row["source_url"] == url for row in sources):
                continue
            sources.append({"provider": "llm_web_search", "source_url": url,
                            "response_id": str(data.get("id", ""))[:200],
                            "tool_call_id": str(call["id"])[:200], "observed_at": utcnow()})
    if not sources:
        fail("llm_search_no_source_evidence")
    return {"provider": "llm_web_search", "status": "success", "sources": sources[:24]}


_LLM_UNCERTAIN_DATE = re.compile(
    r"\b(?:probably|possibly|perhaps|maybe|likely|about|estimated|estimate|approximately|approx|circa|"
    r"before|after|uncertain|unknown|undated|unrecorded|around)\b|\b(?:ca|c)\.\s*\d|"
    r"\b(?:not|never)\s+(?:known|recorded|dated|established|verified)\b|"
    r"\b(?:no|missing)\s+(?:capture\s+)?date\b|[?？]|约|可能|不详|未知", re.I)
_LLM_DATE_EVENT = re.compile(
    r"(?P<noncapture>\b(?:publish(?:ed|ing)?|publication|upload(?:ed|ing)?|scan(?:ned|ning)?|"
    r"digitiz(?:ed|ation|ing)|digitis(?:ed|ation|ing))\b|上传|发表|出版|扫描|数字化)"
    r"|(?P<capture>\b(?:taken|captured|capture|photographed|shot|scene\s+date|date\s+taken)\b|拍摄|摄于|拍于)", re.I)


def _llm_capture_clauses(value: str) -> list[str]:
    """Keep capture clauses while excluding explicitly different date events.

    Event scope lasts until a separator or a different event. Qualifiers remain
    with their capture assertion, including qualifiers preceding 'taken'. The
    unchanged original field is retained separately in source provenance.
    """
    captures = []
    for clause in re.split(r"[;；\n]", value):
        capture, start = True, 0
        for match in _LLM_DATE_EVENT.finditer(clause):
            next_capture = match.lastgroup == "capture"
            if next_capture == capture:
                continue
            if capture:
                captures.append(clause[start:match.start()])
            start, capture = match.start(), next_capture
            if capture:
                # In 'published 2025, probably taken 1983', the uncertainty
                # belongs to the new capture assertion, not the publication.
                qualifier = re.search(r"\b(probably|possibly|perhaps|maybe|likely|about|approximately|circa)\s*$",
                                      clause[:start], re.I)
                if qualifier:
                    start = qualifier.start()
        if capture:
            captures.append(clause[start:])
    return captures


def _llm_capture_date(value: str, temporal: dict) -> dict | None:
    value = _text(value)
    if _LLM_UNCERTAIN_DATE.search(value):
        return None
    years = list(dict.fromkeys(_crawl4ai_years(value)))
    try:
        for token in re.findall(r"(?<!\d)\d{4}[-/][\w/-]+", value):
            if not (re.fullmatch(r"\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?(?:T\d{2})?", token)
                    or re.fullmatch(r"(?:18|19|20)\d{2}-(?:18|19|20)\d{2}", token)):
                return None
        # Normalize explicit numeric precision, including non-zero-padded
        # source dates. Never degrade an unparsed precise date to a year.
        days = list(dict.fromkeys(date(*map(int, parts)).isoformat() for parts in
            re.findall(r"(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)", value)))
        months = list(dict.fromkeys(date(int(y), int(m), 1).isoformat()[:7] for y, m in
            re.findall(r"(?<!\d)(\d{4})[-/](\d{1,2})(?!\d)", value)))
        if len(days) > 1 or len(months) > 1:
            return None
        # Unsupported numeric/named-month dates are not ordinary year captions.
        if re.search(r"(?<!\d)\d{1,2}[-/]\d{1,2}[-/]\d{4}(?!\d)|"
                     r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
                     r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b",
                     value, re.I):
            return None
        year_range = re.search(r"(?<!\d)((?:18|19|20)\d{2})\s*[-–—]\s*((?:18|19|20)\d{2})(?!\d)", value)
        if year_range:
            range_years = [int(year_range.group(1)), int(year_range.group(2))]
            if len(years) != 2 or set(years) != set(range_years):
                return None
            start, end, precision = f"{range_years[0]}-01-01", f"{range_years[1]}-12-31", "range"
        elif len(days) == 1:
            captured = date.fromisoformat(days[0])
            if any(year != captured.year for year in years):
                return None
            start = end = captured.isoformat()
            precision = "day"
        elif len(months) == 1:
            captured = date.fromisoformat(months[0] + "-01")
            if any(year != captured.year for year in years):
                return None
            start = captured.isoformat()
            end = captured.replace(day=calendar.monthrange(captured.year, captured.month)[1]).isoformat()
            precision = "month"
        elif len(years) == 1:
            year = years[0]
            decade = bool(re.search(rf"{year}(?:s|年代)", value, re.I))
            start, end = f"{year}-01-01", f"{year + 9 if decade else year}-12-31"
            precision = "decade" if decade else "year"
        else:
            return None
    except ValueError:
        return None
    if start > end:
        return None
    if temporal.get("mode") != "historical_unspecified" and (
            not temporal.get("start") or not temporal["start"] <= start <= end <= temporal["end"]):
        return None
    return {"start": start, "end": end, "precision": precision,
            "basis": "source_caption", "conflicting": False}


def _llm_reconcile_capture_dates(field_records: list[dict[str, str]], temporal: dict) -> dict | None:
    """Reconcile every field/record for an image before applying the window."""
    assertions = []
    for record, fields in enumerate(field_records):
        for field, value in fields.items():
            if field in {"datePublished", "uploadDate"}:
                continue
            explicit_date = field in {"dateTaken", "dateCreated"}
            field_assertions = []
            for clause in _llm_capture_clauses(value):
                has_year = bool(_crawl4ai_years(clause))
                has_date_context = bool(re.search(r"\b(?:date|taken|capture|captured|undated)\b|拍摄|摄于|拍于", clause, re.I))
                if _LLM_UNCERTAIN_DATE.search(clause) and (has_year or has_date_context or explicit_date):
                    return None
                if not has_year:
                    continue
                parsed = _llm_capture_date(clause, {"mode": "historical_unspecified"})
                if not parsed:
                    return None
                field_assertions.append({"record": record, "field": field, "value": value,
                                         "clause": clause.strip(), **parsed})
            if explicit_date and not field_assertions:
                return None
            assertions.extend(field_assertions)
    if not assertions:
        return None
    start = max(assertion["start"] for assertion in assertions)
    end = min(assertion["end"] for assertion in assertions)
    if start > end:
        return None
    if temporal.get("mode") != "historical_unspecified" and (
            not temporal.get("start") or not temporal["start"] <= start <= end <= temporal["end"]):
        return None
    precision = next((assertion["precision"] for assertion in assertions
                      if assertion["start"] == start and assertion["end"] == end), "range")
    return {"start": start, "end": end, "precision": precision,
            "basis": "source_caption", "conflicting": False, "assertions": assertions}


def llm_source_photos(source_url: str, place: str, temporal: dict, *, timeout: float = 30) -> list[dict]:
    """Inspect public source metadata; the model's prose is never photo evidence."""
    _, host, port = valid_url(source_url)
    public_addresses(host, port)
    status, final, headers, body = Fetcher().fetch(source_url, MAX_PAGE_BYTES, {host}, deadline_seconds=timeout)
    if status != 200 or headers.get("content-type", "").split(";", 1)[0] not in {"text/html", "application/xhtml+xml"}:
        fail("llm_source_unavailable")
    parser = PageParser(final)
    parser.feed(body.decode("utf-8", errors="replace"))
    page = parser.output()
    records = []
    for node in page["json_ld"]:
        nodes = node if isinstance(node, list) else [node]
        for item in nodes:
            if isinstance(item, dict):
                graph = item.get("@graph", [item])
                if isinstance(graph, dict):
                    graph = [graph]
                if isinstance(graph, list):
                    records.extend(graph)
    for item in page["image_candidates"]:
        caption = " ".join((item["alt"], item["figure_text"]))
        records.extend({"@type": "Photograph", "caption": caption, "dateCreated": caption,
                        "contentUrl": url, "caption_record": True} for url in item["candidate_urls"][:1])
    grouped = {}
    for item in records:
        if not isinstance(item, dict):
            continue
        kinds = item.get("@type")
        kinds = kinds if isinstance(kinds, list) else [kinds]
        if not any(kind in ("Photograph", "ImageObject") for kind in kinds):
            continue
        fields = {key: _text(item.get(key)) for key in
                  ("name", "caption", "description", "dateTaken", "dateCreated", "datePublished", "uploadDate")
                  if _text(item.get(key))}
        image = _crawl4ai_image_url(item.get("contentUrl"))
        if image:
            grouped.setdefault(image, []).append((fields, item.get("caption_record", False)))
    images = []
    for image, entries in grouped.items():
        caption = " ".join(fields[key] for fields, _ in entries
                           for key in ("name", "caption", "description") if key in fields)
        if NON_PHOTO.search(caption) or not _crawl4ai_location_matches(caption, place):
            continue
        if any(re.search(r"key|token|secret|signature|password|credential", name, re.I)
               for name in parse_qs(urlsplit(image).query)):
            continue
        scene = _llm_reconcile_capture_dates([fields for fields, _ in entries], temporal)
        if not scene:
            continue
        if any(not is_caption and fields.keys() & {"dateTaken", "dateCreated"}
               for fields, is_caption in entries):
            scene["basis"] = "provider_date_taken"
        _, image_host, image_port = valid_url(image)
        public_addresses(image_host, image_port)
        excerpt = "; ".join(f"{key}: {value}" for fields, _ in entries for key, value in fields.items())
        if len(excerpt) > 4000:
            # Do not truncate away a conflicting assertion or poison sibling
            # results with an evidence record exceeding the persisted schema.
            continue
        images.append({"image_url": image, "title": caption, "source_page_url": final,
                       "scene_date": scene, "source_excerpt": excerpt})
    return images


def llm_discover(run: Path, *, source_limit: int = 24, provider_timeout: float = 30, cache_ttl: int = 86400) -> dict:
    if not 1 <= source_limit <= 24 or not 1 <= provider_timeout <= 120 or not 0 <= cache_ttl <= 86400:
        fail("llm_search_invalid_limits")
    run = run.resolve()
    request, candidates, evidence = load_records(run)
    def qualifying_count():
        verified = set()
        for candidate in candidates:
            reasons = evaluate(candidate, request, evidence)["reason_codes"]
            if not any(reason.startswith(("DATE_", "PLACE_", "AUTHENTICITY_", "NO_DIRECT_IMAGE")) for reason in reasons):
                verified.add(candidate.get("image_url"))
        return len(verified)
    _crawl4ai_load_dotenv()
    if _configured_env("MEMORY_SPARK_PHOTO_WEB_SEARCH").lower() not in {"1", "true", "yes"}:
        fail("llm_search_disabled")
    cache_key = hashlib.sha256(json.dumps({"schema": 1, "place": request["place"], "temporal": request["temporal"],
        "endpoint": _configured_env("MEMORY_SPARK_LLM_BASE_URL"), "model": _configured_env("MEMORY_SPARK_LLM_MODEL")},
        sort_keys=True).encode()).hexdigest()
    cache_path = checked_path(run, "search-cache/" + cache_key + ".json")
    retrieval = None
    if cache_path.is_file():
        try:
            cached = read_json(cache_path)
            if 0 <= time.time() - cached["saved_at"] < cache_ttl:
                retrieval = cached["discovery"]
        except (ValueError, KeyError, TypeError, OSError):
            pass
    cache = "hit" if retrieval is not None else "miss"
    if retrieval is None:
        log_event(run, "search", "LLM public place-photo web search", [])
        retrieval = llm_search(request["place"], request["temporal"], timeout=provider_timeout)
        write_json(cache_path, {"saved_at": time.time(), "discovery": retrieval})
    write_json(checked_path(run, "discovery.json"), {**retrieval, "cache": cache})
    source_failures, budget_exhausted = [], False
    for origin in retrieval["sources"][:source_limit]:
        if qualifying_count() >= request["count"] or len(candidates) >= 100:
            break
        source = origin["source_url"]
        try:
            log_event(run, "page", "LLM search source inspection", [source])
        except ResearchError:
            budget_exhausted = True
            break
        try:
            images = llm_source_photos(source, request["place"], request["temporal"], timeout=provider_timeout)
        except (ResearchError, OSError, ValueError, http.client.HTTPException):
            log_event(run, "note", "LLM source unavailable", [source])
            source_failures.append({"source_url": source, "reason": "source_unavailable"})
            continue
        for image in images:
            if qualifying_count() >= request["count"] or len(candidates) >= 100:
                break
            if any(candidate.get("image_url") == image["image_url"] for candidate in candidates):
                continue
            identifier = "llm-" + hashlib.sha256(image["image_url"].encode()).hexdigest()[:24]
            ids = []
            for kind, excerpt in (("place", image["source_excerpt"]), ("scene_date", image["source_excerpt"]),
                                  ("access_terms", "Public source inspected with robots-aware access checks.")):
                eid = identifier + "-" + kind
                evidence[eid] = {"id": eid, "kind": kind, "url": image["source_page_url"],
                                 "locator": "Image-specific source metadata", "excerpt": excerpt,
                                 "observed_at": utcnow()}
                ids.append(eid)
            candidates.append({"id": identifier, "title": image["title"],
                "source_page_url": image["source_page_url"], "image_url": image["image_url"],
                "authenticity": "source_described_photograph", "memory_reference_only": True,
                "providers": ["llm_web_search"], "discovery_origins": [origin],
                "place": {"label": request["place"], "match": "exact", "evidence_ids": [ids[0]]},
                "scene_date": {**image["scene_date"], "evidence_ids": [ids[1]]},
                "rights": {"license_id": "unknown", "scope": "unknown", "download_permitted": None,
                           "commercial_use_permitted": None, "evidence_ids": []},
                "acquisition": {"access_permitted": True, "allowed_hosts": sorted({host for host in
                    (urlsplit(image["image_url"]).hostname, urlsplit(image["source_page_url"]).hostname)}),
                    "evidence_ids": [ids[2]]},
                "allowed_actions": {"embed": True, "memory_reference": True, "download": False,
                                    "print": False, "publish": False}})
    write_json(run / "candidates.json", candidates)
    write_text(run / "evidence.jsonl", "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in evidence.values()))
    build_manifest(run)
    qualifying = qualifying_count()
    summary = {"qualifying": qualifying, "target": request["count"],
               "shortfall": max(0, request["count"] - qualifying), "cache": cache,
               "budget_exhausted": budget_exhausted,
               "source_failures": source_failures,
               "status": "unavailable" if not qualifying and source_failures else "success"}
    write_json(checked_path(run, "discovery-summary.json"), summary)
    if summary["status"] == "unavailable":
        fail("llm_sources_unavailable")
    return summary


def crawl4ai_discover(run: Path, search_url: str | None = None, *, max_search_pages: int = CRAWL4AI_MAX_SEARCH_PAGES,
                      source_limit: int = CRAWL4AI_MAX_SOURCE_PAGES) -> dict:
    """Populate metadata-only memory-reference candidates through Crawl4AI."""
    if not 1 <= max_search_pages <= CRAWL4AI_MAX_SEARCH_PAGES:
        fail(f"max_search_pages must be 1..{CRAWL4AI_MAX_SEARCH_PAGES}")
    if not 1 <= source_limit <= CRAWL4AI_MAX_SOURCE_PAGES:
        fail(f"source_limit must be 1..{CRAWL4AI_MAX_SOURCE_PAGES}")
    run = run.resolve()
    request, existing, evidence = load_records(run)
    target = request["count"]
    search = _crawl4ai_search_url(search_url, request)
    log_event(run, "search", "Crawl4AI Programmable Search image discovery", [search])
    seen_search_pages = set()

    def before_search_page(page_number, url):
        if page_number not in seen_search_pages:
            log_event(run, "page", f"Crawl4AI image-search page {page_number}", [url])
            seen_search_pages.add(page_number)

    cards = _crawl4ai_search_pages(search, max_search_pages, before_page=before_search_page)
    if not seen_search_pages:
        log_event(run, "page", "Crawl4AI image-search page 1", [search])
    merged = list(existing)
    existing_ids = {candidate.get("id") for candidate in merged}
    seen_sources, qualifying = set(), 0
    for card in cards:
        source_url = card.get("source_url")
        if not source_url or source_url in seen_sources or len(seen_sources) >= source_limit:
            continue
        try:
            _, source_host, source_port = valid_url(source_url)
            public_addresses(source_host, source_port)
        except ResearchError as error:
            log_event(run, "note", f"Skipped unsafe CSE source URL: {error}", [search])
            continue
        if not _crawl4ai_location_matches(card.get("text", ""), request["place"]):
            continue
        if _crawl4ai_scene_date(card.get("text", ""), request["temporal"]) is None:
            continue
        seen_sources.add(source_url)
        log_event(run, "page", "Crawl4AI source-page inspection", [source_url])
        try:
            page = _crawl4ai_source_page(source_url)
            images = _crawl4ai_source_images(page, card, request)
        except (ResearchError, OSError, ValueError, http.client.HTTPException) as error:
            log_event(run, "note", f"Crawl4AI source skipped: {type(error).__name__}: {error}", [source_url])
            continue
        for image in images:
            if qualifying >= target or len(merged) >= 100:
                break
            image_url = image["image_url"]
            candidate_id = "crawl4ai-" + hashlib.sha256(f"{source_url}\n{image_url}".encode()).hexdigest()[:24]
            if candidate_id in existing_ids or any(c.get("image_url") == image_url for c in merged):
                continue
            evidence_ids = []
            for kind, excerpt in (("place", image["source_excerpt"]), ("scene_date", image["source_excerpt"]),
                                  ("access_terms", "Public source page fetched through the user-requested Crawl4AI reference search.")):
                eid = _crawl4ai_evidence_id(source_url, image_url, kind)
                if eid not in evidence:
                    evidence[eid] = {"id": eid, "kind": kind, "url": source_url,
                                     "locator": "Crawl4AI source-page metadata and rendered text",
                                     "excerpt": excerpt[:4000], "observed_at": utcnow()}
                evidence_ids.append(eid)
            _, source_host, _ = valid_url(source_url)
            try:
                _, image_host, image_port = valid_url(image_url)
                public_addresses(image_host, image_port)
            except ResearchError as error:
                log_event(run, "note", f"Skipped non-public C4A image URL: {error}", [source_url])
                continue
            candidate = {
                "id": candidate_id, "title": image["title"], "source_page_url": source_url,
                "image_url": image_url, "observed_image_url": image.get("observed_image_url") or image_url,
                "creator": None, "collection_page_url": search,
                "authenticity": "source_described_photograph", "memory_reference_only": True,
                "place": {"label": request["place"], "match": "exact", "evidence_ids": [evidence_ids[0]]},
                "scene_date": {**image["scene_date"], "evidence_ids": [evidence_ids[1]]},
                "rights": {"license_id": "unknown", "license_url": None, "scope": "unknown",
                           "download_permitted": None, "commercial_use_permitted": None,
                           "attribution": None, "evidence_ids": []},
                "acquisition": {"access_permitted": True, "allowed_hosts": sorted({source_host, image_host}),
                                "evidence_ids": [evidence_ids[2]]},
                "allowed_actions": {"embed": True, "memory_reference": True, "download": False, "print": False, "publish": False},
                "notes": ["Crawl4AI discovery candidate for memory reference only; source rights remain unresolved."]
            }
            merged.append(candidate)
            existing_ids.add(candidate_id)
            qualifying += 1
        if qualifying >= target:
            break
    write_json(run / "candidates.json", merged[:100])
    write_text(run / "evidence.jsonl", "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in evidence.values()))
    manifest = build_manifest(run)
    summary = {"search_url": search, "search_cards": len(cards), "source_pages": len(seen_sources),
               "qualifying": qualifying, "target": target, "shortfall": max(0, target - qualifying),
               "reference_status": "complete" if qualifying >= target else "incomplete",
               "manifest": manifest["summary"]}
    return summary

def image_info(data: bytes, content_type: str) -> dict:
    try:
        from PIL import Image
    except ImportError:
        fail("Pillow is required for downloads. Install the skill requirements in a project-local environment.")
    if len(data) > MAX_IMAGE_BYTES:
        fail("Image exceeds byte limit")
    types = {"JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"), "WEBP": ("image/webp", ".webp")}
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        previous_limit = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        try:
            with Image.open(io.BytesIO(data), formats=list(types)) as im:
                fmt, width, height = im.format, im.width, im.height
                if width * height > MAX_PIXELS or getattr(im, "n_frames", 1) != 1:
                    fail("Oversized or animated image not accepted")
                expected, ext = types[fmt]
                if content_type.split(";", 1)[0].lower().strip() != expected:
                    fail("Image MIME type and decoded format disagree")
                im.verify()
            with Image.open(io.BytesIO(data), formats=list(types)) as im:
                im.load()
        except ResearchError:
            raise
        except Exception as e:
            fail(f"Invalid image: {type(e).__name__}: {e}")
        finally:
            Image.MAX_IMAGE_PIXELS = previous_limit
    return {"width": width, "height": height, "mime_type": expected, "extension": ext,
            "sha256": hashlib.sha256(data).hexdigest(), "byte_count": len(data)}

def required_string(obj, key, limit=8192) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        fail(f"Missing/invalid {key}")
    return value

def load_records(run: Path) -> tuple[dict, list[dict], dict]:
    request = read_json(checked_path(run, "request.json"))
    if request.get("schema_version") != "1.0": fail("Unsupported request schema")
    candidates = read_json(checked_path(run, "candidates.json"))
    if not isinstance(candidates, list) or len(candidates) > 100: fail("candidates.json must be a list of at most 100 objects")
    evidence = {}
    for ev in read_jsonl(checked_path(run, "evidence.jsonl")):
        eid = required_string(ev, "id", 64)
        if not ID_RE.fullmatch(eid) or eid in evidence: fail("Invalid/duplicate evidence id")
        if ev.get("kind") not in EVIDENCE_KINDS: fail("Unknown evidence kind")
        valid_url(required_string(ev, "url"))
        required_string(ev, "excerpt", 4000)
        required_string(ev, "locator", 1000)
        stamp = datetime.fromisoformat(required_string(ev, "observed_at"))
        if stamp.tzinfo is None: fail("Evidence observed_at needs a timezone")
        evidence[eid] = ev
    ids = set()
    for c in candidates:
        if not isinstance(c, dict): fail("Candidate must be an object")
        cid = required_string(c, "id", 64)
        if not ID_RE.fullmatch(cid) or cid in ids: fail("Invalid/duplicate candidate id")
        ids.add(cid)
        required_string(c, "title", 1000)
        valid_url(required_string(c, "source_page_url"))
        if c.get("image_url") is not None: valid_url(c["image_url"])
        if c.get("observed_image_url") is not None: valid_url(c["observed_image_url"])
        for key in ("place", "scene_date", "rights", "acquisition"):
            if not isinstance(c.get(key), dict): fail(f"Missing candidate object: {key}")
            refs = c[key].get("evidence_ids", [])
            if not isinstance(refs, list) or any(not isinstance(x, str) or x not in evidence for x in refs):
                fail(f"Invalid evidence references on {cid}/{key}")
        d = c["scene_date"]
        if d.get("basis") not in DATE_BASES: fail("Unknown date evidence basis")
        a, b = d.get("start"), d.get("end")
        if (a is None) != (b is None): fail("Date interval must have both bounds or neither")
        if a is not None and date.fromisoformat(a) > date.fromisoformat(b): fail("Reversed scene interval")
        if c["place"].get("match") not in {"exact", "broader", "uncertain", "wrong"}: fail("Invalid place match")
        for key in ("download_permitted", "commercial_use_permitted"):
            if c["rights"].get(key) is not None and type(c["rights"][key]) is not bool:
                fail(f"{key} must be true, false or null")
        if c["acquisition"].get("access_permitted") is not None and type(c["acquisition"]["access_permitted"]) is not bool:
            fail("access_permitted must be true, false or null")
        hosts = c["acquisition"].get("allowed_hosts", [])
        if not isinstance(hosts, list) or any(not isinstance(x, str) or not x or "/" in x or ":" in x or "*" in x for x in hosts):
            fail("Allowed hosts must be explicit hostnames without ports, paths or wildcards")
    return request, candidates, evidence

def has_evidence(record: dict, evidence: dict, kinds: set[str]) -> bool:
    return any(evidence[x]["kind"] in kinds for x in record.get("evidence_ids", []) if x in evidence)

def evaluate(c: dict, request: dict, evidence: dict) -> dict:
    reasons = []
    p, d, r, a = c["place"], c["scene_date"], c["rights"], c["acquisition"]
    if p.get("match") != "exact" or not has_evidence(p, evidence, {"place"}): reasons.append("PLACE_NOT_VERIFIED_EXACT")
    temporal = request["temporal"]
    date_status = "unknown"
    known = d.get("start") and d.get("end") and d.get("basis") not in WEAK_DATE_BASES and has_evidence(d, evidence, {"scene_date"})
    if known:
        start, end = date.fromisoformat(d["start"]), date.fromisoformat(d["end"])
        as_of = date.fromisoformat(request["as_of"])
        if start > as_of or end > as_of:
            date_status = "future_or_incomplete_date"
        elif temporal["mode"] == "historical_unspecified":
            # A recent photo is not automatically an old photograph.
            cutoff = subtract_months(as_of, request["recent_months"])
            date_status = "dated_historical_candidate" if end < cutoff else "not_established_as_old"
        else:
            lower, upper = date.fromisoformat(temporal["start"]), date.fromisoformat(temporal["end"])
            date_status = "in_range" if lower <= start and end <= upper else ("overlap" if start <= upper and end >= lower else "out_of_range")
    if date_status not in {"in_range", "dated_historical_candidate"}: reasons.append("DATE_" + date_status.upper())
    if d.get("conflicting") is not False: reasons.append("DATE_CONFLICT_UNRESOLVED")
    if c.get("authenticity") != "source_described_photograph": reasons.append("AUTHENTICITY_UNRESOLVED")
    if not c.get("image_url"): reasons.append("NO_DIRECT_IMAGE_URL")
    if r.get("scope") != "item": reasons.append("RIGHTS_NOT_ITEM_SCOPED")
    if r.get("download_permitted") is not True: reasons.append("DOWNLOAD_PERMISSION_UNKNOWN_OR_DENIED")
    if request["usage"] == "commercial-memoir" and r.get("commercial_use_permitted") is not True:
        reasons.append("COMMERCIAL_PERMISSION_UNKNOWN_OR_DENIED")
    if not has_evidence(r, evidence, {"license", "permission"}): reasons.append("NO_RIGHTS_EVIDENCE")
    license_id = r.get("license_id", "unknown")
    if license_id in LICENSE_URLS:
        if (r.get("license_url") or "").rstrip("/") != LICENSE_URLS[license_id].rstrip("/"):
            reasons.append("LICENSE_URL_MISMATCH")
        if license_id != "CC0-1.0" and not (r.get("attribution") or "").strip(): reasons.append("ATTRIBUTION_MISSING")
    elif license_id == "custom-permission":
        if not has_evidence(r, evidence, {"permission"}) or not r.get("permission_grant_reference"):
            reasons.append("CUSTOM_PERMISSION_NOT_DOCUMENTED")
    else:
        reasons.append("LICENSE_REQUIRES_MANUAL_PERMISSION_REVIEW")
    if a.get("access_permitted") is not True or not has_evidence(a, evidence, {"access_terms", "permission"}):
        reasons.append("ACQUISITION_ACCESS_NOT_DOCUMENTED")
    if c.get("image_url"):
        _, host, _ = valid_url(c["image_url"])
        if host not in a.get("allowed_hosts", []): reasons.append("IMAGE_HOST_NOT_APPROVED")
    return {"id": c["id"], "date_status": date_status, "eligible_for_local_download": not reasons,
            "reason_codes": reasons, "publication_status": "not_approved_by_this_local_skill"}

def log_event(run: Path, kind: str, detail: str, urls: list[str]) -> None:
    request = read_json(checked_path(run, "request.json"))
    if kind not in {"search", "page", "note"}: fail("Invalid event kind")
    if kind != "note":
        limit = request["budgets"]["max_queries" if kind == "search" else "max_pages"]
        count = sum(e.get("kind") == kind for e in read_jsonl(checked_path(run, "search_log.jsonl")))
        if count >= limit: fail(f"{kind} budget exhausted")
    for url in urls: valid_url(url)
    append_jsonl(checked_path(run, "search_log.jsonl"), {"at": utcnow(), "kind": kind, "detail": detail, "urls": urls})

def build_manifest(run: Path, *, download: bool = False) -> dict:
    request, candidates, evidence = load_records(run)
    old_path = checked_path(run, "manifest.json")
    old = read_json(old_path) if old_path.exists() else {}
    prior = {x["id"]: x for x in old.get("results", [])}
    fetcher, results, downloaded_count = Fetcher(), [], 0
    seen_hashes: set[str] = set()
    for c in candidates:
        verdict = evaluate(c, request, evidence)
        entry = {"id": c["id"], "title": c["title"], "source_page_url": c["source_page_url"],
                 "scene_date": c["scene_date"], "creator": c.get("creator"), "rights": c["rights"],
                 "memory_reference_only": bool(c.get("memory_reference_only")),
                 "evaluation": verdict, "download_status": "not_downloaded", "local_path": None}
        old_entry = prior.get(c["id"], {})
        old_acq = old_entry.get("acquisition", {})
        if verdict["eligible_for_local_download"] and old_entry.get("local_path") and old_acq.get("requested_url") == c.get("image_url"):
            path = checked_path(run, old_entry["local_path"])
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == old_acq.get("sha256"):
                entry.update(local_path=old_entry["local_path"], download_status="downloaded", acquisition=old_acq)
                seen_hashes.add(old_acq["sha256"])
                downloaded_count = len(seen_hashes)
        if download and verdict["eligible_for_local_download"] and not entry["local_path"] and downloaded_count < request["count"]:
            try:
                status, final, headers, data = fetcher.fetch(c["image_url"], MAX_IMAGE_BYTES, set(c["acquisition"]["allowed_hosts"]))
                if status != 200: fail(f"Image request returned HTTP {status}")
                info = image_info(data, headers.get("content-type", ""))
                rel = "images/" + info["sha256"] + info["extension"]
                path = checked_path(run, rel)
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    if hashlib.sha256(path.read_bytes()).hexdigest() != info["sha256"]: fail("Existing asset hash mismatch")
                else:
                    fd, temp = tempfile.mkstemp(prefix=".image-", dir=path.parent)
                    try:
                        with os.fdopen(fd, "wb") as f: f.write(data)
                        os.replace(temp, path)
                    finally:
                        if os.path.exists(temp): os.unlink(temp)
                entry.update(download_status="downloaded", local_path=rel,
                             acquisition={**info, "requested_url": c["image_url"], "final_url": final, "downloaded_at": utcnow()})
                seen_hashes.add(info["sha256"])
                downloaded_count = len(seen_hashes)
            except (ResearchError, OSError, http.client.HTTPException, ValueError) as e:
                entry["download_status"] = "failed"
                entry["download_error"] = str(e)
        elif not verdict["eligible_for_local_download"]:
            entry["download_status"] = "blocked"
        results.append(entry)
    manifest = {"schema_version": "1.0", "skill_version": VERSION, "created_at": utcnow(), "request": request,
                "results": results, "summary": {"candidates": len(results), "eligible": sum(x["evaluation"]["eligible_for_local_download"] for x in results),
                "memory_references": sum(x["memory_reference_only"] for x in results),
                "downloaded": sum(x["download_status"] == "downloaded" for x in results),
                "unique_files": len({x["local_path"] for x in results if x["local_path"]})},
                "notice": "Source-grounded assertions, not independent authentication. Crawl4AI candidates marked memory_reference_only are prompts for recollection and are not approved for memoir publication, paid-app export or print."}
    distinct, seen = 0, set()
    for candidate, result in zip(candidates, results):
        if not result["evaluation"]["eligible_for_local_download"]:
            continue
        keys = {candidate["source_page_url"], candidate.get("image_url")}
        keys.discard(None)
        if result.get("acquisition", {}).get("sha256"):
            keys.add(result["acquisition"]["sha256"])
        if not seen.intersection(keys):
            distinct += 1
        seen.update(keys)
    manifest["summary"].update(target=request["count"], qualifying_photos=distinct,
                               shortfall=max(0, request["count"] - distinct),
                               status="complete" if distinct >= request["count"] else "incomplete")
    write_json(old_path, manifest)
    render_reports(run, manifest)
    return manifest

def md_escape(text: str) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", str(text).replace("\n", " "))

def render_reports(run: Path, manifest: dict) -> None:
    req = manifest["request"]
    title = "Place photo research — " + req["place"]
    md = ["# " + md_escape(title), "", f"Mode: **{req['temporal']['mode']}** · As of {req['as_of']}",
          "", "External references, not family photographs. Source claims are not independently authenticated.", "",
          "Summary: " + json.dumps(manifest["summary"]), ""]
    blocks = []
    for row in manifest["results"]:
        cdate = row["scene_date"]
        date_label = f"{cdate.get('start')} to {cdate.get('end')}" if cdate.get("start") else "Capture date unknown"
        clean_title = row["title"].replace("\n", " ")
        md.extend([f"## {row['id']} — {md_escape(clean_title)}", "", f"Scene date: {date_label}; evidence basis: {cdate.get('basis')}",
                   f"Download: {row['download_status']}", f"Source: <{row['source_page_url']}>",
                   f"Attribution: {md_escape(row['rights'].get('attribution') or 'Not recorded')}",
                   "Checks: " + (", ".join(row["evaluation"]["reason_codes"]) or "Local download checks passed"),
                   "Publication: separate review required.", ""])
        image_html = ""
        if row["local_path"]:
            md.extend([f"Local file: `{row['local_path']}`", ""])
            image_html = f'<img loading="lazy" src="{html.escape(row["local_path"], quote=True)}" alt="{html.escape(clean_title, quote=True)}">'
        blocks.append(f'<article><h2>{html.escape(clean_title)}</h2>{image_html}'
                      f'<p>{html.escape(date_label)} · {html.escape(row["download_status"])}</p>'
                      f'<p><a href="{html.escape(row["source_page_url"], quote=True)}" rel="noreferrer noopener">Source page</a></p>'
                      f'<p>{html.escape(row["rights"].get("attribution") or "Attribution not recorded")}</p>'
                      f'<p>{html.escape(", ".join(row["evaluation"]["reason_codes"]))}</p></article>')
    md.append(manifest["notice"])
    write_text(checked_path(run, "report.md"), "\n".join(md)+"\n")
    page = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' \
           '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src \'self\'; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">' \
           f'<title>{html.escape(title)}</title><style>body{{font:16px system-ui;margin:2rem auto;max-width:1100px;padding:0 1rem}}' \
           'main{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1.2rem}article{border:1px solid;padding:1rem;overflow-wrap:anywhere}' \
           'img{width:100%;height:240px;object-fit:contain}h2{font-size:1.1rem}</style>' \
           f'<h1>{html.escape(title)}</h1><p>{html.escape(manifest["notice"])}</p><main>{"".join(blocks)}</main></html>'
    write_text(checked_path(run, "gallery.html"), page)

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Create a new run; omitted --period means current")
    init.add_argument("--place", required=True)
    init.add_argument("--period")
    init.add_argument("--period-note", default="")
    init.add_argument("--subject", default="streets and everyday life")
    init.add_argument("--out", required=True)
    init.add_argument("--as-of", help="ISO date override for reproducibility")
    init.add_argument("--timezone", default="Australia/Sydney")
    init.add_argument("--recent-months", type=int, default=24)
    init.add_argument("--count", type=int, default=10)
    init.add_argument("--usage", choices=["commercial-memoir", "personal-reference"], default="commercial-memoir")
    init.add_argument("--max-queries", type=int, default=40)
    init.add_argument("--max-pages", type=int, default=80)
    log = sub.add_parser("log", help="Record ONE native search or page read BEFORE execution; counts toward budget")
    log.add_argument("--run", required=True)
    log.add_argument("--kind", choices=["search", "page", "note"], required=True)
    log.add_argument("--detail", required=True)
    log.add_argument("--url", action="append", default=[])
    inspect = sub.add_parser("inspect", help="Fetch a permitted public HTML page and extract untrusted candidates")
    inspect.add_argument("--run", required=True)
    inspect.add_argument("--url", required=True)
    inspect.add_argument("--allow-host", action="append", default=[])
    inspect.add_argument("--access-permitted", action="store_true", help="Explicit attestation that source/page access is permitted")
    crawl = sub.add_parser("crawl4ai", help="Use Crawl4AI to discover memory-reference images from a user-supplied Google CSE")
    crawl.add_argument("--run", required=True)
    crawl.add_argument("--search-url", help="Google Programmable Search page URL; defaults to GOOGLE_CSE_URL or GOOGLE_CSE_ID")
    crawl.add_argument("--max-search-pages", type=int, default=CRAWL4AI_MAX_SEARCH_PAGES)
    crawl.add_argument("--source-limit", type=int, default=CRAWL4AI_MAX_SOURCE_PAGES)
    discover = sub.add_parser("discover", help="Discover source-backed place photos through configured LLM web search")
    discover.add_argument("--run", required=True)
    discover.add_argument("--source-limit", type=int, default=24)
    discover.add_argument("--provider-timeout", type=float, default=30)
    discover.add_argument("--cache-ttl", type=int, default=86400)
    for name in ("audit", "download", "report"):
        p = sub.add_parser(name)
        p.add_argument("--run", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            if not 1 <= args.count <= 24 or not 1 <= args.max_queries <= 40 or not 1 <= args.max_pages <= 80:
                fail("Invalid count or research budget")
            if not args.place.strip() or len(args.place) > 300 or len(args.subject) > 300:
                fail("Place/subject must be concise public search text")
            clock = date.fromisoformat(args.as_of) if args.as_of else datetime.now(ZoneInfo(args.timezone)).date()
            temporal = normalize_period(args.period, clock, args.recent_months)
            run = Path(args.out).expanduser().resolve()
            if run.exists() and any(run.iterdir()): fail("Output folder is nonempty; choose a new run or resume the existing run")
            run.mkdir(parents=True, exist_ok=True)
            request = {"schema_version": "1.0", "place": args.place, "subject": args.subject,
                       "temporal": temporal, "period_note": args.period_note, "as_of": clock.isoformat(), "timezone": args.timezone,
                       "recent_months": args.recent_months, "usage": args.usage, "count": args.count,
                       "budgets": {"max_queries": args.max_queries, "max_pages": args.max_pages}, "created_at": utcnow()}
            write_json(run / "request.json", request)
            write_json(run / "candidates.json", [])
            write_text(run / "evidence.jsonl", "")
            write_text(run / "search_log.jsonl", "")
            build_manifest(run)
            print(json.dumps({"run": str(run), "temporal": temporal}, ensure_ascii=False, indent=2))
        elif args.command == "log":
            log_event(Path(args.run).resolve(), args.kind, args.detail, args.url)
            print("Recorded")
        elif args.command == "inspect":
            if not args.access_permitted: fail("Confirm permitted page access before using --access-permitted; this is not a legal determination")
            run = Path(args.run).resolve()
            _, host, _ = valid_url(args.url)
            log_event(run, "page", "HTML inspection", [args.url])
            status, final, headers, body = Fetcher().fetch(args.url, MAX_PAGE_BYTES, {host, *args.allow_host})
            if status != 200: fail(f"Page returned HTTP {status}")
            if headers.get("content-type", "").split(";",1)[0].strip() not in {"text/html", "application/xhtml+xml"}:
                fail("inspect supports HTML only; use a permitted native tool for other formats")
            encoding_match = re.search(r"charset=[\"']?([A-Za-z0-9_-]+)", headers.get("content-type", ""), re.I)
            if not encoding_match:
                encoding_match = re.search(r"charset\s*=\s*[\"']?([A-Za-z0-9_-]+)", body[:4000].decode("ascii", errors="ignore"), re.I)
            encoding = encoding_match.group(1) if encoding_match else "utf-8"
            parsed = PageParser(final)
            parsed.feed(body.decode(encoding, errors="replace"))
            record = {"requested_url": args.url, "final_url": final, "fetched_at": utcnow(),
                      "page_sha256": hashlib.sha256(body).hexdigest(), **parsed.output()}
            rel = "pages/" + hashlib.sha256(args.url.encode()).hexdigest()[:16] + ".json"
            write_json(checked_path(run, rel), record)
            print(json.dumps({"saved": str(checked_path(run, rel)), "images": len(record["image_candidates"]), "title": record["title"]}, ensure_ascii=False))
        elif args.command == "discover":
            summary = llm_discover(Path(args.run), source_limit=args.source_limit,
                                   provider_timeout=args.provider_timeout, cache_ttl=args.cache_ttl)
            print(json.dumps(summary, ensure_ascii=False))
        elif args.command == "crawl4ai":
            summary = crawl4ai_discover(Path(args.run).resolve(), args.search_url,
                                         max_search_pages=args.max_search_pages, source_limit=args.source_limit)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            manifest = build_manifest(Path(args.run).resolve(), download=args.command == "download")
            print(json.dumps(manifest["summary"], indent=2))
        return 0
    except (ResearchError, ValueError, OSError, KeyError, TypeError, http.client.HTTPException) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
