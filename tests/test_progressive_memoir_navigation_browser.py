"""Saved canonical drafts coexist with durable history, navigation and map albums.

The source frontend, Chromium, PostgreSQL, story API and composer worker are real.
External authentication/project metadata/model/photo/imagery boundaries are controlled.
"""
import json
import os

import pytest
from playwright.sync_api import expect, sync_playwright
from browser_optional_fonts import control_optional_fonts

from test_shared_memory_events_postgres import (
    database, attachment_database, private_database, event_database, sql,
    ROOT, OWNER, rpc, five_rounds, run_controlled_composer, story_client,
)
from memoir_postgres_workflow import PostgresRest

pytestmark = pytest.mark.skipif(not os.getenv("MEMOIR_BROWSER_URL"), reason="Requires isolated source frontend")


@pytest.mark.parametrize("locale", ["en-AU", "zh-CN"])
def test_saved_draft_and_map_survive_landing_reentry_and_a_fresh_tab_without_reseeding_history(sql, tmp_path, monkeypatch, locale):
    original = "I started school around 1964."
    prose = original if locale == "en-AU" else "我大约在1964年开始上学。"
    place = {
        "place": "承德", "hierarchy": ["Earth", "中国", "河北", "承德"], "granularity": "city",
        "latitude": 40.97, "longitude": 117.93, "period": "1960s", "revision": 1,
        "status": "active", "schema_version": 1, "photo_search_period": "1960s",
        "photo_search_policy": "place-fallback-gps-time-v8", "photo_search_place": "承德",
        "photo_search_complete": True, "photo_search_at": 1,
        "photo_search_latitude": 40.97, "photo_search_longitude": 117.93,
        "pictures": [{
            "asset_id": "synthetic-map-reference", "title": "Synthetic dated public reference",
            "image_url": "/static/issue6-map-reference.svg", "source_url": "https://archive.example/item",
            "attribution": "Synthetic test archive", "date_expression": "1964",
            "latitude": 40.97, "longitude": 117.93, "allowed_actions": {"embed": True},
        }],
    }
    profile = {"preferred_language": locale, "memory_places": [place]}
    PostgresRest(sql, OWNER).storage().save_profile(profile)
    _, lanes = five_rounds(sql, text=original)
    assert run_controlled_composer(sql, tmp_path, monkeypatch, lanes["composer_lane_id"], prose=prose,
        control_options={"title": "Starting school" if locale == "en-AU" else "开始上学"})["status"] == "saved"
    canonical_before = rpc(sql, "read_user_memory_events", "'project'")
    project = {"id": "project", "revision": 1, "profile": profile, "mode": "self",
               "workspace_unlocked": False, "requires_supabase_auth": True}
    copy = json.loads((ROOT / f"apps/web/messages/{locale}.json").read_text())["Memoir"]["workspace"]
    base = os.environ["MEMOIR_BROWSER_URL"]
    requests = []
    errors = []
    with story_client(sql) as client, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 390, "height": 844}, reduced_motion="reduce")
        context.add_cookies([{"name": "copyme2_ui_locale", "value": locale, "url": base},
                            {"name": "copyme2_ui_locale_source", "value": "fixed", "url": base}])
        def boundary(route):
            if route.request.url.startswith(base) or any(host in route.request.url for host in
                    ("cesium.com/", "fonts.googleapis.com/", "fonts.gstatic.com/")):
                return route.continue_()
            route.abort()
        context.route("**/*", boundary)
        def cesium(route):
            response = route.fetch()
            route.fulfill(response=response, body=response.text() +
                "\nCesium.Google2DImageryProvider.fromUrl=async()=>new Cesium.GridImageryProvider();")
        context.route("**/Build/Cesium/Cesium.js", cesium)
        context.route("**/static/issue6-map-reference.svg", lambda route: route.fulfill(
            content_type="image/svg+xml", body='<svg xmlns="http://www.w3.org/2000/svg" width="320" height="220"><rect width="320" height="220" fill="#c4d8d2"/></svg>'))
        def api(route):
            path = route.request.url.split("/api/v1/memoir")[-1]
            endpoint = path.split("?")[0]
            requests.append((route.request.method, endpoint))
            if endpoint.startswith("/story/private-draft"):
                response = client.request(route.request.method, "/v1" + path,
                    headers={"Authorization": "Bearer synthetic-author", "Content-Type": "application/json"},
                    content=route.request.post_data or None)
                return route.fulfill(status=response.status_code, content_type="application/json", body=response.text)
            if endpoint == "/projects" and route.request.method == "POST":
                return route.fulfill(status=409, json={"detail": "This acceptance fixture must resume its existing project"})
            data = {}
            if endpoint == "/agent/config":
                data = {"supabase_url": "https://auth.test", "supabase_publishable_key": "public",
                        "auth_mode": "supabase", "google_maps_browser_api_key": "synthetic-key",
                        "show_thinking_steps": True}
            elif endpoint in ("/agent/profile", "/user/profile"):
                data = profile
            elif endpoint == "/projects/project":
                data = project
            elif endpoint == "/projects/project/journey":
                data = {"active_session": None}
            elif endpoint == "/story/state":
                data = {"family_features_enabled": False, "payment_features": [],
                        "recall_status": {"rounds_completed": 5, "free_rounds": 20, "payment_required": False, "paid": False}}
            elif endpoint == "/agent/family-context":
                data = {"family_features_enabled": False, "family_context": None}
            elif endpoint == "/agent/place-journey":
                data = {"place_journey": None}
            elif endpoint in ("/projects", "/user/projects"):
                data = {"items": [project]}
            elif endpoint == "/user/conversations" or endpoint.startswith("/projects/project/") or endpoint.startswith("/user/projects/"):
                data = {"items": []}
            return route.fulfill(json=data)
        context.route("**/api/v1/memoir/**", api)
        user = {"id": OWNER, "is_anonymous": False, "user_metadata": {"ui_locale": locale}}
        sdk = f"window.supabase={{createClient:()=>({{auth:{{getSession:async()=>({{data:{{session:{{access_token:'synthetic-author',user:{json.dumps(user)}}}}}}}),getUser:async()=>({{data:{{user:{json.dumps(user)}}}}}),onAuthStateChange:()=>({{}})}}}})}};"
        context.route("https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2", lambda route:
            route.fulfill(content_type="text/javascript", body=sdk))
        # Seed only the first visit. Reload/new-tab acceptance cannot recreate the
        # history through an init script or a mocked history response.
        initial = json.dumps([{"id": "original-memory", "role": "user", "text": original}])
        context.add_init_script(f"""
          if (!localStorage.getItem('issue6-initialized')) {{
            localStorage.setItem('issue6-initialized','true');
            localStorage.setItem('memory-spark-project','project');
            sessionStorage.setItem('memory-spark-chat-history:{OWNER}:project',{json.dumps(initial)});
          }}
        """)
        page = context.new_page()
        control_optional_fonts(page)
        page.on("pageerror", lambda error: errors.append(str(error)))
        interview = base + "/memoir/interview/project"
        page.goto(interview, wait_until="networkidle")
        status = page.locator(".private-draft-status")
        saved_copy = copy["privateDraftSaved"].replace("{round}", "5")
        expect(status).to_contain_text(saved_copy, timeout=30000)
        status.locator("summary").click()
        expect(status).to_contain_text(prose)
        expect(page.locator(".chat-scroll")).to_contain_text(original)
        expect(page.locator(".place-journey-scene.is-cesium-map")).to_be_visible(timeout=30000)
        page.locator(".story-topbar .brand-name").click()
        expect(page).to_have_url(base + "/memoir")
        page.wait_for_load_state("networkidle")
        page.locator('[data-action="start-story"][data-mode="self"]').click()
        expect(page).to_have_url(interview)
        expect(page.locator(".chat-scroll")).to_contain_text(original)
        expect(page.locator(".private-draft-status")).to_contain_text(saved_copy)
        page.locator("[data-photo-album]:visible").first.click()
        expect(page.get_by_role("dialog")).to_be_visible()
        expect(page).to_have_url(interview)
        page.go_back()
        expect(page.get_by_role("dialog")).not_to_be_visible()
        expect(page.locator(".private-draft-status")).to_contain_text(saved_copy)
        page.evaluate("sessionStorage.clear()")
        second = context.new_page()
        second.on("pageerror", lambda error: errors.append(str(error)))
        second.goto(interview, wait_until="networkidle")
        expect(second.locator(".chat-scroll")).to_contain_text(original)
        expect(second.locator(".private-draft-status")).to_contain_text(saved_copy)
        expect(second.locator(".place-journey-scene.is-cesium-map")).to_be_visible(timeout=30000)
        expect(second.locator("#chat-input")).to_be_enabled()
        assert ("POST", "/projects") not in requests
        assert rpc(sql, "read_user_memory_events", "'project'") == canonical_before
        assert not errors, errors
        browser.close()
