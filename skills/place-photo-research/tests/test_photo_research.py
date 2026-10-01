"""Offline unit/integration tests. No real archive or search-provider calls."""
import contextlib
from copy import deepcopy
from datetime import date
import importlib.util
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "photo_research.py"
spec = importlib.util.spec_from_file_location("photo_research", SCRIPT)
p = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = p
spec.loader.exec_module(p)

ASOF = date(2026, 9, 26)

def fixture():
    req = {"schema_version":"1.0","place":"Chengde, Hebei","subject":"streets", "as_of":ASOF.isoformat(),
           "timezone":"Australia/Sydney","temporal":p.normalize_period(None,ASOF),"recent_months":24,
           "usage":"commercial-memoir","count":3,"budgets":{"max_queries":8,"max_pages":12}}
    evs = {}
    for kind in ("place", "scene_date", "license", "access_terms"):
        eid = "ev-"+kind
        evs[eid] = {"id":eid,"kind":kind,"url":"https://example.invalid/item/1","locator":"Synthetic test field",
                    "excerpt":"SYNTHETIC TEST ONLY", "observed_at":"2026-09-26T00:00:00+00:00"}
    c = {"id":"photo-001","title":"SYNTHETIC TEST PHOTO","source_page_url":"https://example.invalid/item/1",
         "image_url":"https://images.example.invalid/photo.png","creator":"Test Creator",
         "authenticity":"source_described_photograph",
         "place":{"match":"exact","evidence_ids":["ev-place"]},
         "scene_date":{"start":"2025-01-01","end":"2025-12-31","precision":"year","basis":"source_caption","conflicting":False,"evidence_ids":["ev-scene_date"]},
         "rights":{"scope":"item","download_permitted":True,"commercial_use_permitted":True,"license_id":"CC-BY-4.0",
                   "license_url":p.LICENSE_URLS["CC-BY-4.0"],"attribution":"Test Creator — CC BY 4.0","evidence_ids":["ev-license"]},
         "acquisition":{"access_permitted":True,"allowed_hosts":["images.example.invalid"],"evidence_ids":["ev-access_terms"]}}
    return req,c,evs

def png_bytes():
    from PIL import Image
    buf=io.BytesIO()
    Image.new("RGB",(8,6)).save(buf,format="PNG")
    return buf.getvalue()

class TemporalTests(unittest.TestCase):
    def test_missing_is_current(self): self.assertEqual(p.normalize_period(None,ASOF)["mode"],"current")
    def test_empty_is_current(self): self.assertEqual(p.normalize_period("",ASOF)["basis"],"absent_period_default")
    def test_current_window(self): self.assertEqual(p.normalize_period(None,ASOF)["start"],"2024-09-26")
    def test_decade(self):
        r=p.normalize_period("1980s",ASOF); self.assertEqual((r["start"],r["end"]),("1980-01-01","1989-12-31"))
    def test_bare_year_starts_ten_year_window(self):
        r=p.normalize_period("1980",ASOF)
        self.assertEqual((r["start"],r["end"],r["precision"]),("1980-01-01","1989-12-31","decade_from_year"))
        self.assertEqual(p.normalize_period("1980年",ASOF)["end"],"1989-12-31")
    def test_chinese_numeric_decade(self): self.assertEqual(p.normalize_period("1980年代",ASOF)["end"],"1989-12-31")
    def test_old_unknown(self): self.assertEqual(p.normalize_period("old",ASOF)["mode"],"historical_unspecified")
    def test_now_explicit(self): self.assertEqual(p.normalize_period("现在",ASOF)["basis"],"explicit_current")
    def test_today_strict(self):
        r=p.normalize_period("today",ASOF); self.assertEqual(r["start"],r["end"])
    def test_last_year(self): self.assertEqual(p.normalize_period("last year",ASOF)["end"],"2025-12-31")
    def test_leap_arithmetic(self): self.assertEqual(p.subtract_months(date(2024,2,29),12),date(2023,2,28))
    def test_iso_range(self): self.assertEqual(p.normalize_period("1983-02-01..1983-03-01",ASOF)["precision"],"range")
    def test_future_rejected(self):
        with self.assertRaises(p.ResearchError): p.normalize_period("2030",ASOF)
    def test_reversed_rejected(self):
        with self.assertRaises(p.ResearchError): p.normalize_period("1990-1980",ASOF)
    def test_ambiguous_century_not_guessed(self):
        with self.assertRaises(p.ResearchError): p.normalize_period("80s",ASOF)
    def test_previous_period_not_an_input(self):
        p.normalize_period("1980s",ASOF)
        self.assertEqual(p.normalize_period(None,ASOF)["mode"],"current")

class EligibilityTests(unittest.TestCase):
    def setUp(self): self.req,self.c,self.ev=fixture()
    def verdict(self): return p.evaluate(self.c,self.req,self.ev)
    def test_eligible(self): self.assertTrue(self.verdict()["eligible_for_local_download"])
    def test_uploaded_recent_old_scene_not_current(self):
        self.c["uploaded_at"]="2026-09-26"
        self.c["scene_date"].update(start="1983-01-01",end="1983-12-31")
        self.assertIn("DATE_OUT_OF_RANGE",self.verdict()["reason_codes"])
    def test_upload_date_is_not_scene_evidence(self):
        self.c["scene_date"]["basis"]="upload_date"
        self.assertIn("DATE_UNKNOWN",self.verdict()["reason_codes"])
    def test_unknown_capture_not_current(self):
        self.c["scene_date"].update(start=None,end=None,basis="unknown")
        self.assertFalse(self.verdict()["eligible_for_local_download"])
    def test_overlap_not_exact(self):
        self.c["scene_date"].update(start="2024-01-01",end="2025-12-31")
        self.assertEqual(self.verdict()["date_status"],"overlap")
    def test_wrong_place(self):
        self.c["place"]["match"]="wrong"
        self.assertIn("PLACE_NOT_VERIFIED_EXACT",self.verdict()["reason_codes"])
    def test_rights_unknown(self):
        self.c["rights"]["download_permitted"]=None
        self.assertFalse(self.verdict()["eligible_for_local_download"])
    def test_commercial_permission_required(self):
        self.c["rights"]["commercial_use_permitted"]=False
        self.assertFalse(self.verdict()["eligible_for_local_download"])
    def test_personal_still_requires_permission(self):
        self.req["usage"]="personal-reference"; self.c["rights"]["download_permitted"]=None
        self.assertFalse(self.verdict()["eligible_for_local_download"])
    def test_unsupported_license_not_relabelled(self):
        self.c["rights"]["license_id"]="CC-BY-NC-2.0"
        self.assertIn("LICENSE_REQUIRES_MANUAL_PERMISSION_REVIEW",self.verdict()["reason_codes"])
    def test_missing_attribution_null_safe(self):
        self.c["rights"]["attribution"]=None
        self.assertIn("ATTRIBUTION_MISSING",self.verdict()["reason_codes"])
    def test_licence_url_null_safe(self):
        self.c["rights"]["license_url"]=None
        self.assertIn("LICENSE_URL_MISMATCH",self.verdict()["reason_codes"])
    def test_source_footer_not_item_license(self):
        self.c["rights"]["scope"]="website"
        self.assertIn("RIGHTS_NOT_ITEM_SCOPED",self.verdict()["reason_codes"])
    def test_conflicting_date(self):
        self.c["scene_date"]["conflicting"]=True
        self.assertIn("DATE_CONFLICT_UNRESOLVED",self.verdict()["reason_codes"])
    def test_custom_requires_permission_evidence(self):
        self.c["rights"]["license_id"]="custom-permission"
        self.assertIn("CUSTOM_PERMISSION_NOT_DOCUMENTED",self.verdict()["reason_codes"])
    def test_access_requires_evidence(self):
        self.c["acquisition"]["evidence_ids"]=[]
        self.assertIn("ACQUISITION_ACCESS_NOT_DOCUMENTED",self.verdict()["reason_codes"])
    def test_old_unspecified_not_recent(self):
        self.req["temporal"]=p.normalize_period("old",ASOF)
        self.assertEqual(self.verdict()["date_status"],"not_established_as_old")
    def test_no_publication_grant(self):
        self.assertEqual(self.verdict()["publication_status"],"not_approved_by_this_local_skill")

class SecurityTests(unittest.TestCase):
    def test_url_schemes(self):
        for url in ["file:///etc/passwd","javascript:alert(1)","data:image/png,x"]:
            with self.assertRaises(p.ResearchError): p.valid_url(url)
    def test_url_credentials(self):
        with self.assertRaises(p.ResearchError): p.valid_url("https://user:pass@example.com/")
    def test_url_controls(self):
        for url in ["https://example.com/a\nb","https://example.com/a b","https://example.com/<x>"]:
            with self.assertRaises(p.ResearchError): p.valid_url(url)
    def test_loopback_dns_blocked(self):
        with patch.object(socket,"getaddrinfo",return_value=[(2,1,6,"",("127.0.0.1",443))]):
            with self.assertRaises(p.ResearchError): p.public_addresses("example.com",443)
    def test_mixed_public_private_dns_blocked(self):
        rows=[(2,1,6,"",("93.184.216.34",443)),(2,1,6,"",("10.0.0.1",443))]
        with patch.object(socket,"getaddrinfo",return_value=rows):
            with self.assertRaises(p.ResearchError): p.public_addresses("example.com",443)
    def test_public_dns_allowed(self):
        with patch.object(socket,"getaddrinfo",return_value=[(2,1,6,"",("93.184.216.34",443))]):
            self.assertEqual(p.public_addresses("example.com",443),["93.184.216.34"])
    def test_explicit_host_gate_before_fetch(self):
        with self.assertRaises(p.ResearchError): p.Fetcher().fetch("https://evil.example/a",10,{"example.com"},check_robots=False)
    def test_path_traversal(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(p.ResearchError): p.checked_path(Path(t),"../escape.txt")
    def test_symlink_output(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t); (root/"link").symlink_to(root/"target")
            with self.assertRaises(p.ResearchError): p.checked_path(root,"link")
    def test_verified_image(self): self.assertEqual(p.image_info(png_bytes(),"image/png")["width"],8)
    def test_mime_mismatch(self):
        with self.assertRaises(p.ResearchError): p.image_info(png_bytes(),"text/html")
    def test_html_disguised_as_image(self):
        with self.assertRaises(p.ResearchError): p.image_info(b"<script>alert(1)</script>","image/png")
    def test_robots_disallow(self):
        fetcher=p.Fetcher()
        with patch.object(fetcher,"fetch",return_value=(200,"https://example.com/robots.txt",{},b"User-agent: *\nDisallow: /private")):
            with self.assertRaises(p.ResearchError): fetcher.robot_check("https://example.com/private/photo",{"example.com"})
    def test_robots_error_fails_closed(self):
        fetcher=p.Fetcher()
        with patch.object(fetcher,"fetch",return_value=(503,"https://example.com/robots.txt",{},b"")):
            with self.assertRaises(p.ResearchError): fetcher.robot_check("https://example.com/a",{"example.com"})

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.run=Path(self.tmp.name)
        self.req,self.c,self.ev=fixture()
        p.write_json(self.run/"request.json",self.req); p.write_json(self.run/"candidates.json",[self.c])
        p.write_text(self.run/"evidence.jsonl","".join(json.dumps(e)+"\n" for e in self.ev.values()))
        p.write_text(self.run/"search_log.jsonl","")
    def tearDown(self): self.tmp.cleanup()
    def test_init_cli_current(self):
        with tempfile.TemporaryDirectory() as t,contextlib.redirect_stdout(io.StringIO()):
            code=p.main(["init","--place","Chengde","--out",t,"--as-of","2026-09-26"])
            self.assertEqual(code,0); self.assertEqual(p.read_json(Path(t)/"request.json")["temporal"]["mode"],"current")

    def test_crawl4ai_cli_dispatch(self):
        summary = {"qualifying": 10, "target": 10, "shortfall": 0}
        with patch.object(p, "crawl4ai_discover", return_value=summary) as discover, \
             contextlib.redirect_stdout(io.StringIO()):
            code = p.main(["crawl4ai", "--run", str(self.run),
                           "--search-url", "https://cse.google.com/cse?cx=test",
                           "--max-search-pages", "2", "--source-limit", "3"])
        self.assertEqual(code, 0)
        discover.assert_called_once_with(self.run.resolve(), "https://cse.google.com/cse?cx=test",
                                         max_search_pages=2, source_limit=3)

    def test_crawl4ai_search_url_adds_decade_and_removes_paging_query(self):
        request = {"place": "Chengde, Hebei, China / 河北承德",
                   "temporal": p.normalize_period("1980", ASOF)}
        url = p._crawl4ai_search_url("https://cse.google.com/cse?cx=test&start=11", request)
        params = parse_qs(urlsplit(url).query)
        self.assertEqual(params["q"], ['("Chengde" OR "承德") 1980年代 老照片'])
        self.assertNotIn("start", params)

    def test_chengde_landmark_aliases_keep_city_and_memory_period(self):
        request = {"place": "离宫, 承德市", "temporal": p.normalize_period("1983", ASOF)}
        query = parse_qs(urlsplit(p._crawl4ai_search_url("https://cse.google.com/cse?cx=test", request)).query)["q"][0]
        for term in ('"离宫"', '"避暑山庄"', '"Mountain Resort"', '"summer palace"', '"承德"', '"Chengde"', '1983-1992'):
            self.assertIn(term, query)
        self.assertTrue(p._crawl4ai_location_matches("Chengde Mountain Resort 1983", request["place"]))
        self.assertFalse(p._crawl4ai_location_matches("Beijing Summer Palace 1983", request["place"]))
    def test_init_photo_count(self):
        for count_args, expected in (([], 10), (["--count", "15"], 15), (["--count", "3"], 3)):
            with self.subTest(count_args=count_args), tempfile.TemporaryDirectory() as t, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(p.main(["init", "--place", "Chengde", "--out", t, *count_args]), 0)
                request = p.read_json(Path(t) / "request.json")
                self.assertEqual(request["count"], expected)
                self.assertEqual(request["budgets"], {"max_queries": 40, "max_pages": 80})

    def test_report_marks_duplicate_shortfall(self):
        import copy
        duplicate = copy.deepcopy(self.c)
        duplicate["id"] = "duplicate-photo"
        p.write_json(self.run / "candidates.json", [self.c, duplicate])
        manifest = p.build_manifest(self.run)
        self.assertEqual(manifest["summary"]["qualifying_photos"], 1)
        self.assertEqual(manifest["summary"]["shortfall"], 2)
        self.assertEqual(manifest["summary"]["status"], "incomplete")

    def test_budget(self):
        for i in range(8): p.log_event(self.run,"search",str(i),[])
        with self.assertRaises(p.ResearchError): p.log_event(self.run,"search","ninth",[])
    def test_missing_evidence_reference(self):
        self.c["place"]["evidence_ids"]=["nonexistent"];p.write_json(self.run/"candidates.json",[self.c])
        with self.assertRaises(p.ResearchError): p.load_records(self.run)
    def test_evidence_without_timezone(self):
        ev=list(self.ev.values()); ev[0]["observed_at"]="2026-09-26T00:00:00"
        p.write_text(self.run/"evidence.jsonl","".join(json.dumps(e)+"\n" for e in ev))
        with self.assertRaises(p.ResearchError): p.load_records(self.run)
    def test_download_and_resume(self):
        with patch.object(p.Fetcher,"fetch",return_value=(200,self.c["image_url"],{"content-type":"image/png"},png_bytes())) as m:
            first=p.build_manifest(self.run,download=True);second=p.build_manifest(self.run,download=True)
            self.assertEqual(first["summary"]["downloaded"],1);self.assertEqual(second["summary"]["downloaded"],1)
            self.assertEqual(m.call_count,1)
    def test_download_failure_reported(self):
        with patch.object(p.Fetcher,"fetch",side_effect=p.ResearchError("blocked")):
            result=p.build_manifest(self.run,download=True)
            self.assertEqual(result["results"][0]["download_status"],"failed")
    def test_rights_block_no_network(self):
        self.c["rights"]["download_permitted"]=None;p.write_json(self.run/"candidates.json",[self.c])
        with patch.object(p.Fetcher,"fetch") as m:
            result=p.build_manifest(self.run,download=True);m.assert_not_called()
            self.assertEqual(result["results"][0]["download_status"],"blocked")
    def test_gallery_escapes_untrusted_content(self):
        self.c["title"]='<script>alert(1)</script> ![remote](https://evil.example/a)'
        p.write_json(self.run/"candidates.json",[self.c]);p.build_manifest(self.run)
        page=(self.run/"gallery.html").read_text();md=(self.run/"report.md").read_text()
        self.assertNotIn('<script>',page);self.assertNotIn('![remote](',md)
        self.assertNotIn('<img',page)
    def test_sha_dedup(self):
        c2=deepcopy(self.c);c2["id"]="photo-002";c2["image_url"]="https://images.example.invalid/other.png"
        p.write_json(self.run/"candidates.json",[self.c,c2])
        with patch.object(p.Fetcher,"fetch",return_value=(200,self.c["image_url"],{"content-type":"image/png"},png_bytes())):
            m=p.build_manifest(self.run,download=True)
            self.assertEqual(m["summary"]["unique_files"],1)
    def test_page_parser_preserves_figure(self):
        parser=p.PageParser("https://example.com/a")
        parser.feed('<figure><img src="/1.jpg"><figcaption>Chengde 1983</figcaption></figure><script>ignore()</script>')
        out=parser.output();self.assertEqual(out["image_candidates"][0]["figure_text"],"Chengde 1983")
        self.assertNotIn("ignore()",out["text_excerpt"])

    def test_crawl4ai_image_parser_keeps_source_links_and_thumbnails(self):
        html = '''
        <div class="gsc-results gsc-imageResult"><div class="gsc-expansionArea">
          <div class="gsc-result gsc-imageResult">
            <img class="gs-image gs-image-scalable" src="https://encrypted-tbn0.gstatic.com/thumb.jpg"
                 alt="Chengde 1983 street" width="640" height="480">
            <a class="gs-previewLink" href="https://archive.example/item/1">item</a>
            <div class="gs-previewTitle">Chengde 1983 street</div>
            <div class="gs-previewDescription">Chengde 1980s photograph</div>
          </div>
        </div></div>'''
        results = p.parse_crawl4ai_image_results(html)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source_url"], "https://archive.example/item/1")
        self.assertEqual(results[0]["preview_url"], "https://encrypted-tbn0.gstatic.com/thumb.jpg")
        self.assertIn("1980s", results[0]["text"])

    def test_crawl4ai_search_wrapper_collects_paginated_cards(self):
        def card(page_number):
            return f'''<div class="gsc-imageResult gsc-result">
              <img class="gs-image" src="https://encrypted-tbn0.gstatic.com/{page_number}.jpg" alt="Chengde 198{page_number} street">
              <a class="gs-previewLink" href="https://archive.example/item/{page_number}">item</a>
              <div class="gs-previewTitle">Chengde 198{page_number} street</div>
              <div class="gs-previewDescription">Chengde 1980s photograph</div>
            </div>'''

        calls, pages_seen = [], []
        html_pages = [card(1), card(2)]

        class FakeCrawler:
            def __init__(self, config): self.config = config
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return None
            async def arun(self, url, config):
                calls.append((url, config))
                return types.SimpleNamespace(success=True, error_message="", status_code=200,
                                            html=html_pages[len(calls) - 1])

        fake_module = types.SimpleNamespace(
            AsyncWebCrawler=FakeCrawler,
            BrowserConfig=lambda **kwargs: kwargs,
            CacheMode=types.SimpleNamespace(BYPASS="bypass"),
            CrawlerRunConfig=lambda **kwargs: types.SimpleNamespace(**kwargs),
        )
        with patch.dict(sys.modules, {"crawl4ai": fake_module}):
            cards = p._crawl4ai_search_pages("https://cse.google.com/cse?cx=test", 2,
                                              before_page=lambda number, url: pages_seen.append(number))
        self.assertEqual(pages_seen, [1, 2])
        self.assertEqual([card["search_page"] for card in cards], [1, 2])
        self.assertEqual(len(calls), 2)
        self.assertFalse(calls[0][1].js_only)
        self.assertTrue(calls[1][1].js_only)

    def test_crawl4ai_discovery_paginates_source_pages_and_filters_metadata(self):
        self.req.update({"temporal": p.normalize_period("1980s", ASOF), "count": 10})
        p.write_json(self.run / "request.json", self.req)
        p.write_json(self.run / "candidates.json", [])
        p.write_text(self.run / "evidence.jsonl", "")
        cards = [{"source_url": f"https://archive.example/item/{i}",
                  "title": "Chengde 1980s street photo", "text": "Chengde 1980s photograph"}
                 for i in range(1, 13)]
        source_pages = {
            card["source_url"]: {
                "url": card["source_url"],
                "title": card["title"],
                "text": "Chengde 1983 street photograph",
                "media": [{"src": f"https://images.example/{i}.jpg", "alt": "Chengde street 1983",
                           "desc": "Chengde 1983 street photograph", "width": 1200, "height": 800}],
            }
            for i, card in enumerate(cards, 1)
        }
        with patch.object(p, "_crawl4ai_search_pages", return_value=cards), \
             patch.object(p, "_crawl4ai_source_page", side_effect=lambda url: source_pages[url]), \
             patch.object(p, "public_addresses", return_value=["93.184.216.34"]):
            summary = p.crawl4ai_discover(self.run, "https://cse.google.com/cse?cx=test", max_search_pages=2,
                                           source_limit=12)
        self.assertEqual(summary["qualifying"], 10)
        self.assertEqual(summary["manifest"]["memory_references"], 10)
        candidates = p.read_json(self.run / "candidates.json")
        self.assertEqual(len(candidates), 10)
        self.assertTrue(all(candidate["memory_reference_only"] for candidate in candidates))
        self.assertTrue(all(candidate["rights"]["license_id"] == "unknown" for candidate in candidates))
        events = p.read_jsonl(self.run / "search_log.jsonl")
        self.assertEqual(sum(event["kind"] == "search" for event in events), 1)
        self.assertEqual(sum(event["kind"] == "page" for event in events), 11)

    def test_crawl4ai_source_filter_drops_related_media(self):
        request = {"place": "Chengde, Hebei", "temporal": p.normalize_period("1980s", ASOF)}
        page = {"url": "https://archive.example/item/1", "title": "Chengde 1980s photographs",
                "text": "Chengde 1980s photographs", "markdown": "",
                "media": [{"src": "https://images.example/historical.jpg", "alt": "Chengde 1983 street photo",
                           "desc": "Chengde 1983 street photo"},
                          {"src": "https://images.example/related.jpg", "alt": "Football highlights",
                           "desc": "Latest football match highlights"},
                          {"src": "https://images.example/banknote.jpg", "alt": "Chengde 1983 banknote photo",
                           "desc": "Currency scan"}]}
        card = {"title": "Chengde 1980s photographs", "text": "Chengde 1980s photographs"}
        images = p._crawl4ai_source_images(page, card, request)
        self.assertEqual([item["image_url"] for item in images], ["https://images.example/historical.jpg"])

    def test_crawl4ai_image_url_upgrades_observed_http_cdn(self):
        observed = "http://k.sinaimg.cn/n/sinacn/w550h329/20180116/photo.png/w700d1q75cms.jpg"
        self.assertEqual(
            p._crawl4ai_image_url(observed),
            observed.replace("http://", "https://", 1),
        )

if __name__ == '__main__': unittest.main()
