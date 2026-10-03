from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect, sync_playwright


PLACE_JOURNEY = {
    "schema_version": 1,
    "status": "active",
    "revision": 1,
    "place": "Hobart",
    "hierarchy": ["Earth", "Australia", "Tasmania", "Hobart"],
    "granularity": "city",
    "latitude": None,
    "longitude": None,
    "duration_ms": 5200,
    "updated_at": "2026-09-26T00:00:00Z",
}

EMPTY_FAMILY_CONTEXT = {
    "schema_version": 1,
    "project_id": "project-test",
    "revision": 0,
    "updated_at": "2026-09-26T00:00:00Z",
    "people": [],
    "relationships": [],
    "timeline": [],
    "life_periods": [],
}

FAMILY_TREE_CONTEXT = {
    **EMPTY_FAMILY_CONTEXT,
    "revision": 1,
    "people": [
        {"id": "p-mum", "name": "Mei", "family_title": "mother"},
        {"id": "p-me", "name": "Avery"},
    ],
    "relationships": [
        {"from_person_id": "p-mum", "to_person_id": "p-me", "relationship_type": "parent"}
    ],
}

AUTHOR_TIMELINE_CONTEXT = {
    **FAMILY_TREE_CONTEXT,
    "revision": 2,
    "timeline": [
        {
            "id": "e-school",
            "title": "Started school",
            "date_expression": "around 1964",
            "precision": "approximate",
            "place": "Hobart",
            "person_ids": ["p-me"],
        }
    ],
}

PUBLIC_CUE = {
    "asset_id": "public-hobart-1960",
    "kind": "image",
    "title": "霍巴特海滨，1960年代",
    "location": "霍巴特",
    "scene_date_range": {"start": "1960", "end": "1969"},
    "label": "公共历史线索",
    "allowed_actions": {"embed": True},
    "source_url": "https://example.com/hobart-reference",
}

CASES = {
    "en-AU": {
        "landing_heading": "Start with a conversation.",
        "language_label": "Language",
        "opening": "Hi, I’m Mira. It’s nice to meet you.",
        "reply": lambda round_number: (
            f"Round {round_number}: Thank you for continuing this memory. We will keep your original "
            "details and follow this thread gently. This longer reply verifies that assistant text "
            "appears progressively in the browser."
        ),
        "timeline_label": "around 1964 · Approximate date · Hobart",
        "user_messages": [
            "I remember a summer afternoon by the water in Hobart.",
            "My mother Mei walked with me through that memory.",
            "I started school around 1964.",
            "I also remember an old photo near the waterfront.",
            "The kitchen smells and sunlight are still clear.",
            "I want to preserve this story about my family.",
            "We kept talking about that afternoon afterwards.",
            "Some dates I can only remember as a rough range.",
            "I hope my family understands how it felt.",
            "This is the memory I most want to keep.",
        ],
    },
    "zh-CN": {
        "landing_heading": "用自己的话，讲述自己的人生",
        "language_label": "语言",
        "opening": "你好，我是 Mira。很高兴认识你。",
        "reply": lambda round_number: (
            f"第 {round_number} 轮：谢谢你继续讲述这段回忆。我们会保留你说出的原始细节，"
            "并慢慢沿着这条线索继续。这一段较长的回复用于验证助手文字会在浏览器中逐步出现。"
        ),
        "timeline_label": "around 1964 · 大致日期 · Hobart",
        "user_messages": [
            "我记得在霍巴特海边的一个夏日午后。",
            "我的母亲 Mei 陪我走过那段回忆。",
            "我大约在 1964 年开始上学。",
            "那时我还记得海滨附近的一张旧照片。",
            "厨房里的气味和阳光到现在仍然很清楚。",
            "我想把这段关于家人的故事留下来。",
            "后来我们仍会谈起那个下午。",
            "有些日期我只能记得大概的范围。",
            "我希望家人读到时能理解当时的感受。",
            "这就是我现在最想保存的一段回忆。",
        ],
    },
}


def family_update(skills: list[str], revision: int, added: dict[str, int]) -> dict:
    return {
        "schema_version": 1,
        "project_id": "project-test",
        "changed": True,
        "persisted": True,
        "revision": revision,
        "skills": skills,
        "added": {"people": 0, "relationships": 0, "timeline": 0, "life_periods": 0, **added},
        "updated": {"people": 0, "relationships": 0, "timeline": 0, "life_periods": 0},
    }


def goto_ready(page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except PlaywrightTimeoutError:
        # Next dev's HMR/external font connections can remain active even
        # after the rendered application is ready; the assertions below wait
        # on the actual UI state.
        pass


def run_case(browser, base_url: str, locale: str) -> None:
    case = CASES[locale]
    agent_requests: list[dict] = []
    answer_requests: list[dict] = []
    profile_requests: list[dict] = []
    page_errors: list[str] = []

    context = browser.new_context(
        locale=locale,
        viewport={"width": 1440, "height": 960},
        device_scale_factor=1,
    )
    page = context.new_page()
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "request",
        lambda request: profile_requests.append(request.post_data_json or {})
        if request.method == "PATCH" and "/projects/" in request.url
        else None,
    )

    def family_state(route) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "user_id": f"ten-round-test-user-{locale}",
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
                    "project_id": "project-test",
                    "family_features_enabled": True,
                    "family_context": None,
                    "family_context_update": None,
                }
            ),
        )

    def memory_answer(route) -> None:
        if route.request.method != "POST":
            route.fallback()
            return
        payload = route.request.post_data_json or {}
        answer_requests.append(payload)
        round_number = len(answer_requests)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "id": f"memory-session-test-{locale}",
                    "turns": [{"turn": index} for index in range(1, round_number + 1)],
                    "follow_ups_offered": 3,
                    "follow_ups_used": 0,
                    "context_cues": [PUBLIC_CUE] if round_number == 4 else [],
                }
            ),
        )

    def codex_turn(route) -> None:
        if route.request.method != "POST":
            route.fallback()
            return
        payload = route.request.post_data_json or {}
        agent_requests.append(payload)
        call_number = len(agent_requests)
        assert payload.get("language") == locale, payload
        assert payload.get("project_id"), payload
        assert payload.get("first_reply_localization") is (call_number == 1), payload
        response = {"reply": case["reply"](call_number), "trace": [], "trace_mode": "codex"}
        if call_number == 1:
            response.update(
                {
                    "profile_updates": {
                        "preferred_language": locale,
                        "name": "Avery",
                        "childhood_place": "Hobart",
                        "story_focus": {
                            "who": "my mother",
                            "where": "the waterfront",
                            "when": "a summer afternoon",
                            "what": "the feeling of being together",
                        },
                    },
                    "place_journey": PLACE_JOURNEY,
                    "place_journey_change": {"changed": True, "kind": "created", "revision": 1},
                }
            )
        elif call_number == 2:
            response.update(
                {
                    "family_features_enabled": True,
                    "family_context": FAMILY_TREE_CONTEXT,
                    "family_context_update": family_update(
                        ["family_tree"], 1, {"people": 2, "relationships": 1}
                    ),
                }
            )
        elif call_number == 3:
            response.update(
                {
                    "family_features_enabled": True,
                    "family_context": AUTHOR_TIMELINE_CONTEXT,
                    "family_context_update": family_update(["author_timeline"], 2, {"timeline": 1}),
                }
            )
        route.fulfill(status=200, content_type="application/json", body=json.dumps(response))

    page.route("**/place-photos?**", lambda route: route.fulfill(json={"items": []}))
    page.route("**/api/v1/memoir/story/state", family_state)
    page.route("**/api/v1/memoir/agent/family-context*", family_context)
    page.route("**/api/v1/memoir/memory-sessions/*/answers", memory_answer)
    page.route("**/api/v1/memoir/agent/turn", codex_turn)
    # The journey intentionally verifies renderer fallbacks; library adapters
    # have their own browser contract tests.
    page.route("**/unpkg.com/**", lambda route: route.abort())

    try:
        goto_ready(page, f"{base_url}/memoir")
        expect(page.get_by_role("heading", name=case["landing_heading"])).to_be_visible(timeout=15000)
        expect(page.get_by_role("combobox", name=case["language_label"])).to_have_value(locale)
        page.wait_for_function(
            "() => typeof globalThis.__copyme2Intl?.messages?.Memoir?.conversation?.opening === 'string'"
        )
        assert page.evaluate("document.documentElement.lang") == locale

        page.locator("[data-action='start-story'][data-mode='self']").click()
        expect(page.locator("main.chat-main")).to_be_visible()
        expect(page.locator(".assistant-message .message-text").first).to_contain_text(case["opening"])
        expect(page.locator(".assistant-message.message-streaming")).to_have_count(0, timeout=10000)
        assert len(agent_requests) == 0, f"The fixed opening must not start an agent turn; got {agent_requests}"

        for round_number, text in enumerate(case["user_messages"], start=1):
            page.locator("#chat-input").fill(text)
            page.locator("#chat-form button[type='submit']").click()

            streaming = page.locator(".assistant-message.message-streaming")
            expect(streaming).to_have_count(1, timeout=10000)
            expect(streaming.last.locator(".message-text")).to_contain_text(
                f"第 {round_number} 轮" if locale == "zh-CN" else f"Round {round_number}",
                timeout=10000,
            )
            expect(page.locator(".assistant-message .message-text").last).to_contain_text(
                f"第 {round_number} 轮" if locale == "zh-CN" else f"Round {round_number}",
                timeout=15000,
            )
            expect(streaming).to_have_count(0, timeout=15000)

            if round_number == 1:
                places = page.locator(".workspace-media-overview")
                expect(places).to_be_visible()
                expect(places.get_by_role("heading", name="Hobart")).to_be_visible()
            elif round_number == 2:
                page.locator("[data-workspace-tab='family']").click()
                family = page.locator("#workspace-detail")
                expect(family.locator(".family-person-card strong", has_text="Mei")).to_be_visible()
                expect(family.locator("[data-renderer-status='fallback']")).to_be_visible(timeout=10000)
            elif round_number == 3:
                page.locator("[data-workspace-tab='timeline']").click()
                timeline = page.locator("#workspace-detail")
                expect(timeline.locator(".timeline-list strong", has_text="Started school")).to_be_visible()
                expect(timeline.get_by_text(case["timeline_label"], exact=True)).to_be_visible()
                expect(timeline.locator("[data-renderer-status='fallback']")).to_be_visible(timeout=10000)
            elif round_number == 4:
                pictures = page.locator(".workspace-media-gallery")
                expect(pictures.get_by_text(PUBLIC_CUE["title"])).to_be_visible()
                expect(pictures.get_by_text("公共历史线索 · 不是个人证据")).to_have_count(0)

        expect(page.locator(".user-message")).to_have_count(10)
        expect(page.locator(".assistant-message")).to_have_count(11)
        assert len(agent_requests) == 10, f"Expected ten agent turns, got {len(agent_requests)}"
        assert len(answer_requests) == 10, f"Expected ten memory answers, got {len(answer_requests)}"
        assert all(request.get("language") == locale for request in agent_requests)
        assert agent_requests[0].get("first_reply_localization") is True
        assert all(not request.get("first_reply_localization") for request in agent_requests[1:])
        assert any(
            request.get("profile", {}).get("preferred_language") == locale
            for request in profile_requests
        ), profile_requests
        assert not page_errors, "Browser page errors: " + "; ".join(page_errors)
        assert "MEMORY_SPARK_" not in page.locator("body").inner_text()

        output = (
            Path(__file__).resolve().parents[1]
            / "output"
            / "playwright"
            / f"chat-ten-rounds-{locale}.png"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output), full_page=True)
    finally:
        context.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run ten localized chat turns through the rendered Memoir workspace."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:3010")
    parser.add_argument("--locale", choices=["all", *CASES], default="all")
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        locales = CASES if args.locale == "all" else {args.locale: CASES[args.locale]}
        for locale in locales:
            run_case(browser, args.base_url, locale)
        browser.close()
    print(f"Ten-round localized chat passed for: {', '.join(locales)}")


if __name__ == "__main__":
    main()
