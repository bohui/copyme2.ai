"""Workspace UI with real demo project/session persistence over HTTP.

Authentication, collector replies and their account history are controlled
external boundaries. This suite does not exercise Supabase history/RLS.

Run against the local source server:
MEMOIR_BROWSER_URL=http://localhost:3011 python3 -m pytest tests/test_interview_workspace_browser.py -q
"""
import json
import os
import re

import pytest
from playwright.sync_api import expect, sync_playwright
from browser_optional_fonts import control_optional_fonts
from browser_workspace_history import WorkspaceHistory, mock_workspace_turn

pytestmark = pytest.mark.skipif(not os.environ.get("MEMOIR_BROWSER_URL"), reason="Requires an explicitly selected running browser test server")


@pytest.fixture
def interview():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        control_optional_fonts(page)
        page.set_default_timeout(8000)
        # Product routes use the isolated API's demo principal; the synthetic
        # browser token belongs only to the mocked authentication boundary.
        page.workspace_history = WorkspaceHistory()
        page.route("**/api/v1/memoir/projects**", page.workspace_history.project_request)
        page.route("**/api/v1/memoir/memory-sessions/**", page.workspace_history.project_request)
        page.route(re.compile(r"^.*/api/v1/memoir/user/projects/[^/?]+/history(?:\?.*)?$"),
                   page.workspace_history.history_request)
        # Authentication and model output are external boundaries. Avoid creating
        # a new real anonymous Supabase account for every regression scenario.
        page.route("**/api/v1/memoir/agent/config", lambda route: route.fulfill(
            content_type="application/json", body='{"auth_mode":"test","show_thinking_steps":false}'))
        profile = {'preferred_language': 'en-AU'}
        def private_profile(route):
            if route.request.method == 'PATCH':
                profile.update(route.request.post_data_json)
            route.fulfill(json=profile)
        page.route('**/api/v1/memoir/agent/profile', private_profile)
        page.route('**/api/v1/memoir/user/profile', private_profile)
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
                   "duration_ms": 2800, "life_stage": "childhood"}
        mock_workspace_turn(page, lambda route: route.fulfill(
            content_type="application/json", body=json.dumps({
                "reply": "What do you remember about the streets near your childhood home?",
                "profile_updates": {"story_focus": {"life_stage": "childhood"}},
                "place_journey": journey,
                "place_journey_change": {"changed": True, "revision": 1},
            })))
        page.goto(os.environ.get("MEMOIR_BROWSER_URL", "http://localhost:3011").rstrip('/') + '/memoir',
                  wait_until="networkidle", timeout=30000)
        page.get_by_role("button", name="Begin my story").click()
        expect(page.locator(".assistant-message .listen-button").first).to_be_visible(timeout=30000)
        expect(page.locator(".message-streaming")).to_have_count(0, timeout=30000)
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("Before chapter one", exact=True)).to_have_count(0)
        expect(page.get_by_role("button", name="Hide history", exact=True)).to_have_count(0)
        page.get_by_role("textbox", name="Your message").fill("I grew up in Chengde. " + "I remember the streets and my friends. " * 25)
        page.get_by_role("button", name="Send message").click()
        expect(page.get_by_role("button", name="Collapse workspace")).to_be_visible(timeout=20000)
        expect(page.locator(".message-streaming")).to_have_count(0, timeout=20000)
        page.wait_for_load_state("networkidle")
        yield page
        browser.close()


def test_narrow_conversation_heading_leaves_room_for_history(interview):
    heading = interview.get_by_role("heading", name="Let’s remember together.")
    expect(heading).to_have_css('font-size', re.compile(r'(?:[12]?\d(?:\.\d+)?|30(?:\.0+)?)px'))


def test_birthplace_photos_restore_the_historical_period_without_thumbnail_duplicates(interview):
    page = interview
    requests = []
    historical = {
        'asset_id': 'historical-original', 'title': 'Chengde in the 1980s',
        'date_expression': '1980-1989', 'period_match': 'decade', 'matched_period': '1980s',
        'requested_period': '1983年4月', 'search_place': 'Chengde', 'search_fallback': 'gps',
        'source_url': 'https://commons.wikimedia.org/wiki/File:Chengde_1980s.jpg',
        'image_url': 'https://upload.wikimedia.org/wikipedia/commons/a/ab/Chengde_1980s.jpg',
        'allowed_actions': {'embed': True},
    }
    duplicate = {**historical, 'asset_id': 'historical-thumbnail',
        'image_url': 'https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/Chengde_1980s.jpg/120px-Chengde_1980s.jpg'}
    def photos(route):
        from urllib.parse import parse_qs, urlsplit
        query = parse_qs(urlsplit(route.request.url).query, keep_blank_values=True)
        requests.append(query)
        items = [historical, duplicate] if query['place'] == ['Chengde'] and query['period'] == ['1983年4月'] else []
        route.fulfill(json={'items': items, 'status': 'PARTIAL', 'searching': False})
    page.route('**/place-photos?**', photos)
    sydney = {'place': 'Sydney', 'hierarchy': ['Earth', 'Australia', 'Sydney'],
        'granularity': 'city', 'latitude': -33.8688, 'longitude': 151.2093, 'source_sequence': 2}
    chengde = {'place': 'Chengde', 'hierarchy': ['Earth', 'China', 'Hebei', 'Chengde'],
        'granularity': 'city', 'latitude': 40.9515, 'longitude': 117.9634, 'source_sequence': 2}
    mock_workspace_turn(page, lambda route: route.fulfill(json={
        'reply': 'What do you remember about Chengde?', 'place_journey': chengde,
        'place_journeys': [sydney, chengde], 'place_journey_change': {'changed': True},
    }))
    page.get_by_role('textbox', name='Your message').fill(
        '现在生活在Sydney，但是我于1983年4月出生在Chengde')
    page.get_by_role('button', name='Send message').click()
    gallery = page.locator('.workspace-media-gallery .place-pictures figure')
    expect(gallery).to_have_count(1, timeout=20000)
    expect(gallery).to_contain_text('1980-1989')
    assert any(query['place'] == ['Chengde'] and query['period'] == ['1983年4月'] for query in requests)
    assert any(query['place'] == ['Sydney'] and query['period'] == [''] for query in requests)
    expect(page.locator('.place-choices button span')).to_have_text(['Chengde', 'Sydney'])
    requests.clear()
    page.route('**/api/v1/memoir/agent/config', lambda route: route.fulfill(json={
        'auth_mode': 'test', 'show_thinking_steps': True}))
    page.reload(wait_until='networkidle')
    page.locator('.place-choices button').filter(has_text='Chengde').click()
    expect(gallery).to_have_count(1, timeout=20000)
    expect(gallery).to_contain_text('1980-1989')
    assert not any(query['place'] == ['Chengde'] and query['period'] == [''] for query in requests)
    page.get_by_role('button', name='Show all history', exact=True).click()
    restored = page.locator('.assistant-message').last.locator('[data-step-id="place-journey"]')
    expect(restored).to_contain_text('Restored saved place cues')
    expect(restored).to_contain_text('Chengde')


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


def test_thinking_steps_include_place_skills_and_photo_retry_outcomes(interview):
    page = interview
    page.route('**/api/v1/memoir/agent/config', lambda route: route.fulfill(json={
        'auth_mode': 'test', 'show_thinking_steps': True}))
    page.reload(wait_until='networkidle')
    page.get_by_role('button', name='Show all history', exact=True).click()
    chengde = {'place': 'Chengde', 'hierarchy': ['Earth', 'China', 'Hebei', 'Chengde'],
        'granularity': 'city', 'latitude': 40.9515, 'longitude': 117.9634}
    sydney = {'place': 'Sydney', 'hierarchy': ['Earth', 'Australia', 'Sydney'],
        'granularity': 'city', 'latitude': -33.8688, 'longitude': 151.2093}
    def turn(route):
        events = page.workspace_history.turn_events(route.request, {
            'reply': 'What do you remember about Chengde?', 'place_journey': chengde,
            'place_journeys': [sydney, chengde], 'place_journey_change': {'changed': True}})
        events.insert(1, {'type': 'progress', 'data': {'id': 'place-journey', 'kind': 'skill',
            'skill': 'memoir-place-journey', 'status': 'completed',
            'detail': 'Validated and saved place cues · Sydney · Chengde'}})
        route.fulfill(content_type='application/x-ndjson',
            body=''.join(json.dumps(event) + '\n' for event in events))
    page.route('**/api/v1/memoir/agent/turn', turn)
    retried = False
    def photos(route):
        from urllib.parse import parse_qs, urlsplit
        query = parse_qs(urlsplit(route.request.url).query)
        if query['place'] == ['Chengde'] and not retried:
            return route.fulfill(json={'status': 'UNAVAILABLE', 'searching': False, 'items': [],
                'failures': [{'provider': 'flickr', 'reason': 'robots_denied'},
                             {'provider': 'loc', 'reason': 'http_403'}]})
        items = [{'asset_id': 'old-street', 'image_url': 'https://images.example/chengde-1983.jpg',
            'date_expression': '1983', 'latitude': chengde['latitude'], 'longitude': chengde['longitude'],
            'allowed_actions': {'embed': True}}] if query['place'] == ['Chengde'] else []
        route.fulfill(json={'status': 'READY', 'searching': False, 'items': items})
    page.route('**/place-photos?**', photos)
    page.get_by_role('textbox', name='Your message').fill(
        '现在生活在Sydney，但是我于1983年4月出生在Chengde')
    page.get_by_role('button', name='Send message').click()
    trace = page.locator('.assistant-message').last.locator('.agent-loop')
    expect(trace.locator('[data-step-id="place-journey"]')).to_have_count(1)
    expect(trace.locator('[data-step-id^="place-groups:"][data-step-status="completed"]')).not_to_have_count(0)
    failed = trace.locator('[data-step-id^="photos:"][data-step-status="failed"]')
    expect(failed).to_have_count(1)
    expect(failed).to_contain_text('Chengde · 1983年4月')
    expect(failed).to_contain_text('flickr: robots_denied; loc: http_403')
    expect(trace.locator('[data-step-id^="photos:"][data-step-status="completed"]')).to_contain_text('Sydney')
    retried = True
    page.locator('[data-photo-retry]').click()
    expect(trace.locator('[data-step-id^="photos:"][data-step-status="failed"]')).to_have_count(0)
    expect(trace.locator('[data-step-id^="photos:"][data-step-status="completed"]')).to_have_count(2)
    page.reload(wait_until='networkidle')
    page.get_by_role('button', name='Show all history', exact=True).click()
    expect(trace.locator('[data-step-id="place-journey"]')).to_have_count(1)
    expect(trace.locator('[data-step-id^="photos:"][data-step-status="completed"]')).to_have_count(2)


def test_workspace_navigation_preserves_chat_reading_position(interview):
    scroll = interview.locator("#chat-scroll")
    scroll.evaluate("el => { el.style.scrollBehavior = 'auto'; el.scrollTop = 100; }")
    before = scroll.evaluate("el => el.scrollTop")
    interview.get_by_role("button", name=re.compile(r'^Childhood:')).click()
    interview.wait_for_timeout(500)
    assert abs(scroll.evaluate("el => el.scrollTop") - before) < 2


def test_workspace_prioritizes_map_and_places_toggle_at_left(interview):
    expect(interview.get_by_text("1 memory in conversation · Place context added", exact=True)).to_have_count(0)
    expect(interview.locator(".workspace-media-gallery [role='status']")).to_have_text(
        "No matching reference photos were found for this place and period."
    )
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
    mock_workspace_turn(page, lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({
            "reply": "What do you remember about arriving there?",
            "profile_updates": {"story_focus": {"life_stage": "young_adulthood"}},
            "place_journey": {"schema_version": 1, "place": "Sydney", "hierarchy": ["Earth", "Australia", "Sydney"],
                              "granularity": "city", "latitude": -33.8688, "longitude": 151.2093, "revision": 2,
                              "life_stage": "young_adulthood"},
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
    page.get_by_role("button", name=re.compile(r'^Childhood:')).click()
    expect(page.get_by_role("heading", name="Chengde", exact=True)).to_be_visible()
    page.get_by_role("button", name=re.compile(r'^Young adulthood:')).click()
    expect(page.get_by_role("heading", name="Sydney", exact=True)).to_be_visible()
    page.reload()
    expect(page.get_by_role("heading", name="Sydney", exact=True)).to_be_visible(timeout=20000)
    # Hydration restores the saved place's stage; use the stage selector to
    # verify that places in both stages survived the reload.
    page.get_by_role("button", name=re.compile(r'^Childhood:')).click()
    expect(page.get_by_role("heading", name="Chengde", exact=True)).to_be_visible()
    expect(page.locator(".message-streaming")).to_have_count(0, timeout=20000)
    mock_workspace_turn(page, lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({
            "reply": "What else do you remember about Chengde?",
            "profile_updates": {"story_focus": {"life_stage": "childhood"}},
            "place_journey": {"place": "Chengde", "hierarchy": ["Earth", "China", "Hebei", "Chengde"],
                              "granularity": "city", "latitude": 40.9515, "longitude": 117.9634, "revision": 3,
                              "life_stage": "childhood"},
            "place_journey_change": {"changed": True, "revision": 3}})))
    with page.expect_response(lambda response: response.request.method == "PATCH" and "/projects/" in response.url):
        page.get_by_role("textbox", name="Your message").fill("Back to my childhood in Chengde.")
        page.get_by_role("button", name="Send message").click()
    expect(page.get_by_role("button", name="Send message")).to_be_enabled(timeout=20000)
    expect(page.locator(".message-streaming")).to_have_count(0, timeout=20000)
    expect(page.get_by_role("navigation", name="Place history").get_by_role("button")).to_have_count(2)
    page.reload()
    expect(page.get_by_role("heading", name="Chengde", exact=True)).to_be_visible(timeout=20000)
    expect(page.get_by_role("button", name=re.compile(r'^Childhood:'))).to_have_attribute("aria-pressed", "true")
    page.get_by_role("button", name=re.compile(r'^Young adulthood:')).click()
    expect(page.get_by_role("heading", name="Sydney", exact=True)).to_be_visible()


def test_storyteller_artwork_preference_updates_timeline(interview):
    mock_workspace_turn(interview, lambda route: route.fulfill(json={
        'reply': 'I have updated the illustrations.',
        'profile_updates': {'avatar_style': 'female'}}))
    interview.get_by_role('textbox', name='Your message').fill('Please use female illustrations for my timeline.')
    interview.get_by_role('button', name='Send message').click()
    expect(interview.locator(".life-stage-figure img").first).to_have_attribute("src", "/static/timeline_avatar_baby_female.png")


def test_place_photos_arrive_without_interrupting_reply_or_draft(interview):
    page = interview
    page.route("**/place-photos?**", lambda route: route.fulfill(content_type="application/json", body=json.dumps({"items": [{
        "asset_id": "photo-sydney", "kind": "image", "title": "Sydney street",
        "image_url": "/static/timeline_avatar_child_female.png", "source_url": "https://commons.wikimedia.org/",
        "attribution": "Example photographer", "license": "CC BY 4.0", "date_expression": "1985",
        "latitude": -33.8688, "longitude": 151.2093,
        "allowed_actions": {"embed": True}}]})))
    mock_workspace_turn(page, lambda route: route.fulfill(content_type="application/json", body=json.dumps({
        "reply": "What do you remember about the day you arrived? " * 12,
        "profile_updates": {"story_focus": {"life_stage": "young_adulthood"}},
        "place_journey": {"place": "Sydney", "hierarchy": ["Earth", "Australia", "Sydney"], "granularity": "city",
                          "period": "1980s", "latitude": -33.8688, "longitude": 151.2093,
                          "life_stage": "young_adulthood"},
        "place_journey_change": {"changed": True}})))
    page.get_by_role("textbox", name="Your message").fill("I moved to Sydney as a young adult in the 1980s.")
    page.get_by_role("button", name="Send message").click()
    expect(page.get_by_role("img", name="Sydney street")).to_be_visible(timeout=20000)
    expect(page.locator(".message-streaming")).to_have_count(0)
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
    mock_workspace_turn(page, lambda route: route.fulfill(content_type="application/json", body='{"reply":"Where would you like to continue?"}'))
    page.reload()
    expect(page.get_by_role("heading", name="Chengde", exact=True)).to_be_visible(timeout=20000)
    expect(page.get_by_role("button", name="Childhood", exact=False)).to_have_attribute("aria-pressed", "true")


def test_unmapped_place_keeps_places_and_photos_available_after_round_five(interview):
    page = interview
    page.route("**/place-map", lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"status": "NO_MATCH", "target": None})))
    mock_workspace_turn(page, lambda route: route.fulfill(content_type="application/json", body=json.dumps({
        "reply": "What was your new neighbourhood like?",
        "composition_stage": 0,
        "profile_updates": {"story_focus": {"life_stage": "childhood"}},
        "place_journey": {"place": "Beijing", "hierarchy": ["Earth", "China", "Beijing"], "granularity": "city",
                          "life_stage": "childhood", "revision": 2},
        "place_journey_change": {"changed": True}})))
    page.get_by_role("textbox", name="Your message").fill("We moved to Beijing when I was a child.")
    page.get_by_role("button", name="Send message").click()
    expect(page.get_by_role("heading", name="Beijing", exact=True)).to_be_visible(timeout=20000)
    expect(page.get_by_role("button", name="Send message")).to_be_enabled(timeout=20000)
    page.route("**/api/v1/memoir/story/private-draft?**", lambda route: route.fulfill(json={
        "covered_round": 5, "preview": {"title": "Childhood", "text": "A saved private draft."}}))
    page.wait_for_timeout(250)  # Exceed the former workspace visibility timeout.
    expect(page.get_by_role("complementary", name="Places workspace")).to_be_visible()
    expect(page.locator(".workspace-media-map")).to_be_visible()
    expect(page.locator(".workspace-media-gallery")).to_be_visible()
    expect(page.get_by_text("Location pending", exact=True)).to_be_visible()
    expect(page.locator(".place-journey-card")).to_have_count(0)
    expect(page.locator("[data-workspace-tab]")).to_have_count(0)

    with page.expect_response(lambda response: "/story/private-draft?" in response.url):
        page.reload()
    expect(page.get_by_role("heading", name="Beijing", exact=True)).to_be_visible(timeout=20000)
    expect(page.locator(".private-draft-status")).to_have_count(0)
    expect(page.get_by_text("A saved private draft.", exact=True)).to_have_count(0)
    expect(page.locator(".workspace-media-gallery")).to_be_visible()
    history = page.get_by_role("navigation", name="Place history")
    history.get_by_role("button", name="Chengde", exact=False).click()
    expect(page.locator(".place-journey-card")).to_be_visible()
    history.get_by_role("button", name="Beijing", exact=False).click()
    expect(page.get_by_text("Location pending", exact=True)).to_be_visible()

    from pathlib import Path
    destination = Path("output/playwright/interview-unmapped-workspace-fixed.png")
    destination.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(destination))


def test_conversation_keeps_inviting_memories_after_session_followups(interview):
    captured = []
    def answer(route):
        captured.append(route.request.post_data_json['text'])
        route.fulfill(content_type="application/json", body='{"reply":"What happened next?"}')
    mock_workspace_turn(interview, answer)
    interview.route("**/memory-sessions/*/answers", lambda route: route.fulfill(content_type="application/json", body=json.dumps({
        "id": "session-finished", "status": "READY_TO_SAVE", "turns": [{}] * 10, "follow_ups_remaining": 0, "follow_ups_used": 100})))
    interview.get_by_role("textbox", name="Your message").fill("And then we went to school together.")
    interview.get_by_role("button", name="Send message").click()
    expect(interview.locator(".assistant-message").last).to_contain_text("What happened next?", timeout=20000)
    assert 'Do not ask another question' not in captured[0]
    assert 'follow-up question' in captured[0]


def test_places_without_a_map_keep_workspace_controls_and_later_composition(interview):
    page = interview
    page.route("**/place-map", lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({"status": "NO_MATCH", "target": None})))
    mock_workspace_turn(page, lambda route: route.fulfill(content_type="application/json", body=json.dumps({
        "reply": "What comes to mind about that place?",
        "place_journey": {"place": "Hobart", "hierarchy": ["Earth", "Australia", "Hobart"], "granularity": "city"},
        "place_journey_change": {"changed": True}})))
    page.get_by_role("textbox", name="Your message").fill("I also remember Hobart.")
    page.get_by_role("button", name="Send message").click()
    expect(page.get_by_role("heading", name="Hobart", exact=True)).to_be_visible(timeout=20000)
    expect(page.get_by_role("complementary", name="Places workspace")).to_be_visible()
    expect(page.locator(".workspace-media-gallery")).to_be_visible()
    expect(page.locator(".place-journey-card")).to_have_count(0)
    expect(page.get_by_role("button", name="Send message")).to_be_enabled(timeout=20000)
    page.get_by_role("button", name="Collapse workspace").click()
    expect(page.locator("#workspace-detail")).to_have_class("workspace-detail is-collapsed")
    page.get_by_role("button", name="Show workspace").click()
    expect(page.locator(".workspace-media-gallery")).to_be_visible()

    mock_workspace_turn(page, lambda route: route.fulfill(json={
        "reply": "Your first chapter is ready. What else do you remember?",
        "composition_stage": 3,
        "chapters": [{"id": "first-chapter", "chapter_number": 1, "title": "Childhood", "text": "A remembered journey."}]}))
    page.get_by_role("textbox", name="Your message").fill("There is more I would like to remember.")
    page.get_by_role("button", name="Send message").click()
    expect(page.locator(".story-shell.workspace-visible")).to_be_visible(timeout=20000)
    expect(page.locator("[data-workspace-tab='memoir']")).to_be_visible()
    expect(page.locator(".workspace-media-overview")).to_have_count(0)
    expect(page.get_by_role("textbox", name="Your message")).to_be_visible()


def test_city_alias_keeps_saved_photos_without_repeating_discovery(interview):
    page = interview
    searches = []
    def photos(route):
        searches.append(route.request.url)
        route.fulfill(json={"status": "READY", "items": [{
            "asset_id": "chengde-saved", "title": "Chengde reference",
            "image_url": "/static/timeline_avatar_child_female.png",
            "date_expression": "1983", "latitude": 40.9517, "longitude": 117.9632,
            "allowed_actions": {"embed": True}}], "next_cursor": None})
    page.route("**/place-photos?**", photos)
    turn = {"reply": "What do you remember about the city?",
        "place_journey": {"place": "承德市", "hierarchy": ["Earth", "中国", "河北省", "承德市"],
            "granularity": "city", "latitude": 40.9517, "longitude": 117.9632,
            "period": "1980s", "life_stage": "childhood", "revision": 2},
        "place_journey_change": {"changed": True}}
    mock_workspace_turn(page, lambda route: route.fulfill(json=turn))
    page.get_by_role("textbox", name="Your message").fill("I remember 承德市 in the 1980s.")
    page.get_by_role("button", name="Send message").click()
    expect(page.get_by_role("img", name="Chengde reference", exact=True)).to_be_visible(timeout=20000)
    expect(page.get_by_role("button", name="Send message")).to_be_enabled(timeout=20000)
    page.wait_for_load_state("networkidle")
    assert len(searches) == 1

    turn["place_journey"] = {"place": "承德", "hierarchy": ["Earth", "中国", "河北", "承德"],
        "granularity": "city", "period": "1980s", "life_stage": "young_adulthood", "revision": 3}
    page.get_by_role("textbox", name="Your message").fill("I returned to 承德 in the 1980s.")
    page.get_by_role("button", name="Send message").click()
    expect(page.get_by_role("button", name="Send message")).to_be_enabled(timeout=20000)
    expect(page.get_by_role("img", name="Chengde reference", exact=True)).to_be_visible()
    page.wait_for_load_state("networkidle")
    assert len(searches) == 1, "a city suffix alias must reuse saved photo discovery"
    page.reload()
    expect(page.get_by_role("img", name="Chengde reference", exact=True)).to_be_visible(timeout=20000)
    assert len(searches) == 1
