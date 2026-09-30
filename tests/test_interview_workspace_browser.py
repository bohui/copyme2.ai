"""Interview regression checks through the browser and HTTP boundary.

Run against the local source server:
MEMOIR_BROWSER_URL=http://localhost:3011 python3 -m pytest tests/test_interview_workspace_browser.py -q
"""
import json
import os

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.skipif(not os.environ.get("MEMOIR_BROWSER_URL"), reason="Requires an explicitly selected running browser test server")


@pytest.fixture
def interview():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(8000)
        # Authentication and model output are external boundaries. Avoid creating
        # a new real anonymous Supabase account for every regression scenario.
        page.route("**/api/v1/memoir/agent/config", lambda route: route.fulfill(
            content_type="application/json", body='{"auth_mode":"test","show_thinking_steps":false}'))
        page.route("**/api/v1/memoir/story/state", lambda route: route.fulfill(
            content_type="application/json", body='{"family_features_enabled":false}'))
        page.route("**/place-photos?**", lambda route: route.fulfill(content_type="application/json", body='{"items":[]}'))
        def google_place_map(route):
            payload = route.request.post_data_json or {}
            place = payload.get("place")
            coordinates = {
                "Chengde": (40.9515, 117.9634),
                "Sydney": (-33.8688, 151.2093),
            }.get(place)
            if not coordinates:
                return route.fulfill(content_type="application/json", body=json.dumps({"status": "NO_MATCH", "target": None}))
            return route.fulfill(content_type="application/json", body=json.dumps({
                "status": "READY",
                "target": {"place": place, "latitude": coordinates[0], "longitude": coordinates[1], "attribution": "Google Maps"},
                "fallback": False,
            }))
        page.route("**/place-map", google_place_map)
        journey = {"schema_version": 1, "status": "active", "revision": 1,
                   "place": "Chengde", "hierarchy": ["Earth", "China", "Hebei", "Chengde"],
                   "granularity": "city", "latitude": 40.9515, "longitude": 117.9634,
                   "duration_ms": 2800}
        page.route("**/api/v1/memoir/agent/turn", lambda route: route.fulfill(
            content_type="application/json", body=json.dumps({
                "reply": "What do you remember about the streets near your childhood home?",
                "profile_updates": {"story_focus": {"life_stage": "childhood"}},
                "place_journey": journey,
                "place_journey_change": {"changed": True, "revision": 1},
            })))
        page.goto(os.environ.get("MEMOIR_BROWSER_URL", "http://localhost:3011"))
        page.get_by_role("button", name="Begin my story").click()
        expect(page.locator(".assistant-message .listen-button").first).to_be_visible(timeout=30000)
        expect(page.locator(".message-streaming")).to_have_count(0, timeout=30000)
        expect(page.get_by_text("Before chapter one", exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="Hide history", exact=True)).to_have_count(0)
        page.get_by_role("textbox", name="Your message").fill("I grew up in Chengde. " + "I remember the streets and my friends. " * 25)
        page.get_by_role("button", name="Send message").click()
        expect(page.get_by_role("button", name="Collapse workspace")).to_be_visible(timeout=20000)
        expect(page.locator(".message-streaming")).to_have_count(0, timeout=20000)
        yield page
        browser.close()


def test_narrow_conversation_heading_leaves_room_for_history(interview):
    heading = interview.get_by_role("heading", name="Let’s remember together.")
    assert heading.evaluate("el => parseFloat(getComputedStyle(el).fontSize)") <= 30


def test_refresh_collapses_chat_history_until_expanded(interview):
    page = interview
    expect(page.get_by_role("button", name="Hide history", exact=True)).to_be_visible()
    expect(page.locator("#chat-history")).not_to_have_attribute("hidden", "")

    page.reload()

    show_history = page.get_by_role("button", name="Show all history", exact=True)
    expect(show_history).to_be_visible(timeout=20000)
    expect(page.locator("#chat-history")).to_have_attribute("hidden", "")
    expect(page.locator("#chat-history .chat-row").first).not_to_be_visible()
    expect(page.locator("#chat-history .user-message").first).not_to_be_visible()

    show_history.click()
    expect(page.get_by_role("button", name="Hide history", exact=True)).to_be_visible()
    expect(page.locator("#chat-history")).not_to_have_attribute("hidden", "")
    expect(page.locator("#chat-history .chat-row").first).to_be_visible()
    expect(page.locator("#chat-history .user-message").first).to_be_visible()


def test_workspace_navigation_preserves_chat_reading_position(interview):
    scroll = interview.locator("#chat-scroll")
    scroll.evaluate("el => { el.style.scrollBehavior = 'auto'; el.scrollTop = 100; }")
    before = scroll.evaluate("el => el.scrollTop")
    interview.get_by_role("button", name="Toddler Not explored yet", exact=True).click()
    interview.wait_for_timeout(500)
    assert abs(scroll.evaluate("el => el.scrollTop") - before) < 2


def test_workspace_prioritizes_map_and_places_toggle_at_left(interview):
    expect(interview.get_by_text("1 memory in conversation · Place context added", exact=True)).to_have_count(0)
    expect(interview.locator(".workspace-media-gallery")).to_have_count(0)
    expect(interview.get_by_text("Not quite the right place? Tell me in the conversation.", exact=True)).to_have_count(0)
    workspace = interview.get_by_role("complementary", name="Places workspace").bounding_box()
    toggle = interview.get_by_role("button", name="Collapse workspace").bounding_box()
    assert toggle["x"] - workspace["x"] < 50
    scene = interview.locator(".place-journey-scene").bounding_box()
    timeline = interview.locator(".life-stage-navigator").bounding_box()
    assert scene["height"] >= 280
    assert scene["y"] + scene["height"] <= timeline["y"]
    from pathlib import Path
    destination = Path("output/playwright/interview-workspace-fixed.png")
    destination.parent.mkdir(parents=True, exist_ok=True)
    interview.screenshot(path=str(destination))


def test_life_stages_show_distinct_existing_avatar_images(interview):
    icons = interview.locator(".life-stage-figure img")
    expect(icons).to_have_count(7)
    assert icons.evaluate_all("els => els.every(el => el.complete && el.naturalWidth > 0)")
    assert len(set(icons.evaluate_all("els => els.map(el => el.src)"))) == 7


def test_places_follow_stage_and_survive_new_places(interview):
    page = interview
    page.route("**/api/v1/memoir/agent/turn", lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({
            "reply": "What do you remember about arriving there?",
            "profile_updates": {"story_focus": {"life_stage": "young_adulthood"}},
            "place_journey": {"schema_version": 1, "place": "Sydney", "hierarchy": ["Earth", "Australia", "Sydney"],
                              "granularity": "city", "latitude": -33.8688, "longitude": 151.2093, "revision": 2},
            "place_journey_change": {"changed": True, "revision": 2}})))
    page.get_by_role("textbox", name="Your message").fill("As a young adult I moved to Sydney.")
    page.get_by_role("button", name="Send message").click()
    expect(page.get_by_role("heading", name="Sydney", exact=True)).to_be_visible(timeout=20000)
    history = page.get_by_role("navigation", name="Place history")
    expect(history.get_by_role("button", name="Chengde", exact=False)).to_be_visible()
    history.get_by_role("button", name="Chengde", exact=False).click()
    expect(page.get_by_role("heading", name="Chengde", exact=True)).to_be_visible()
    history.get_by_role("button", name="Sydney", exact=False).click()
    expect(page.get_by_role("heading", name="Sydney", exact=True)).to_be_visible()
    page.get_by_role("button", name="Childhood", exact=True).click()
    expect(page.get_by_role("heading", name="Chengde", exact=True)).to_be_visible()
    page.get_by_role("button", name="Young adulthood", exact=True).click()
    expect(page.get_by_role("heading", name="Sydney", exact=True)).to_be_visible()
    page.reload()
    expect(page.get_by_role("heading", name="Sydney", exact=True)).to_be_visible(timeout=20000)
    page.get_by_role("navigation", name="Place history").get_by_role("button", name="Chengde", exact=False).click()
    expect(page.get_by_role("heading", name="Chengde", exact=True)).to_be_visible()
    expect(page.locator(".message-streaming")).to_have_count(0, timeout=20000)
    page.route("**/api/v1/memoir/agent/turn", lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({
            "reply": "What else do you remember about Chengde?",
            "profile_updates": {"story_focus": {"life_stage": "childhood"}},
            "place_journey": {"place": "Chengde", "hierarchy": ["Earth", "China", "Hebei", "Chengde"],
                              "granularity": "city", "latitude": 40.9515, "longitude": 117.9634, "revision": 3},
            "place_journey_change": {"changed": True, "revision": 3}})))
    with page.expect_response(lambda response: response.request.method == "PATCH" and "/projects/" in response.url):
        page.get_by_role("textbox", name="Your message").fill("Back to my childhood in Chengde.")
        page.get_by_role("button", name="Send message").click()
    expect(page.locator(".message-streaming")).to_have_count(0, timeout=20000)
    expect(page.get_by_role("navigation", name="Place history").get_by_role("button")).to_have_count(2)
    page.reload()
    expect(page.get_by_role("heading", name="Chengde", exact=True)).to_be_visible(timeout=20000)
    expect(page.get_by_role("navigation", name="Place history").get_by_role("button")).to_have_count(2)


def test_storyteller_can_choose_timeline_artwork(interview):
    interview.get_by_role("button", name="Open profile menu").click()
    interview.get_by_label("Timeline artwork").select_option("female")
    expect(interview.locator(".life-stage-figure img").first).to_have_attribute("src", "/static/timeline_avatar_baby_female.png")


def test_place_photos_arrive_without_interrupting_reply_or_draft(interview):
    page = interview
    page.route("**/place-photos?**", lambda route: route.fulfill(content_type="application/json", body=json.dumps({"items": [{
        "asset_id": "photo-sydney", "kind": "image", "title": "Sydney street",
        "image_url": "/static/timeline_avatar_child_female.png", "source_url": "https://commons.wikimedia.org/",
        "attribution": "Example photographer", "license": "CC BY 4.0", "date_expression": "1985",
        "allowed_actions": {"embed": True}}]})))
    page.route("**/api/v1/memoir/agent/turn", lambda route: route.fulfill(content_type="application/json", body=json.dumps({
        "reply": "What do you remember about the day you arrived? " * 12,
        "profile_updates": {"story_focus": {"life_stage": "young_adulthood"}},
        "place_journey": {"place": "Sydney", "hierarchy": ["Earth", "Australia", "Sydney"], "granularity": "city"},
        "place_journey_change": {"changed": True}})))
    page.get_by_role("textbox", name="Your message").fill("I moved to Sydney as a young adult.")
    page.get_by_role("button", name="Send message").click()
    expect(page.get_by_role("img", name="Sydney street")).to_be_visible(timeout=20000)
    expect(page.locator(".message-streaming")).to_have_count(1)
    page.get_by_role("textbox", name="Your message").fill("My next memory")
    expect(page.locator(".message-streaming")).to_have_count(0, timeout=20000)
    expect(page.get_by_role("textbox", name="Your message")).to_have_value("My next memory")
    expect(page.get_by_role("textbox", name="Your message")).to_be_focused()


def test_workspace_refresh_keeps_existing_map_camera(interview):
    import io
    from PIL import Image, ImageChops, ImageStat
    scene = interview.locator(".place-journey-scene.is-cesium-live")
    expect(scene).to_be_visible(timeout=30000)
    interview.wait_for_timeout(3500)
    before = Image.open(io.BytesIO(scene.screenshot())).convert("RGB")
    interview.get_by_role("button", name="Childhood", exact=False).click()
    after = Image.open(io.BytesIO(scene.screenshot())).convert("RGB")
    assert max(ImageStat.Stat(ImageChops.difference(before, after)).mean) < 5


def test_saved_project_places_survive_reload_without_new_place_cue(interview):
    page = interview
    page.route("**/api/v1/memoir/agent/place-journey", lambda route: route.fulfill(content_type="application/json", body='{"place_journey":null}'))
    page.route("**/api/v1/memoir/agent/turn", lambda route: route.fulfill(content_type="application/json", body='{"reply":"Where would you like to continue?"}'))
    page.reload()
    expect(page.get_by_role("heading", name="Chengde", exact=True)).to_be_visible(timeout=20000)
    expect(page.get_by_role("button", name="Childhood", exact=False)).to_have_attribute("aria-pressed", "true")


def test_unmapped_place_does_not_replace_the_workspace(interview):
    page = interview
    page.route("**/place-map", lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"status": "NO_MATCH", "target": None})))
    page.route("**/api/v1/memoir/agent/turn", lambda route: route.fulfill(content_type="application/json", body=json.dumps({
        "reply": "What was your new neighbourhood like?",
        "profile_updates": {"story_focus": {"life_stage": "childhood"}},
        "place_journey": {"place": "Beijing", "hierarchy": ["Earth", "China", "Beijing"], "granularity": "city"},
        "place_journey_change": {"changed": True}})))
    page.get_by_role("textbox", name="Your message").fill("We moved to Beijing when I was a child.")
    page.get_by_role("button", name="Send message").click()
    expect(page.get_by_role("complementary", name="Places workspace")).to_have_count(0, timeout=20000)
    expect(page.locator(".place-journey-card")).to_have_count(0)


def test_conversation_keeps_inviting_memories_after_session_followups(interview):
    captured = []
    def answer(route):
        captured.append(route.request.post_data_json['text'])
        route.fulfill(content_type="application/json", body='{"reply":"What happened next?"}')
    interview.route("**/api/v1/memoir/agent/turn", answer)
    interview.route("**/memory-sessions/*/answers", lambda route: route.fulfill(content_type="application/json", body=json.dumps({
        "id": "session-finished", "status": "READY_TO_SAVE", "turns": [{}] * 10, "follow_ups_remaining": 0, "follow_ups_used": 100})))
    interview.get_by_role("textbox", name="Your message").fill("And then we went to school together.")
    interview.get_by_role("button", name="Send message").click()
    expect(interview.locator(".assistant-message").last).to_contain_text("What happened next?", timeout=20000)
    assert 'Do not ask another question' not in captured[0]
    assert 'follow-up question' in captured[0]


def test_places_without_a_map_do_not_open_workspace(interview):
    page = interview
    page.route("**/place-map", lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"status": "NO_MATCH", "target": None})))
    page.route("**/api/v1/memoir/agent/turn", lambda route: route.fulfill(content_type="application/json", body=json.dumps({
        "reply": "What comes to mind about that place?",
        "place_journey": {"place": "Hobart", "hierarchy": ["Earth", "Australia", "Hobart"], "granularity": "city"},
        "place_journey_change": {"changed": True}})))
    page.get_by_role("textbox", name="Your message").fill("I also remember Hobart.")
    page.get_by_role("button", name="Send message").click()
    expect(page.get_by_role("complementary", name="Places workspace")).to_have_count(0, timeout=20000)
    expect(page.locator(".place-journey-card")).to_have_count(0)
