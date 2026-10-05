"""Bounded parallel search providers. Only public, normalized metadata is cached."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sys
import time
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import photo_research as p

SCHEMA = 1
TTL = 86400
MARKER = "PLACE_PHOTO_RESULT:"
SENSITIVE = re.compile(r"key|token|secret|signature|credential|password|authorization", re.I)


def public_url(value):
    if not isinstance(value, str) or len(value) > 8192:
        return None
    try:
        parsed, _, _ = p.valid_url(value)
        secret = os.environ.get("SERPAPI_KEY", "")
        if secret and secret in value:
            return None
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        if any(SENSITIVE.search(name) for name, _ in pairs):
            return None
        pairs = [(name, val) for name, val in pairs if not name.lower().startswith("utm_")]
        return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, urlencode(pairs), ""))
    except (p.ResearchError, ValueError):
        return None


def normalize_cards(cards, provider):
    normalized = []
    for item in cards[:100] if isinstance(cards, list) else []:
        if not isinstance(item, dict):
            continue
        source = public_url(item.get("source_url"))
        if not source:
            continue
        row = {"source_url": source, "providers": [provider]}
        for key in ("image_url", "preview_url"):
            row[key] = public_url(item.get(key))
        for key in ("title", "description", "alt"):
            row[key] = str(item.get(key) or "")[:1500]
            secret = os.environ.get("SERPAPI_KEY", "")
            if secret:
                row[key] = row[key].replace(secret, "[redacted]")
        # Do not cache provider diagnostics or authenticated request metadata.
        row["text"] = " ".join(row[key] for key in ("title", "description", "alt"))
        row["search_page"] = item.get("search_page", 1)
        normalized.append(row)
    return normalized


def serpapi(query):
    p._crawl4ai_load_dotenv()
    key = os.environ.get("SERPAPI_KEY", "").strip()
    if not key:
        return {"status": "not_configured", "cards": [], "requests": 0}
    options = {"engine": "google_images", "google_domain": "google.com", "hl": "zh-cn",
               "gl": "us", "ijn": 0, "safe": "active", "q": query, "api_key": key}
    try:
        # This URL is transient; neither it nor raw errors/responses are persisted.
        req = Request("https://serpapi.com/search.json?" + urlencode(options), headers={"User-Agent": p.UA})
        with urlopen(req, timeout=25) as response:
            body = response.read(4 * 1024 * 1024 + 1)
        if len(body) > 4 * 1024 * 1024:
            return {"status": "error", "error": "response_limit", "cards": [], "requests": 1}
        data = json.loads(body)
        if data.get("error") or data.get("search_metadata", {}).get("status") not in (None, "Success"):
            return {"status": "error", "error": "provider_error", "cards": [], "requests": 1}
        cards = [{"source_url": item.get("link"), "image_url": item.get("original"),
                  "preview_url": item.get("thumbnail"), "title": item.get("title")}
                 for item in data.get("images_results", []) if isinstance(item, dict)]
        return {"status": "success", "cards": normalize_cards(cards, "serpapi"), "requests": 1}
    except HTTPError as error:
        return {"status": "error", "error": f"http_{error.code}", "cards": [], "requests": 1}
    except Exception as error:
        return {"status": "error", "error": type(error).__name__, "cards": [], "requests": 1}


async def worker(provider, params, timeout):
    """A hard timeout kills/reaps just this worker; a sibling keeps its results."""
    started = time.monotonic()
    process = await asyncio.create_subprocess_exec(
        sys.executable, str(Path(__file__).resolve()), "worker", provider,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True)
    try:
        output, _ = await asyncio.wait_for(process.communicate(json.dumps(params).encode()), timeout)
        lines = output.decode("utf-8", errors="replace").splitlines()
        result = next(json.loads(line[len(MARKER):]) for line in reversed(lines) if line.startswith(MARKER))
        if not isinstance(result, dict):
            raise ValueError("Invalid worker result")
    except asyncio.TimeoutError:
        os.killpg(process.pid, signal.SIGKILL)
        await process.communicate()
        result = {"status": "timeout", "cards": [], "requests": 1}
    except Exception as error:
        if process.returncode is None:
            os.killpg(process.pid, signal.SIGKILL)
            await process.communicate()
        result = {"status": "error", "error": type(error).__name__, "cards": [], "requests": 1}
    result["seconds"] = round(time.monotonic() - started, 6)
    return result


def merge_cards(results):
    """An image identifies a lead; an album URL alone does not identify a photo."""
    merged = {}
    for provider, result in results.items():
        for card in normalize_cards(result.get("cards", []), provider):
            identity = card.get("image_url") or (card["source_url"], card["title"], card.get("preview_url"))
            if identity not in merged:
                merged[identity] = {**card, "origins": []}
            row = merged[identity]
            row["providers"] = sorted(set(row["providers"] + card["providers"]))
            origin = {"provider": provider, "source_url": card["source_url"],
                      "image_url": card.get("image_url"), "preview_url": card.get("preview_url"),
                      "title": card["title"]}
            if origin not in row["origins"]:
                row["origins"].append(origin)
    rows = list(merged.values())
    bridged = []
    for row in rows:
        matches = [other for other in rows if other.get("image_url") and not row.get("image_url")
                   and other["source_url"] == row["source_url"] and other["title"] == row["title"]]
        if len(matches) == 1:
            matches[0]["providers"] = sorted(set(matches[0]["providers"] + row["providers"]))
            matches[0]["origins"] += row["origins"]
        else:
            bridged.append(row)
    return bridged


def cache_path(run, provider, params):
    public = {"schema": SCHEMA, "provider": provider, "params": params}
    digest = hashlib.sha256(json.dumps(public, sort_keys=True).encode()).hexdigest()
    return p.checked_path(run, "search-cache/" + digest + ".json")


async def retrieve(run, request, search_url, max_pages, timeout, ttl=TTL):
    p._crawl4ai_load_dotenv()
    query = p._crawl4ai_query(request)
    results, pending = {}, {}
    options = {"serpapi": {"query": query, "engine": "google_images", "google_domain": "google.com",
                            "hl": "zh-cn", "gl": "us", "ijn": 0, "safe": "active"},
               "cse": {"url": search_url, "max_pages": max_pages}}
    started = time.monotonic()
    for provider, params in options.items():
        if provider == "serpapi" and not os.environ.get("SERPAPI_KEY", "").strip():
            results[provider] = {"status": "not_configured", "cards": [], "requests": 0}
            continue
        if provider == "cse" and not search_url:
            results[provider] = {"status": "not_configured", "cards": [], "requests": 0}
            continue
        guard = p.checked_path(run, "cse-blocked.json")
        if provider == "cse" and guard.is_file():
            results[provider] = {"status": "blocked", "error": "prior_challenge_in_this_run",
                                 "cards": [], "requests": 0}
            continue
        path = cache_path(run, provider, params)
        cached = None
        if path.is_file():
            try:
                data = p.read_json(path)
                if data.get("schema") == SCHEMA and data.get("params") == params and 0 <= time.time() - data["saved_at"] < ttl:
                    cached = normalize_cards(data["cards"], provider)
            except (ValueError, OSError, KeyError, TypeError):
                pass
        if cached is not None:
            results[provider] = {"status": "success", "cache": "hit", "cards": cached, "requests": 0, "seconds": 0}
            p.log_event(run, "note", provider + " search metadata cache hit", [])
            continue
        try:
            p.log_event(run, "search", provider + " image search: " + query, [search_url] if provider == "cse" else [])
            # Reserve browser page attempts before execution. Unused reservations
            # are conservative charges, not claims of successful page reads.
            if provider == "cse":
                for number in range(1, max_pages + 1):
                    p.log_event(run, "page", f"Reserved CSE browser page attempt {number}", [search_url])
        except p.ResearchError:
            results[provider] = {"status": "budget_exhausted", "cards": [], "requests": 0}
            continue
        pending[provider] = asyncio.create_task(worker(provider, params, timeout))
    if pending:
        values = await asyncio.gather(*pending.values(), return_exceptions=True)
        for (provider, _), value in zip(pending.items(), values):
            result = value if isinstance(value, dict) else {"status": "error", "error": type(value).__name__, "cards": [], "requests": 1}
            result["cards"] = normalize_cards(result.get("cards", []), provider)
            result["cache"] = "miss"
            results[provider] = result
            if provider == "cse" and result.get("status") == "blocked":
                p.write_json(p.checked_path(run, "cse-blocked.json"),
                             {"status": "blocked", "observed_at": p.utcnow()})
            if result.get("status") == "success":
                p.write_json(cache_path(run, provider, options[provider]),
                             {"schema": SCHEMA, "params": options[provider], "saved_at": time.time(), "cards": result["cards"]})
    return {"query": query, "providers": results, "cards": merge_cards(results),
            "search_seconds": round(time.monotonic() - started, 6)}


def discover(run, search_url=None, *, max_search_pages=1, source_limit=24, provider_timeout=45, cache_ttl=TTL):
    if not 1 <= max_search_pages <= p.CRAWL4AI_MAX_SEARCH_PAGES or not 1 <= source_limit <= p.CRAWL4AI_MAX_SOURCE_PAGES:
        p.fail("Invalid search/source page limits")
    if not 1 <= provider_timeout <= 120 or not 0 <= cache_ttl <= TTL:
        p.fail("Invalid timeout or cache TTL")
    run = run.resolve()
    request, _, _ = p.load_records(run)
    try:
        search_url = p._crawl4ai_search_url(search_url, request)
    except p.ResearchError:
        if search_url or p._configured_env("GOOGLE_CSE_URL") or p._configured_env("GOOGLE_CSE_ID"):
            raise
        search_url = None
    retrieval = asyncio.run(retrieve(run, request, search_url, max_search_pages, provider_timeout, cache_ttl))
    # Always save useful search leads, even when extraction fails or their dates
    # remain unresolved. Search titles never establish capture dates or rights.
    p.write_json(p.checked_path(run, "discovery.json"), retrieval)
    def fetch_source(url):
        result = asyncio.run(worker("source", {"url": url}, provider_timeout))
        if result.get("status") != "success":
            p.fail("Source inspection " + result.get("status", "error"))
        return result["page"]
    summary = p._discover_cards(run, retrieval["cards"], search_url, source_limit, fetch_source=fetch_source)
    summary.update(providers={name: {key: val for key, val in result.items() if key != "cards"}
                              for name, result in retrieval["providers"].items()},
                   search_seconds=retrieval["search_seconds"], discovery_file="discovery.json")
    p.write_json(p.checked_path(run, "discovery-summary.json"), summary)
    return summary


def worker_main(provider, params):
    if provider == "serpapi":
        return serpapi(params["query"])
    if provider == "source":
        return {"status": "success", "page": p._crawl4ai_source_page(params["url"])}
    try:
        cards = p._crawl4ai_search_pages(params["url"], params["max_pages"])
        return {"status": "success", "cards": normalize_cards(cards, "cse"), "requests": 1}
    except p.SearchBlocked as error:
        return {"status": "blocked", "error": "captcha_or_access_challenge", "cards": normalize_cards(error.cards, "cse"), "requests": 1}


if __name__ == "__main__":
    try:
        result = worker_main(sys.argv[2], json.loads(sys.stdin.read()))
    except Exception as error:
        result = {"status": "error", "error": type(error).__name__, "cards": [], "requests": 1}
    print(MARKER + json.dumps(result, ensure_ascii=False))
