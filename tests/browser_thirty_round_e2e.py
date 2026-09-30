"""Exercise a 30-turn Memoir chat in the rendered browser with deterministic API replies.

Run against the local source server with:
    python3 tests/browser_thirty_round_e2e.py --base-url http://127.0.0.1:3011

This verifies browser history and the existing place, family, timeline, and public-cue
rendering contracts. It does not exercise live model selection or durable Supabase history.
"""

from __future__ import annotations

import argparse
import json

from playwright.sync_api import expect, sync_playwright

from browser_ten_round_e2e import (
    AUTHOR_TIMELINE_CONTEXT,
    CASES,
    EMPTY_FAMILY_CONTEXT,
    FAMILY_TREE_CONTEXT,
    PLACE_JOURNEY,
    PUBLIC_CUE,
    family_update,
    goto_ready,
)


def run_case(browser, base_url: str) -> None:
    locale = "en-AU"
    case = CASES[locale]
    agent_requests: list[dict] = []
    answer_requests: list[dict] = []
    page_errors: list[str] = []
    page = browser.new_page(locale=locale, viewport={"width": 1440, "height": 960})
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    def story_state(route) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "user_id": "thirty-round-test-user",
                    "is_anonymous": False,
                    "rounds_required": 5,
                    "rounds_completed": 5,
                    "free_chapter_claimed": True,
                    "payment_status": "paid",
                    "payment_plan": "family_memoir_v1",
                    "payment_features": ["family_tree", "timeline", "expanded_details"],
                    "family_features_enabled": True,
                    "next_action": "full_memoir",
                }
            ),
        )

    def family_context(route) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "project_id": "project-thirty-rounds",
                    "family_features_enabled": True,
                    "family_context": EMPTY_FAMILY_CONTEXT,
                    "family_context_update": None,
                }
            ),
        )

    def memory_answer(route) -> None:
        if route.request.method != "POST":
            route.fallback()
            return
        answer_requests.append(route.request.post_data_json or {})
        round_number = len(answer_requests)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "id": "memory-session-thirty-rounds",
                    "turns": [{"turn": index} for index in range(1, round_number + 1)],
                    "follow_ups_offered": 3,
                    "follow_ups_used": 0,
                    "context_cues": [PUBLIC_CUE] if round_number == 4 else [],
                }
            ),
        )

    def agent_turn(route) -> None:
        if route.request.method != "POST":
            route.fallback()
            return
        payload = route.request.post_data_json or {}
        agent_requests.append(payload)
        round_number = len(agent_requests)
        assert payload.get("language") == locale, payload
        assert payload.get("project_id"), payload
        assert payload.get("first_reply_localization") is (round_number == 1), payload
        response = {
            "reply": f"Round {round_number}: I’ve kept that detail with the story. What else comes to mind?",
            "trace": [],
            "trace_mode": "codex",
        }
        if round_number == 1:
            response.update(
                {
                    "profile_updates": {
                        "preferred_language": locale,
                        "name": "Avery",
                        "childhood_place": "Hobart",
                    },
                    # The local map adapter needs coordinates before it can
                    # render the place card; the existing fixture leaves them
                    # blank so its separate geocoder test can cover that path.
                    "place_journey": {**PLACE_JOURNEY, "latitude": -42.8821, "longitude": 147.3272},
                    "place_journey_change": {"changed": True, "kind": "created", "revision": 1},
                }
            )
        elif round_number == 2:
            response.update(
                {
                    "family_features_enabled": True,
                    "family_context": FAMILY_TREE_CONTEXT,
                    "family_context_update": family_update(
                        ["family_tree"], 1, {"people": 2, "relationships": 1}
                    ),
                }
            )
        elif round_number == 3:
            response.update(
                {
                    "family_features_enabled": True,
                    "family_context": AUTHOR_TIMELINE_CONTEXT,
                    "family_context_update": family_update(["author_timeline"], 2, {"timeline": 1}),
                }
            )
        route.fulfill(status=200, content_type="application/json", body=json.dumps(response))

    page.route("**/place-photos?**", lambda route: route.fulfill(json={"items": []}))
    page.route("**/api/v1/memoir/story/state", story_state)
    page.route("**/api/v1/memoir/agent/family-context*", family_context)
    page.route("**/api/v1/memoir/memory-sessions/*/answers", memory_answer)
    page.route("**/api/v1/memoir/agent/turn", agent_turn)
    page.route("**/unpkg.com/**", lambda route: route.abort())

    try:
        goto_ready(page, f"{base_url}/memoir")
        expect(page.get_by_role("heading", name=case["landing_heading"])).to_be_visible(timeout=15000)
        expect(page.get_by_role("combobox", name=case["language_label"])).to_have_value(locale)
        page.locator("[data-action='start-story'][data-mode='self']").click()
        expect(page.locator("main.chat-main")).to_be_visible()
        expect(page.locator(".assistant-message .message-text").first).to_contain_text(case["opening"])

        for round_number in range(1, 31):
            if round_number <= len(case["user_messages"]):
                message = case["user_messages"][round_number - 1]
            else:
                message = (
                    f"Another part of that same life story, detail {round_number}: "
                    "I remember who was there and how the place changed over time."
                )
            page.locator("#chat-input").fill(message)
            page.locator("#chat-form button[type='submit']").click()
            reply = page.locator(".assistant-message .message-text").last
            expect(reply).to_contain_text(f"Round {round_number}", timeout=20000)
            expect(page.locator(".assistant-message.message-streaming")).to_have_count(0, timeout=20000)

            if round_number == 1:
                expect(page.locator(".workspace-media-overview").get_by_role("heading", name="Hobart")).to_be_visible()
            elif round_number == 2:
                page.locator("[data-workspace-tab='family']").click()
                expect(page.locator("#workspace-detail .people-list strong", has_text="Mei")).to_be_visible()
            elif round_number == 3:
                page.locator("[data-workspace-tab='timeline']").click()
                expect(page.locator("#workspace-detail .timeline-list strong", has_text="Started school")).to_be_visible()
            elif round_number == 4:
                expect(page.locator(".workspace-media-gallery").get_by_text(PUBLIC_CUE["title"])).to_be_visible()

        expect(page.locator(".user-message")).to_have_count(30)
        expect(page.locator(".assistant-message")).to_have_count(31)
        history = page.evaluate(
            """() => {
              const key = Array.from({length: sessionStorage.length}, (_, i) => sessionStorage.key(i))
                .find(item => item?.startsWith('memory-spark-chat-history:'));
              return key ? JSON.parse(sessionStorage.getItem(key) || '[]') : [];
            }"""
        )
        assert len(history) == 61, f"Expected 61 persisted chat entries, got {len(history)}"
        assert sum(item.get("role") == "user" for item in history) == 30
        assert sum(item.get("role") == "assistant" for item in history) == 31
        assert len(agent_requests) == 30, f"Expected 30 agent requests, got {len(agent_requests)}"
        assert len(answer_requests) == 30, f"Expected 30 memory-answer requests, got {len(answer_requests)}"
        assert agent_requests[0]["first_reply_localization"] is True
        assert all(not request.get("first_reply_localization") for request in agent_requests[1:])
        assert not page_errors, "Browser page errors: " + "; ".join(page_errors)
    finally:
        page.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a 30-turn browser Memoir history smoke test.")
    parser.add_argument("--base-url", default="http://127.0.0.1:3010")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        run_case(browser, args.base_url)
        browser.close()
    print("PASS: 30 rendered chat turns, 31 assistant messages, place/family/timeline/cue UI contracts")


if __name__ == "__main__":
    main()
