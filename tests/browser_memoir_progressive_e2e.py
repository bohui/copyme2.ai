"""Drive the memoir UI through 31 turns in China and Australia.

The server remains real for project/session setup; the browser-only worker
responses are deterministic so this test can assert the UI contract without a
live model.  The final turn emits the same stage-3 composition envelope that a
composer worker would return, including structured chapter blocks.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect, sync_playwright

from browser_ten_round_e2e import goto_ready
from fixtures.browser_memory_events import school_events


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads((ROOT / "tests/evaluation/memoir_progressive_cases.json").read_text(encoding="utf-8"))
PROFILES = {profile["locale"]: profile for profile in FIXTURE["profiles"] if profile["locale"] in {"zh-CN", "en-AU"}}


def rounds_for(profile: dict) -> list[str]:
    rounds: list[str] = []
    for number in range(1, 32):
        phase = 0 if number <= 8 else 1 if number <= 16 else 2 if number <= 24 else 3
        lead = f"第{number}轮，我记得" if profile["locale"] == "zh-CN" else f"Round {number}: I remember"
        text = f"{lead}{profile['life_arc'][phase]}。"
        cue = profile.get("round_cues", {}).get(str(number))
        if cue:
            text += f" {cue}"
        detail = {16: profile["family_detail"], 21: profile["date_detail"], 26: profile["photo_detail"]}.get(number)
        if detail:
            text += f" {detail}"
        rounds.append(text)
    return rounds


def place_for(profile: dict) -> dict:
    return {
        "schema_version": 1,
        "status": "active",
        "revision": 1,
        "place": profile["place"],
        "hierarchy": profile["hierarchy"],
        "granularity": "city",
        # Leave coordinates unresolved so the browser must call the place-map
        # adapter before the location workspace can render.
        "latitude": None,
        "longitude": None,
        "duration_ms": 80,
        "life_stage": "childhood",
        "updated_at": "2026-10-02T00:00:00Z",
    }


def family_context() -> dict:
    return {
        "schema_version": 1,
        "project_id": "progressive-browser-project",
        "revision": 0,
        "updated_at": "2026-10-02T00:00:00Z",
        "people": [],
        "relationships": [],
        "timeline": [],
        "life_periods": [],
    }


def family_context_with_content(revision: int) -> dict:
    context = family_context()
    context.update(
        {
            "revision": revision,
            "people": [
                {"id": "person-mei", "name": "Mei", "family_title": "mother"},
                {"id": "person-storyteller", "name": "The storyteller"},
            ],
            "relationships": [
                {"from_person_id": "person-mei", "to_person_id": "person-storyteller", "relationship_type": "parent"}
            ],
            "timeline": (
                [
                    {
                        "id": "timeline-school",
                        "title": "Started school",
                        "date_expression": "around 1964",
                        "precision": "approximate",
                        "place": "the remembered hometown",
                        "person_ids": ["person-storyteller"],
                    }
                ]
                if revision >= 2
                else []
            ),
        }
    )
    return context


def public_cue(profile: dict) -> dict:
    return {
        "asset_id": f"public-reference-{profile['id']}",
        "kind": "image",
        "title": f"{profile['place']} public reference",
        "location": profile["place"],
        "scene_date_range": {"start": "1960", "end": "1969"},
        "label": "Public historical reference",
        "allowed_actions": {"embed": True},
        "source_url": "https://example.com/public-reference",
    }


def composer_chapters(profile: dict) -> list[dict]:
    if profile["locale"] == "zh-CN":
        titles = ["在熟悉的地方长大", "离开熟悉的街道", "承担与改变", "回望普通日子"]
        paragraphs = [
            f"我记得在{profile['place']}长大的最初场景。",
            profile["family_detail"],
            f"我记得{profile['date_detail']}发生过一些改变。",
            f"{profile['photo_detail']}我愿意把这些普通日子留给未来的读者。",
        ]
    else:
        titles = ["The Place Where I Began", "Leaving What I Knew", "Work, Family and Change", "What I Carry Forward"]
        paragraphs = [
            f"I remember the first scenes of growing up in {profile['place']}.",
            profile["family_detail"],
            f"I remember changes around {profile['date_detail']}.",
            f"{profile['photo_detail']}. I want to leave these ordinary days for a future reader.",
        ]
    chapters = []
    for index, (title, paragraph) in enumerate(zip(titles, paragraphs), start=1):
        chapters.append(
            {
                "id": f"composer-chapter-{index}",
                "chapter_number": index,
                "title": title,
                "status": "DRAFT",
                "blocks": [
                    {"id": f"composer-heading-{index}", "type": "heading", "text": title},
                    {"id": f"composer-paragraph-{index}", "type": "narrative", "text": paragraph},
                ],
                "source_memory_ids": [f"round-{index:02d}"],
            }
        )
    return chapters


def run_case(browser, base_url: str, locale: str) -> None:
    profile = PROFILES[locale]
    messages = json.loads((ROOT / f"apps/web/messages/{locale}.json").read_text(encoding="utf-8"))
    workspace_copy = messages["Memoir"]["workspace"]
    rounds = rounds_for(profile)
    journey = place_for(profile)
    cue = public_cue(profile)
    chapters = composer_chapters(profile)
    photo_year = next((year for year in range(1900, 2101) if str(year) in profile["date_detail"]), 1994)
    journey['period'] = '1990s' if locale == 'zh-CN' else profile['date_detail']
    cue['scene_date_range'] = {'start': str(photo_year), 'end': str(photo_year)}
    latitude, longitude = {'西安': (34.3416, 108.9398), 'Sydney': (-33.8688, 151.2093)}[profile['place']]
    agent_requests: list[dict] = []
    answer_requests: list[dict] = []
    place_group_requests: list[dict] = []
    place_map_requests: list[dict] = []
    photo_requests: list[dict] = []
    page_errors: list[str] = []

    context = browser.new_context(locale=locale, viewport={"width": 1440, "height": 960}, device_scale_factor=1)
    page = context.new_page()
    page.set_default_navigation_timeout(60000)
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    def project_payload(project_id: str, profile_data: dict | None = None) -> dict:
        return {
            "id": project_id,
            "revision": 1,
            "policy_epoch": 1,
            "mode": "self",
            "owner_id": f"progressive-user-{locale}",
            "storyteller_id": f"progressive-user-{locale}",
            "home_region": "au" if locale == "en-AU" else "cn",
            "profile": profile_data or {"name": "Avery", "memory_places": []},
            "consent": {},
            "preferences": {},
            "member_count": 1,
            "entitlements": {},
            "trial_units_remaining": 0,
            "completed_sessions": 0,
            "free_chapter_available": False,
            "preview": None,
            "composition_stage": 0,
            "workspace_unlocked": False,
            "first_chapter_free": False,
            "deletion_state": "ACTIVE",
            "created_at": "2026-10-02T00:00:00Z",
        }

    def fulfill(route, data: dict, status: int = 200) -> None:
        return route.fulfill(status=status, content_type="application/json", body=json.dumps(data, ensure_ascii=False))

    def api(route) -> None:
        request = route.request
        path = request.url.split("/api/v1/memoir", 1)[-1].split("?", 1)[0]
        if path == "/agent/config" and request.method == "GET":
            return fulfill(route, {"supabase_url": "https://auth.test", "supabase_publishable_key": "public", "auth_mode": "supabase"})
        if path in {"/agent/profile", "/user/profile"} and request.method == "GET":
            return fulfill(route, {"name": "Avery", "memory_places": []})
        if path == "/story/state" and request.method == "GET":
            return fulfill(
                route,
                {
                    "user_id": f"progressive-user-{locale}",
                    "is_anonymous": False,
                    "rounds_required": 20,
                    "rounds_completed": 31,
                    "free_chapter_claimed": True,
                    "payment_status": "paid",
                    "payment_plan": "family_memoir_v1",
                    "payment_features": ["family_tree", "timeline", "expanded_details"],
                    "family_features_enabled": True,
                    "next_action": "full_memoir",
                }
            )
        if path.startswith("/agent/family-context") and request.method == "GET":
            return fulfill(route, {"project_id": "progressive-browser-project", "family_features_enabled": True, "family_context": None, "family_context_update": None})
        if path == "/story/readiness" and request.method == "GET":
            return fulfill(route, {"project_id": "progressive-browser-project", "stages": {}})
        if path == '/story/events' and request.method == 'GET':
            return school_events(route, present=len(agent_requests) >= 3, completed_rounds=len(agent_requests))
        if path == "/story/private-draft" and request.method == "GET":
            return fulfill(route, {"status": "none", "preview": None, "updating": False})
        if path == "/user/conversations" and request.method == "GET":
            return fulfill(route, {"items": []})
        if path.endswith("/journey") and path.startswith("/projects/") and request.method == "GET":
            return fulfill(route, {"active_session": None})
        if path.startswith("/projects/") and path.endswith("/chapters") and request.method == "GET":
            return fulfill(route, {"items": chapters})
        if path.startswith("/projects/") and any(path.endswith(suffix) for suffix in ("/memories", "/sources", "/people", "/relationships", "/timeline")) and request.method == "GET":
            return fulfill(route, {"items": []})
        if path.startswith("/projects/") and path.count("/") == 2 and request.method == "GET":
            project_id = path.split("/")[-1]
            return fulfill(route, project_payload(project_id))
        if path.startswith("/projects/") and path.count("/") == 2 and request.method == "PATCH":
            project_id = path.split("/")[-1]
            body = request.post_data_json or {}
            return fulfill(route, project_payload(project_id, body.get("profile") or {"name": "Avery", "memory_places": []}))
        if path.startswith("/projects/") and path.endswith("/place-groups") and request.method == "POST":
            payload = request.post_data_json or {}
            place_group_requests.append(payload)
            records = []
            for index, item in enumerate(payload.get("places", [])):
                records.append({"index": index, "city": item, "city_key": json.dumps(item.get("hierarchy", []), ensure_ascii=False), "pin": item})
            return fulfill(route, {"places": records})
        if path.startswith("/projects/") and path.endswith("/place-map") and request.method == "POST":
            payload = request.post_data_json or {}
            place_map_requests.append(payload)
            return fulfill(route, {"target": {**payload, "latitude": latitude, "longitude": longitude}})
        if path.startswith("/projects/") and path.endswith("/place-photos") and request.method == "GET":
            photo_requests.append({"url": request.url})
            return fulfill(route, {"items": [{**cue, "date_expression": str(photo_year), "date_basis": "historical", "latitude": latitude, "longitude": longitude}], "status": "OK", "searching": False, "next_cursor": None})
        return route.fallback()

    def memory_answer(route) -> None:
        if route.request.method != "POST":
            return route.fallback()
        answer_requests.append(route.request.post_data_json or {})
        number = len(answer_requests)
        fulfill(
            route,
            {
                "id": f"progressive-session-{locale}",
                "turns": [{"turn": index} for index in range(1, number + 1)],
                "follow_ups_offered": 3,
                "follow_ups_used": 0,
                "context_cues": [cue] if number == 4 else [],
            }
        )

    def agent_turn(route) -> None:
        if route.request.method != "POST":
            return route.fallback()
        payload = route.request.post_data_json or {}
        agent_requests.append(payload)
        number = len(agent_requests)
        assert payload.get("language") == locale, payload
        assert payload.get("project_id"), payload
        assert payload.get("first_reply_localization") is (number == 1), payload
        response = {
            "reply": (f"第 {number} 轮：我会保留你说出的细节，并继续沿着这条记忆线索。" if locale == "zh-CN" else f"Round {number}: I will keep the details you supplied and follow this memory thread gently."),
            "trace": [],
            "trace_mode": "codex",
        }
        if number == 1:
            response.update(
                {
                    "profile_updates": {
                        "preferred_language": locale,
                        "name": "Avery",
                        "childhood_place": profile["place"],
                        "story_focus": {"who": "my family", "where": profile["place"], "when": profile["date_detail"], "what": "the details I still carry"},
                    },
                    "place_journey": journey,
                    "place_journey_change": {"changed": True, "kind": "created", "revision": 1},
                }
            )
        elif number == 2:
            response.update(
                {
                    "family_features_enabled": True,
                    "family_context": family_context_with_content(1),
                    "family_context_update": {"persisted": True, "changed": True, "revision": 1, "skills": ["family_tree"], "added": {"people": 2, "relationships": 1}},
                }
            )
        elif number == 3:
            response.update(
                {
                    "family_features_enabled": True,
                    "family_context": family_context_with_content(2),
                    "family_context_update": {"persisted": True, "changed": True, "revision": 2, "skills": ["author_timeline"], "added": {"timeline": 1}},
                }
            )
        elif number == 31:
            response.update(
                {
                    "composition_stage": 3,
                    "composer_delivery": {"stage": 3, "status": "review", "chapters": chapters},
                }
            )
        if response.get('family_context'):
            response['family_context'] = {**response['family_context'], 'project_id': payload['project_id']}
            response['family_context_update']['project_id'] = payload['project_id']
        return fulfill(route, response)

    page.route("**/api/v1/memoir/**", api)
    page.route("**/api/v1/memoir/memory-sessions/*/answers", memory_answer)
    page.route("**/api/v1/memoir/agent/turn", agent_turn)
    page.route("https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2", lambda route: route.fulfill(content_type="text/javascript", body=(
        "window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:{access_token:'fixture-only',user:{id:'progressive-user',is_anonymous:false,user_metadata:{}}}}}),getUser:async()=>({data:{user:{id:'progressive-user',is_anonymous:false,user_metadata:{}}}}),onAuthStateChange:()=>({})}})};"
    )))
    page.route("**/unpkg.com/**", lambda route: route.abort())

    try:
        goto_ready(page, f"{base_url}/memoir")
        expect(page.get_by_role("heading", name=messages["Memoir"]["landing"]["title"])).to_be_visible(timeout=15000)
        page.locator("[data-action='start-story'][data-mode='self']").click()
        expect(page.locator("main.chat-main")).to_be_visible(timeout=15000)
        expect(page.locator(".assistant-message .message-text").first).to_contain_text(messages["Memoir"]["conversation"]["opening"].splitlines()[0])

        for number, message in enumerate(rounds, start=1):
            page.locator("#chat-input").fill(message)
            page.locator("#chat-form button[type='submit']").click()
            expected_round = f"第 {number} 轮" if locale == "zh-CN" else f"Round {number}"
            expect(page.locator(".assistant-message .message-text").last).to_contain_text(expected_round, timeout=20000)
            expect(page.locator(".assistant-message.message-streaming")).to_have_count(0, timeout=20000)

            if number == 1:
                expect(page.locator(".workspace-media-overview")).to_be_visible()
                expect(page.locator(".workspace-media-overview").get_by_role("heading", name=profile["place"])).to_be_visible()
            elif number == 2:
                page.locator("[data-workspace-tab='family']").click()
                expect(page.locator("#workspace-detail .family-person-card strong", has_text="Mei")).to_be_visible()
            elif number == 3:
                page.locator("[data-workspace-tab='timeline']").click()
                expect(page.locator("#workspace-detail .timeline-list strong", has_text="Started school")).to_be_visible()
            elif number == 4:
                expect(page.locator(".workspace-media-gallery").get_by_text(cue["title"])).to_be_visible()
            elif number == 31:
                expect(page.locator("[data-workspace-tab='memoir']")).to_be_visible()
                expect(page.locator(".workspace-media-overview")).to_have_count(0)
                page.locator("[data-workspace-tab='memoir']").click()
                expect(page.locator(".chapter-card")).to_have_count(1)
                expect(page.locator(".chapter-body")).to_have_count(1)
                expect(page.locator(".chapter-body-block")).to_have_count(1)
                for chapter in chapters:
                    page.locator('.chapter-page-numbers button').nth(chapter['chapter_number'] - 1).click()
                    expect(page.locator(".chapter-card")).to_contain_text(chapter["blocks"][1]["text"])
                expect(page.locator(".workspace-media-gallery")).to_have_count(0)

        expect(page.locator(".user-message")).to_have_count(31)
        expect(page.locator(".assistant-message")).to_have_count(32)
        assert len(agent_requests) == 31, (locale, len(agent_requests))
        assert not answer_requests, "Accepted narrator turns must not be duplicated through legacy memory answers"
        assert all(request.get('source_kind') == 'narrator_chat' for request in agent_requests)
        assert place_group_requests, f"{locale}: place-group skill did not make a request"
        assert place_map_requests, f"{locale}: place-map resolution did not make a request"
        assert photo_requests, f"{locale}: photo research request did not make a request"
        history = page.evaluate(
            """() => {
              const key = Array.from({length: sessionStorage.length}, (_, i) => sessionStorage.key(i))
                .find(item => item?.startsWith('memory-spark-chat-history:'));
              return key ? JSON.parse(sessionStorage.getItem(key) || '[]') : [];
            }"""
        )
        assert len(history) == 63, (locale, len(history))
        assert sum(item.get("role") == "user" for item in history) == 31
        assert sum(item.get("role") == "assistant" for item in history) == 32
        assert [request['conversation_text'] for request in agent_requests] == [
            item['text'] for item in history if item.get('role') == 'user'
        ]
        assert not page_errors, f"{locale}: browser page errors: {'; '.join(page_errors)}"
        assert "MEMORY_SPARK_" not in page.locator("body").inner_text()
        output = ROOT / "output" / "playwright" / f"memoir-progressive-{locale}.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output), full_page=True)
    finally:
        context.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run 31-round progressive memoir UI checks for China and Australia.")
    parser.add_argument("--base-url", default="http://127.0.0.1:3010")
    parser.add_argument("--locale", choices=["all", "en-AU", "zh-CN"], default="all")
    args = parser.parse_args()
    locales = ["zh-CN", "en-AU"] if args.locale == "all" else [args.locale]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for locale in locales:
            run_case(browser, args.base_url, locale)
        browser.close()
    print(f"PASS: 31-round progressive memoir UI checks for {', '.join(locales)}")


if __name__ == "__main__":
    main()
