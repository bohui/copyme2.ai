"""Offline regressions for the public-metadata search pipeline."""
import asyncio
import contextlib
from copy import deepcopy
from datetime import date
import importlib.util
import json
import io
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import photo_research as p
import photo_search as s

CARD = {"source_url": "https://archive.example/photo", "image_url": "https://images.example/1.jpg",
        "preview_url": "https://images.example/thumb.jpg", "title": "Chengde street"}


class ParallelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Path(self.tmp.name)
        with contextlib.redirect_stdout(io.StringIO()):
            p.main(["init", "--place", "Chengde", "--out", str(self.run), "--as-of", "2026-10-02"])
        self.request = p.read_json(self.run / "request.json")
        self.env = patch.dict(os.environ, {"SERPAPI_KEY": "fake-private-key"})
        self.env.start()
    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def retrieve(self, **kwargs):
        return asyncio.run(s.retrieve(self.run, self.request, "https://cse.google.com/cse?cx=test&q=Chengde", 1, 2, **kwargs))

    def test_concurrent_start_and_cache_hits_make_zero_provider_calls(self):
        started = set()
        async def fake(provider, params, timeout):
            started.add(provider)
            for _ in range(100):
                if len(started) == 2: break
                await asyncio.sleep(.001)
            self.assertEqual(started, {"serpapi", "cse"})
            return {"status": "success", "cards": [CARD], "requests": 1, "seconds": .1}
        with patch.object(s, "worker", side_effect=fake) as worker:
            first = self.retrieve()
            second = self.retrieve()
        self.assertEqual(worker.call_count, 2)
        self.assertEqual(len(first["cards"]), 1)
        self.assertEqual(first["cards"][0]["providers"], ["cse", "serpapi"])
        self.assertTrue(all(row["requests"] == 0 and row["cache"] == "hit" for row in second["providers"].values()))
        self.assertNotIn("fake-private-key", "".join(path.read_text() for path in self.run.rglob("*.json")))

    def test_blocked_partial_results_preserved_and_no_cse_retry(self):
        async def fake(provider, *args):
            return {"status": "blocked" if provider == "cse" else "success", "cards": [CARD], "requests": 1}
        with patch.object(s, "worker", side_effect=fake) as worker:
            first = self.retrieve()
            second = self.retrieve()
        self.assertEqual(first["cards"][0]["providers"], ["cse", "serpapi"])
        self.assertEqual(second["providers"]["cse"]["requests"], 0)
        self.assertEqual(worker.call_count, 2)
        self.assertEqual(len(second["cards"]), 1)

    def test_failure_does_not_lose_sibling_cards(self):
        async def fake(provider, *args):
            if provider == "cse": raise OSError("private diagnostic")
            return {"status": "success", "cards": [CARD], "requests": 1}
        with patch.object(s, "worker", side_effect=fake):
            result = self.retrieve()
        self.assertEqual(result["providers"]["cse"]["status"], "error")
        self.assertEqual(len(result["cards"]), 1)
        self.assertNotIn("private diagnostic", json.dumps(result))

    def test_expiry_and_options_change_cause_misses(self):
        fake = AsyncMock(return_value={"status": "success", "cards": [CARD], "requests": 1})
        with patch.object(s, "worker", fake):
            self.retrieve()
            self.retrieve(ttl=0)
            request = {**self.request, "place": "Beijing"}
            asyncio.run(s.retrieve(self.run, request, "https://cse.google.com/cse?cx=other", 2, 2))
        self.assertEqual(fake.call_count, 6)

    def test_missing_serpapi_key_does_not_disable_cse(self):
        with patch.dict(os.environ, {"SERPAPI_KEY": ""}), patch.object(p, "_crawl4ai_load_dotenv"), \
             patch.object(s, "worker", AsyncMock(return_value={"status": "success", "cards": [CARD]})) as worker:
            result = self.retrieve()
        self.assertEqual(worker.call_count, 1)
        self.assertEqual(result["providers"]["serpapi"]["status"], "not_configured")
        self.assertEqual(len(result["cards"]), 1)

    def test_album_does_not_collapse_different_photos(self):
        other = {**CARD, "image_url": "https://images.example/2.jpg"}
        cards = s.merge_cards({"serpapi": {"cards": [CARD, other]}, "cse": {"cards": [CARD]}})
        self.assertEqual(len(cards), 2)
        self.assertEqual(len(cards[0]["origins"]), 2)

    def test_preview_bridges_unique_original_without_collapsing_album(self):
        preview = {**CARD, "image_url": None}
        self.assertEqual(len(s.merge_cards({"serpapi": {"cards": [CARD]}, "cse": {"cards": [preview]}})), 1)
        other = {**CARD, "image_url": "https://images.example/2.jpg"}
        self.assertEqual(len(s.merge_cards({"serpapi": {"cards": [CARD, other]}, "cse": {"cards": [preview]}})), 3)

    def test_source_inspected_once_and_provenance_reaches_manifest(self):
        cards = s.merge_cards({"serpapi": {"cards": [CARD]}, "cse": {"cards": [{**CARD, "image_url": None}]}})
        page = {"url": CARD["source_url"], "html": '<title>Chengde</title><img src="https://images.example/1.jpg" alt="Chengde street 2025-08-30">'}
        with patch.object(p, "public_addresses", return_value=["93.184.216.34"]), \
             patch.object(p, "_crawl4ai_source_page", return_value=page) as fetch:
            result = p._discover_cards(self.run, cards, "https://cse.google.com/cse?cx=test", 2)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result["verified_memory_references_added"], 1)
        candidate = p.read_json(self.run / "candidates.json")[0]
        self.assertEqual(candidate["providers"], ["cse", "serpapi"])
        self.assertEqual(len(candidate["discovery_origins"]), 2)
        self.assertEqual(p.read_json(self.run / "manifest.json")["results"][0]["providers"], ["cse", "serpapi"])
        with patch.object(p, "_crawl4ai_source_page", return_value=page), patch.object(p, "public_addresses", return_value=["93.184.216.34"]):
            repeat = p._discover_cards(self.run, cards, "https://cse.google.com/cse?cx=test", 2)
        self.assertEqual(repeat["qualifying"], 1)
        self.assertEqual(repeat["verified_memory_references_added"], 0)

    def test_manifest_counts_distinct_album_images(self):
        from test_photo_research import fixture
        req, first, evidence = fixture()
        second = deepcopy(first)
        second.update(id="other-photo", image_url="https://images.example.invalid/other.jpg")
        p.write_json(self.run / "request.json", req)
        p.write_json(self.run / "candidates.json", [first, second])
        p.write_text(self.run / "evidence.jsonl", "".join(json.dumps(row) + "\n" for row in evidence.values()))
        self.assertEqual(p.build_manifest(self.run)["summary"]["qualifying_photos"], 2)

    def test_cse_challenge_preserves_prior_page_cards(self):
        calls = []
        class Config:
            def __init__(self, **kwargs): self.__dict__.update(kwargs)
        class Crawler:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def arun(self, **kwargs):
                calls.append(kwargs)
                html = ('<div class="gsc-imageResult gsc-result"><a class="gs-previewLink" href="https://archive.example/photo"></a>'
                        '<img class="gs-image" src="https://images.example/thumb.jpg"><div class="gs-previewTitle">Chengde</div></div>')
                if len(calls) > 1: html = '<p>Please verify that you are not a robot</p>'
                return SimpleNamespace(success=True, html=html)
        module = SimpleNamespace(AsyncWebCrawler=Crawler, BrowserConfig=Config, CrawlerRunConfig=Config,
                                 CacheMode=SimpleNamespace(BYPASS="bypass"))
        with patch.dict(sys.modules, {"crawl4ai": module}), self.assertRaises(p.SearchBlocked) as blocked:
            p._crawl4ai_search_pages("https://cse.google.com/cse?cx=test", 3)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(blocked.exception.cards), 1)

    def test_authenticated_urls_and_echoed_secrets_are_never_cached(self):
        self.assertIsNone(s.public_url("https://images.example/a.jpg?api_key=secret"))
        self.assertIsNone(s.public_url("https://user:pass@images.example/a.jpg"))
        cleaned = s.normalize_cards([{**CARD, "title": "fake-private-key"}], "serpapi")
        self.assertNotIn("fake-private-key", json.dumps(cleaned))

    def test_http_exception_never_exposes_authenticated_url(self):
        error = HTTPError("https://serpapi.com/search?api_key=fake-private-key", 401, "secret", None, None)
        with patch.object(s, "urlopen", side_effect=error):
            result = s.serpapi("Chengde")
        self.assertEqual(result["error"], "http_401")
        self.assertNotIn("fake-private-key", json.dumps(result))

    def test_worker_hard_timeout_kills_and_reaps(self):
        class Process:
            pid = 12345
            returncode = None
            calls = 0
            async def communicate(self, data=None):
                self.calls += 1
                if self.calls == 1: await asyncio.sleep(10)
                self.returncode = -9
                return b"", b""
        process = Process()
        with patch.object(asyncio, "create_subprocess_exec", AsyncMock(return_value=process)), \
             patch.object(s.os, "killpg") as kill:
            result = asyncio.run(s.worker("cse", {}, .01))
        self.assertEqual(result["status"], "timeout")
        kill.assert_called_once()
        self.assertEqual(process.calls, 2)


class CaptureTests(unittest.TestCase):
    current = {"place": "Chengde", "temporal": p.normalize_period(None, date(2026, 10, 2))}
    historical = {"place": "Chengde", "temporal": p.normalize_period("1980s", date(2026, 10, 2))}

    def images(self, html, request=None):
        return p._crawl4ai_source_images({"url": "https://archive.example/page", "html": html},
                                        {"title": "Chengde 1983", "text": "Chengde 1983"}, request or self.current)

    def test_current_query_and_precise_capture_date(self):
        url = p._crawl4ai_search_url("https://cse.google.com/cse?cx=test&api_key=secret", self.current)
        query = parse_qs(urlsplit(url).query)["q"][0]
        self.assertIn("现在", query)
        self.assertNotIn("老照片", query)
        self.assertNotIn("secret", url)
        images = self.images('<title>Chengde photos</title><img src="/recent.jpg" alt="Chengde street 2025-08-30">')
        self.assertEqual(images[0]["scene_date"]["precision"], "day")

    def test_publication_or_upload_year_is_not_capture_date(self):
        self.assertIsNone(p._crawl4ai_scene_date("Uploaded on 1983", self.historical["temporal"]))
        self.assertIsNone(p._crawl4ai_scene_date("Taken on October 1, 1920 Uploaded on October 1, 1983", self.historical["temporal"]))
        html = '<title>Chengde 1983 photos</title><meta name="datePublished" content="1983-01-01"><img src="/a.jpg" alt="Chengde street">'
        self.assertEqual(self.images(html, self.historical), [])

    def test_search_title_never_dates_all_images_in_article(self):
        html = '<title>Chengde 1983 photos</title><p>Chengde 1983</p><img src="/a.jpg" alt="Chengde 1983 photos"><img src="/b.jpg" alt="Chengde street">'
        self.assertEqual(self.images(html, self.historical), [])

    def test_each_figure_retains_its_own_capture_date(self):
        html = '<title>Chengde archive</title><figure><img src="/a.jpg"><figcaption>Chengde street 1983</figcaption></figure><figure><img src="/b.jpg"><figcaption>Chengde street 2025</figcaption></figure>'
        self.assertEqual([row["image_url"] for row in self.images(html, self.historical)], ["https://archive.example/a.jpg"])

    def test_photo_metadata_date_is_bound_to_its_image(self):
        metadata = {"@type": "Photograph", "name": "Chengde street", "dateCreated": "2025-08-30", "contentUrl": "https://images.example/current.jpg"}
        html = '<title>Chengde photos</title><script type="application/ld+json">' + json.dumps(metadata) + '</script><img src="/unrelated.jpg" alt="Chengde street">'
        self.assertEqual([row["image_url"] for row in self.images(html)], [metadata["contentUrl"]])
        metadata["@type"] = "Article"
        html = '<title>Chengde</title><script type="application/ld+json">' + json.dumps(metadata) + '</script>'
        self.assertEqual(self.images(html), [])

    def test_mixed_years_and_future_dates_do_not_qualify(self):
        self.assertIsNone(p._crawl4ai_scene_date("Chengde 1920 1983", self.historical["temporal"]))
        self.assertIsNone(p._crawl4ai_scene_date("Chengde 2026", self.current["temporal"]))
        self.assertIsNone(p._crawl4ai_scene_date("Chengde 2027-01-01", self.current["temporal"]))

    def test_unspecified_old_request_does_not_promote_recent_photo(self):
        request = {"place": "Chengde", "as_of": "2026-10-02", "recent_months": 24,
                   "temporal": p.normalize_period("historical", date(2026, 10, 2))}
        html = '<title>Chengde photos</title><img src="/old.jpg" alt="Chengde street 1983"><img src="/recent.jpg" alt="Chengde street 2025">'
        self.assertEqual([row["image_url"] for row in self.images(html, request)], ["https://archive.example/old.jpg"])


if __name__ == "__main__": unittest.main()
