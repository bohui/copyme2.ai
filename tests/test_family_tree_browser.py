"""Family tree selection with synthetic people and the actual pinned renderer."""
import json
import os
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen

import pytest
from PIL import Image
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.skipif(not os.getenv("MEMOIR_BROWSER_URL"), reason="Requires source frontend")
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def chart_assets():
    urls = ["https://unpkg.com/d3@7.9.0/dist/d3.min.js",
            "https://unpkg.com/family-chart@0.9.0/dist/family-chart.min.js",
            "https://unpkg.com/family-chart@0.9.0/dist/styles/family-chart.css"]
    return {url: urlopen(url, timeout=30).read() for url in urls}


@pytest.mark.parametrize("locale,width", [("en-AU", 1440), ("zh-CN", 390)])
@pytest.mark.parametrize("renderer_available", [True, False])
def test_person_introductions_and_author_marker(locale, width, renderer_available, chart_assets):
    workspace = json.loads((ROOT / f"apps/web/messages/{locale}.json").read_text())["Memoir"]["workspace"]
    profile = {"name": "Avery", "preferred_language": locale}
    project = {"id": "family-ui-project", "profile": profile, "mode": "self", "revision": 1,
               "workspace_unlocked": True, "composition_stage": 3}
    people = [{"id": "me", "name": "Avery", "introduction": "I grew up beside a small garden."},
              {"id": "mum", "name": "Mei", "family_title": "mother", "aliases": ["Mum"],
               "birth_date_expression": "around 1940", "introduction": "She grew roses. <script>not executable</script>"},
              {"id": "uncle", "name": "Bo", "family_title": "uncle"}]
    family = {"project_id": "family-ui-project", "revision": 1, "people": people, "relationships": [{"from_person_id": "mum", "to_person_id": "me", "relationship_type": "parent"}], "timeline": []}
    image = BytesIO()
    Image.new("RGB", (128, 160), "#b6cfb1").save(image, format="PNG")
    photo = image.getvalue()
    uploads = []
    upload_failure = False

    def api(route):
        path = route.request.url.split("/api/v1/memoir")[-1].split("?")[0]
        data = {}
        if path == "/agent/config":
            data = {"supabase_url": "https://auth.test", "supabase_publishable_key": "public", "auth_mode": "supabase"}
        elif path in ("/agent/profile", "/user/profile"): data = profile
        elif path == "/projects/family-ui-project": data = project
        elif path == "/projects/family-ui-project/journey": data = {"active_session": None}
        elif path == "/story/state":
            data = {"family_features_enabled": True, "payment_features": ["family_tree", "timeline"],
                    "recall_status": {"rounds_completed": 25, "free_rounds": 20, "paid": True, "payment_required": False}}
        elif path == "/agent/family-context": data = {"family_features_enabled": True, "family_context": family}
        elif path == "/agent/family-context/family-ui-project/people/mum/photo":
            if upload_failure:
                return route.fulfill(status=503, content_type="application/json", body='{"detail":"Photo unavailable"}')
            if route.request.method == "PUT":
                uploads.append(route.request.post_data_buffer)
                assert route.request.headers["content-type"] == "image/png"
                people[1]["photo_path"] = f"private/mum-{len(uploads)}.jpg"
                people[1]["photo_url"] = f"https://photos.test/mum-{len(uploads)}.png"
            else:
                people[1].pop("photo_path", None)
                people[1].pop("photo_url", None)
            family["revision"] += 1
            data = {"person": people[1], "revision": family["revision"]}
        elif path == "/projects/family-ui-project/people": data = {"items": people}
        elif path == "/projects/family-ui-project/relationships": data = {"items": family["relationships"]}
        elif path == "/agent/place-journey": data = {"place_journey": None}
        elif path.endswith("/memory-sessions"): return route.fulfill(status=403, content_type="application/json", body="{}")
        else: data = {"items": []}
        route.fulfill(content_type="application/json", body=json.dumps(data))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        base = os.environ["MEMOIR_BROWSER_URL"]
        context = browser.new_context(viewport={"width": width, "height": 960}, reduced_motion="reduce")
        context.add_cookies([{"name": "copyme2_ui_locale", "value": locale, "url": base},
                            {"name": "copyme2_ui_locale_source", "value": "fixed", "url": base}])
        user = {"id": "family-fixture-owner", "is_anonymous": False, "user_metadata": {}}
        script = f"window.supabase={{createClient:()=>({{auth:{{getSession:async()=>({{data:{{session:{{access_token:'fixture-only',user:{json.dumps(user)}}}}}}}),getUser:async()=>({{data:{{user:{json.dumps(user)}}}}}),onAuthStateChange:()=>({{}})}}}})}};"
        context.route("https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2", lambda route: route.fulfill(content_type="text/javascript", body=script))
        for url, body in chart_assets.items():
            if renderer_available:
                context.route(url, lambda route, request, body=body: route.fulfill(content_type="text/css" if request.url.endswith(".css") else "text/javascript", body=body))
            else:
                context.route(url, lambda route: route.abort())
        context.route("**/api/v1/memoir/**", api)
        context.route("https://photos.test/**", lambda route: route.fulfill(content_type="image/png", body=photo))
        context.add_init_script("localStorage.setItem('memory-spark-project','family-ui-project');sessionStorage.setItem('memory-spark-chat-history:family-ui-project','[{\"role\":\"user\",\"text\":\"A saved synthetic memory.\"}]');")
        page = context.new_page()
        page.on("pageerror", lambda error: print(f"Browser error: {error}"))
        page.on("console", lambda message: print(f"Browser console: {message.text}") if message.type == "error" else None)
        page.goto(base + "/memoir/interview/family-ui-project")
        page.wait_for_load_state("networkidle")
        output = ROOT / "output/family-tree"
        output.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output / f"initial-{locale}-{width}.png"))
        page.locator('[data-workspace-tab="family"]').click()
        tree = page.locator(".family-chart-adapter")
        expect(tree).to_have_attribute("data-renderer-status", "family-chart" if renderer_available else "fallback")
        expect(page.locator(".people-list, .relationship-list")).to_have_count(0)
        author = tree.locator('[data-family-person="me"]')
        expect(author.locator(".family-author-badge")).to_have_text(workspace["familyAuthor"])
        expect(tree.locator(".family-author-badge")).to_have_count(1)
        if width < 760:
            box = page.locator('#workspace-detail').bounding_box()
            assert box['height'] > 400
        tree.screenshot(path=str(output / f"canvas-{locale}-{width}-{'tree' if renderer_available else 'fallback'}.png"))
        if renderer_available:
            expect(tree.locator('.family-chart-library [data-family-person="mum"]')).to_be_visible()
            expect(tree.locator('.family-chart-fallback [data-family-person="mum"]')).to_have_count(0)
            expect(page.locator('[data-family-zoom="in"]')).to_be_enabled()
            transform = tree.locator('div.cards_view').get_attribute('style')
            page.locator('[data-family-zoom="in"]').click()
            expect(tree.locator('div.cards_view')).not_to_have_attribute('style', transform)
            page.locator('[data-family-zoom="out"]').click()
            page.locator('[data-family-zoom="fit"]').click()
        else:
            expect(page.locator('[data-family-zoom="in"]')).to_be_disabled()
        tree.locator('[data-family-person="mum"]').click()
        detail = page.locator(".family-person-detail")
        expect(detail).to_contain_text("She grew roses.")
        expect(detail).to_contain_text("around 1940")
        expect(detail.locator("script")).to_have_count(0)
        expect(page.locator("#family-person-name")).to_be_focused()
        expect(page.locator('[data-family-photo-upload]')).to_have_text(workspace['familyPhotoAdd'])
        with page.expect_file_chooser() as chooser:
            page.locator('[data-family-photo-upload]').click()
        chooser.value.set_files({"name": "mum.png", "mimeType": "image/png", "buffer": photo})
        expect(detail.locator('[role="status"]')).to_have_text(workspace['familyPhotoSaved'])
        expect(tree.locator('[data-family-person="mum"] img')).to_have_attribute('src', 'https://photos.test/mum-1.png')
        expect(detail.locator('img')).to_have_attribute('src', 'https://photos.test/mum-1.png')
        page.wait_for_function("[...document.querySelectorAll('[data-family-portrait]')].every(image => image.complete && image.naturalWidth > 0)")
        assert uploads == [photo]
        page.locator('#family-person-photo').set_input_files({"name": "wrong.txt", "mimeType": "text/plain", "buffer": b'not a photo'})
        expect(detail.locator('[role="alert"]')).to_have_text(workspace['familyPhotoInvalidType'])
        assert len(uploads) == 1
        upload_failure = True
        page.locator('#family-person-photo').set_input_files({"name": "mum.png", "mimeType": "image/png", "buffer": photo})
        expect(detail.locator('[role="alert"]')).to_have_text(workspace['familyPhotoFailed'])
        expect(tree.locator('[data-family-person="mum"] img')).to_have_attribute('src', 'https://photos.test/mum-1.png')
        upload_failure = False
        page.locator('#family-person-photo').set_input_files({"name": "mum-new.png", "mimeType": "image/png", "buffer": photo})
        expect(detail.locator('[role="status"]')).to_have_text(workspace['familyPhotoSaved'])
        expect(tree.locator('[data-family-person="mum"] img')).to_have_attribute('src', 'https://photos.test/mum-2.png')
        if width < 760:
            page.locator('.family-workspace').evaluate('element => element.scrollTop = 130')
            page.screenshot(path=str(output / 'mobile-family-photo.png'))
        tree.screenshot(path=str(output / f"photo-canvas-{locale}-{width}-{'tree' if renderer_available else 'fallback'}.png"))
        detail.screenshot(path=str(output / f"photo-detail-{locale}-{width}-{'tree' if renderer_available else 'fallback'}.png"))
        page.reload()
        page.wait_for_load_state('networkidle')
        page.locator('[data-workspace-tab="family"]').click()
        expect(tree.locator('[data-family-person="mum"] img')).to_have_attribute('src', 'https://photos.test/mum-2.png')
        tree.locator('[data-family-person="mum"]').click()
        expect(page.locator('[data-family-photo-upload]')).to_have_text(workspace['familyPhotoReplace'])
        page.locator('[data-family-photo-remove]').click()
        expect(detail.locator('[role="status"]')).to_have_text(workspace['familyPhotoRemoved'])
        expect(tree.locator('[data-family-person="mum"] img')).to_have_count(0)
        expect(page.locator('[data-family-photo-upload]')).to_have_text(workspace['familyPhotoAdd'])
        page.keyboard.press("Escape")
        expect(detail).to_have_count(0)
        expect(tree.locator('[data-family-person="mum"]')).to_be_focused()
        author.focus()
        page.keyboard.press("Enter")
        expect(detail).to_contain_text("I grew up beside a small garden.")
        expect(detail.locator(".family-author-badge")).to_have_text(workspace["familyAuthor"])
        page.locator("[data-family-person-close]").click()
        tree.locator('[data-family-person="uncle"]').click()
        expect(detail).to_contain_text(workspace["familyPersonIntroductionEmpty"].replace("{name}", "Bo"))
        expect(detail).not_to_contain_text("She grew roses.")
        page.locator("[data-family-person-close]").click()
        author.click()
        # Chromium can clip a fraction of a pixel after smooth scrolling.
        expect(detail).to_be_in_viewport(ratio=0.99)
        page.locator("#workspace-detail").screenshot(path=str(output / f"{locale}-{width}-{'tree' if renderer_available else 'fallback'}.png"))
        browser.close()
