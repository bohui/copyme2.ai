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
import warnings
from zoneinfo import ZoneInfo

VERSION = "1.1.0"
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


class SearchBlocked(ResearchError):
    def __init__(self, cards):
        super().__init__("CSE access challenge; no retry or CAPTCHA solving")
        self.cards = cards


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
    """Parse a capture assertion, never select a convenient year from mixed dates.

    Callers must supply an image caption or explicit capture metadata, not a
    page title, search snippet, publication date or upload timestamp.
    """
    text = _text(text)
    # Explicit capture labels distinguish mixed 'taken / uploaded' records.
    capture = re.search(r"(?:taken on|photographed(?: on)?|captured(?: on)?|拍摄(?:于)?|摄于)\s*[:：]?\s*([^;；\n]+)", text, re.I)
    if capture:
        text = capture.group(1)
    text = re.split(r"uploaded|published|updated|scanned|copyright|上传|发表|发布|更新|扫描|©", text, maxsplit=1, flags=re.I)[0]
    dates, consumed = [], text
    for match in re.finditer(r"(?<!\d)((?:18|19|20)\d{2})[-:/年](\d{1,2})[-:/月](\d{1,2})(?:日)?", text):
        try:
            day = date(*map(int, match.groups()))
        except ValueError:
            return None
        dates.append((day, day, "day"))
        consumed = consumed.replace(match.group(0), " ")
    for match in re.finditer(r"\b([A-Za-z]+ \d{1,2},? (?:18|19|20)\d{2})\b", text):
        for fmt in ("%B %d, %Y", "%B %d %Y", "%b %d, %Y", "%b %d %Y"):
            try:
                day = datetime.strptime(match.group(1), fmt).date()
                dates.append((day, day, "day"))
                consumed = consumed.replace(match.group(0), " ")
                break
            except ValueError:
                pass
    for match in re.finditer(r"(?<!\d)((?:18|19|20)\d{2})(?:s|年代)", consumed, re.I):
        year = int(match.group(1))
        if year % 10:
            return None
        dates.append((date(year, 1, 1), date(year + 9, 12, 31), "decade"))
        consumed = consumed.replace(match.group(0), " ")
    if re.search(r"(?:上世纪|20世纪)?\s*(?:80|八十)年代", consumed):
        dates.append((date(1980, 1, 1), date(1989, 12, 31), "decade"))
        consumed = re.sub(r"(?:上世纪|20世纪)?\s*(?:80|八十)年代", " ", consumed)
    for year in set(_crawl4ai_years(consumed)):
        # A repeated year alongside a precise date is not a second assertion.
        if not any(a.year <= year <= b.year for a, b, _ in dates):
            dates.append((date(year, 1, 1), date(year, 12, 31), "year"))
    dates = list(dict.fromkeys(dates))
    if len(dates) != 1:
        return None
    start, end, precision = dates[0]
    if temporal.get("start") and temporal.get("end"):
        if not date.fromisoformat(temporal["start"]) <= start <= end <= date.fromisoformat(temporal["end"]):
            return None
    return {"start": start.isoformat(), "end": end.isoformat(), "precision": precision,
            "basis": "source_caption", "conflicting": False}


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
            if key in {"SERPAPI_KEY", "GOOGLE_CSE_URL", "GOOGLE_CSE_ID"} and key not in os.environ:
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
    # Only public widget options are allowed in logged/cached search URLs.
    params = {"cx": params["cx"], "q": [_crawl4ai_query(request)]}
    return urlunsplit((parsed.scheme, parsed.hostname, parsed.path or "/cse", urlencode(params, doseq=True), ""))


def _crawl4ai_query(request: dict) -> str:
    temporal = request["temporal"]
    terms = [_crawl4ai_place_query(request["place"])]
    if temporal.get("mode") == "current":
        terms += ["现在", "街景"]
    elif temporal.get("mode") == "historical_range":
        start, end = date.fromisoformat(temporal["start"]).year, date.fromisoformat(temporal["end"]).year
        terms += [f"{start}年代" if start % 10 == 0 and end == start + 9 else f"{start}-{end}", "老照片"]
    else:
        terms += ["老照片"]
    return " ".join(terms)


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
                blocked_text = re.search(r"please verify that you are not a robot|unusual traffic from your computer network|g-recaptcha", result.html or "", re.I)
                js_result = getattr(result, "js_execution_result", None)
                if blocked_text or (isinstance(js_result, dict) and '"blocked": true' in json.dumps(js_result)):
                    raise SearchBlocked(cards)
                if not result.success:
                    if page_number == 1:
                        fail("Crawl4AI search failed")
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
    record = parsed.output()
    title = record.get("title") or page.get("title", "")
    excerpt = record.get("text_excerpt") or page.get("text", "")
    if not _crawl4ai_location_matches(" ".join([title, excerpt[:2000]]), request["place"]):
        return []
    images = []
    for item in page.get("media", []) if isinstance(page.get("media"), list) else []:
        if isinstance(item, dict):
            images.append({"url": item.get("src") or item.get("url"), "alt": item.get("alt", ""),
                           "description": item.get("desc", "")})
    for item in record["image_candidates"]:
        for url in item["candidate_urls"]:
            images.append({"url": url, "alt": item["alt"], "description": item["figure_text"]})
    capture_metadata = {}
    def visit(node, depth=0):
        if depth > 10:
            return
        if isinstance(node, list):
            for child in node[:150]: visit(child, depth + 1)
        elif isinstance(node, dict):
            kinds = node.get("@type", [])
            if isinstance(kinds, str): kinds = [kinds]
            if set(kinds).intersection({"Photograph", "ImageObject"}):
                url = _crawl4ai_image_url(node.get("contentUrl"))
                taken = node.get("dateTaken") or node.get("dateCreated")
                if url and isinstance(taken, str):
                    capture_metadata[url] = taken
                    images.append({"url": url, "alt": node.get("name", ""), "description": node.get("caption", "")})
            for child in node.values(): visit(child, depth + 1)
    visit(record["json_ld"])
    metadata = {str(item.get("property") or item.get("name") or "").lower(): item.get("content", "")
                for item in record["metadata"]}
    primary = _crawl4ai_image_url(metadata.get("og:image"))
    taken = next((metadata[key] for key in ("datetaken", "date_taken", "exif:datetimeoriginal", "photo:datetaken") if metadata.get(key)), None)
    if primary and taken:
        capture_metadata[primary] = taken
        images.append({"url": primary, "alt": metadata.get("og:title", title), "description": ""})
    unique = {}
    for image in images:
        observed = image.get("url")
        if isinstance(observed, str): observed = urljoin(source_url, observed)
        url = _crawl4ai_image_url(observed)
        if not url: continue
        alt, caption = _text(image.get("alt")), _text(image.get("description"))
        if NON_PHOTO.search(" ".join([alt, caption])): continue
        if alt and not (_crawl4ai_location_matches(alt, request["place"]) or _crawl4ai_scene_date(alt, request["temporal"])):
            continue
        if not alt and caption and not (_crawl4ai_location_matches(caption, request["place"]) or _crawl4ai_scene_date(caption, request["temporal"])):
            continue
        # Repeated article-title alt text is not an image-specific date assertion.
        assertion = capture_metadata.get(url) or " ".join(value for value in (alt, caption) if value and value != title)
        scene = _crawl4ai_scene_date(assertion, request["temporal"])
        if scene is None: continue
        if request.get("as_of"):
            as_of = date.fromisoformat(request["as_of"])
            end = date.fromisoformat(scene["end"])
            if end > as_of: continue
            if request["temporal"]["mode"] == "historical_unspecified" and end >= subtract_months(as_of, request.get("recent_months", 24)):
                continue
        if url in capture_metadata: scene["basis"] = "provider_date_taken"
        unique[url] = {"image_url": url, "observed_image_url": observed, "title": (alt or caption or title)[:1000],
                       "scene_date": scene, "source_excerpt": ("Place: " + title + "; Image capture assertion: " + assertion)[:1200]}
    return list(unique.values())


def _crawl4ai_evidence_id(source_url: str, image_url: str, kind: str) -> str:
    return "c4a-" + hashlib.sha256(f"{source_url}\n{image_url}\n{kind}".encode()).hexdigest()[:24]


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
    return _discover_cards(run, cards, search, source_limit)


def _discover_cards(run: Path, cards: list[dict], search: str | None, source_limit: int, *, fetch_source=None) -> dict:
    request, existing, evidence = load_records(run)
    target = request["count"]
    fetch_source = fetch_source or _crawl4ai_source_page
    merged = list(existing)
    existing_ids = {candidate.get("id") for candidate in merged}
    def verified_reference_urls(candidates):
        verified = set()
        for candidate in candidates:
            evaluation = evaluate(candidate, request, evidence)
            identity_errors = [reason for reason in evaluation["reason_codes"]
                               if reason.startswith(("DATE_", "PLACE_", "AUTHENTICITY_", "NO_DIRECT_IMAGE"))]
            if not identity_errors and (candidate.get("memory_reference_only") or evaluation["eligible_for_local_download"]):
                verified.add(candidate["image_url"])
        return verified
    preserved = verified_reference_urls(existing)
    seen_sources, qualifying = set(), 0
    for card in cards:
        if len(preserved) + qualifying >= target:
            break
        source_url = card.get("source_url")
        if not source_url or source_url in seen_sources or len(seen_sources) >= source_limit:
            continue
        try:
            _, source_host, source_port = valid_url(source_url)
            public_addresses(source_host, source_port)
        except ResearchError as error:
            log_event(run, "note", f"Skipped unsafe CSE source URL: {error}", [search] if search else [])
            continue
        if not _crawl4ai_location_matches(card.get("text", ""), request["place"]):
            continue
        seen_sources.add(source_url)
        log_event(run, "page", "Crawl4AI source-page inspection", [source_url])
        try:
            page = fetch_source(source_url)
            images = _crawl4ai_source_images(page, card, request)
            source_cards = [lead for lead in cards if lead.get("source_url") == source_url]
            origins = [origin for lead in source_cards for origin in lead.get("origins", [])]
            providers = sorted({provider for lead in source_cards for provider in lead.get("providers", ["cse"])})
        except (ResearchError, OSError, ValueError, http.client.HTTPException) as error:
            log_event(run, "note", f"Crawl4AI source skipped: {type(error).__name__}", [source_url])
            continue
        for image in images:
            if len(preserved) + qualifying >= target or len(merged) >= 100:
                break
            image_url = image["image_url"]
            related = [lead for lead in cards if lead.get("image_url") == image_url]
            image_origins = origins + [origin for lead in related for origin in lead.get("origins", [])]
            image_origins = list({json.dumps(origin, sort_keys=True): origin for origin in image_origins}.values())
            image_providers = sorted(set(providers + [provider for lead in related for provider in lead.get("providers", [])]))
            candidate_id = "crawl4ai-" + hashlib.sha256(f"{source_url}\n{image_url}".encode()).hexdigest()[:24]
            duplicate = next((c for c in merged if c.get("image_url") == image_url), None)
            if duplicate:
                duplicate["providers"] = sorted(set(duplicate.get("providers", []) + image_providers))
                duplicate["discovery_origins"] = list({json.dumps(origin, sort_keys=True): origin for origin in duplicate.get("discovery_origins", []) + image_origins}.values())
                continue
            if candidate_id in existing_ids:
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
                "creator": None, "collection_page_url": search or source_url,
                "providers": image_providers, "discovery_origins": image_origins,
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
        if len(preserved) + qualifying >= target:
            break
    write_json(run / "candidates.json", merged[:100])
    write_text(run / "evidence.jsonl", "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in evidence.values()))
    manifest = build_manifest(run)
    total = len(verified_reference_urls(merged))
    summary = {"search_url": search, "search_cards": len(cards), "source_pages": len(seen_sources),
               "qualifying": total, "verified_memory_references_added": qualifying, "target": target, "shortfall": max(0, target - total),
               "reference_status": "complete" if total >= target else "incomplete",
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
                 "providers": c.get("providers", []), "discovery_origins": c.get("discovery_origins", []),
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
        keys = {candidate.get("image_url") or candidate["source_page_url"]}
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
                   f"Providers: {', '.join(row.get('providers', [])) or 'manual/native'}", f"Download: {row['download_status']}", f"Source: <{row['source_page_url']}>",
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
    discover = sub.add_parser("discover", help="Run SerpAPI and the supplied Google CSE page concurrently; merge public leads")
    discover.add_argument("--run", required=True)
    discover.add_argument("--search-url")
    discover.add_argument("--max-search-pages", type=int, default=1)
    discover.add_argument("--source-limit", type=int, default=CRAWL4AI_MAX_SOURCE_PAGES)
    discover.add_argument("--provider-timeout", type=float, default=45)
    discover.add_argument("--cache-ttl", type=int, default=86400, help="Public search metadata TTL seconds; 0 disables reads")
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
            # Import lazily: app callers load this helper by file path.
            scripts = str(Path(__file__).resolve().parent)
            if scripts not in sys.path: sys.path.insert(0, scripts)
            sys.modules.setdefault("photo_research", sys.modules[__name__])
            from photo_search import discover as parallel_discover
            summary = parallel_discover(Path(args.run).resolve(), args.search_url,
                max_search_pages=args.max_search_pages, source_limit=args.source_limit,
                provider_timeout=args.provider_timeout, cache_ttl=args.cache_ttl)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
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
