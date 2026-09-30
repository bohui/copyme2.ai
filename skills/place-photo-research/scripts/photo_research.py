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
from urllib.parse import urljoin, urlsplit, urlunsplit, quote
from urllib.robotparser import RobotFileParser
import warnings
from zoneinfo import ZoneInfo

VERSION = "1.0.0"
UA = "PlacePhotoResearch/1.0"
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_PIXELS = 40_000_000
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
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
                "downloaded": sum(x["download_status"] == "downloaded" for x in results),
                "unique_files": len({x["local_path"] for x in results if x["local_path"]})},
                "notice": "Source-grounded assertions, not independent authentication. Local evidence flags are not a production permission boundary. No paid-app/export/print approval is granted."}
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
        else:
            manifest = build_manifest(Path(args.run).resolve(), download=args.command == "download")
            print(json.dumps(manifest["summary"], indent=2))
        return 0
    except (ResearchError, ValueError, OSError, KeyError, TypeError, http.client.HTTPException) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
