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
import unittest
from unittest.mock import patch

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

if __name__ == '__main__': unittest.main()
