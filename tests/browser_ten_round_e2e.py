from __future__ import annotations

import argparse
import json
from pathlib import Path

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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ten localized chat turns through the rendered Memoir workspace.")
    parser.add_argument("--base-url", default="http://127.0.0.1:3010")
    args = parser.parse_args()

    agent_requests: list[dict] = []
    answer_requests: list[dict] = []
    page_errors: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            locale="zh-CN",
            viewport={"width": 1440, "height": 960},
            device_scale_factor=1,
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        def family_state(route) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "user_id": "ten-round-test-user",
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
                        "id": "memory-session-test",
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
            assert payload.get("language") == "zh-CN", payload
            assert payload.get("project_id"), payload
            reply = (
                f"第 {call_number} 轮：谢谢你继续讲述这段回忆。我们会保留你说出的原始细节，"
                "并慢慢沿着这条线索继续。这一段较长的回复用于验证助手文字会在浏览器中逐步出现。"
            )
            response = {"reply": reply, "trace": [], "trace_mode": "codex"}
            if call_number == 1:
                response.update(
                    {
                        "profile_updates": {
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
        # This journey intentionally verifies the accessible renderer fallbacks;
        # the library adapters have their own browser contract tests.
        page.route("**/unpkg.com/**", lambda route: route.abort())

        page.goto(f"{args.base_url}/memoir", wait_until="networkidle")
        expect(page.get_by_role("heading", name="用自己的话，讲述自己的人生")).to_be_visible()
        expect(page.get_by_role("combobox", name="语言")).to_have_value("zh-CN")
        page.wait_for_function(
            "() => typeof globalThis.__copyme2Intl?.messages?.Memoir?.conversation?.opening === 'string'"
        )
        assert page.evaluate("document.documentElement.lang") == "zh-CN"

        page.locator("[data-action='start-story'][data-mode='self']").click()
        expect(page.get_by_role("main", name="Mira 的对话")).to_be_visible()
        expect(page.get_by_text("你好，我是 Mira。很高兴认识你。")).to_be_visible()
        expect(page.locator(".assistant-message.message-streaming")).to_have_count(0, timeout=10000)

        user_messages = [
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
        ]

        for round_number, text in enumerate(user_messages, start=1):
            page.locator("#chat-input").fill(text)
            page.locator("#chat-form button[type='submit']").click()

            streaming = page.locator(".assistant-message.message-streaming")
            expect(streaming).to_have_count(1, timeout=10000)
            expect(streaming.last.locator(".message-text")).to_contain_text(
                f"第 {round_number} 轮", timeout=10000
            )
            expect(page.locator(".assistant-message .message-text").last).to_contain_text(
                f"第 {round_number} 轮", timeout=15000
            )
            expect(streaming).to_have_count(0, timeout=15000)

            if round_number == 1:
                places = page.get_by_role("complementary", name="地点 工作区")
                expect(places).to_be_visible()
                # Place names are storyteller/source wording, not UI copy.
                expect(places.get_by_role("heading", name="Hobart")).to_be_visible()
            elif round_number == 2:
                family_tab = page.get_by_role("button", name="家族树")
                expect(family_tab).to_be_visible()
                family_tab.click()
                family = page.get_by_role("complementary", name="家族树 工作区")
                expect(family.locator(".people-list strong", has_text="Mei")).to_be_visible()
                expect(family.get_by_text("mother · parent")).to_be_visible()
                expect(family.locator("[data-renderer-status='fallback']")).to_be_visible(timeout=10000)
            elif round_number == 3:
                page.get_by_role("button", name="时间线").click()
                timeline = page.get_by_role("complementary", name="时间线 工作区")
                expect(timeline.locator(".timeline-list strong", has_text="Started school")).to_be_visible()
                expect(timeline.get_by_text("around 1964 · 大致日期 · Hobart", exact=True)).to_be_visible()
                expect(timeline.locator("[data-renderer-status='fallback']")).to_be_visible(timeout=10000)
            elif round_number == 4:
                pictures = page.locator(".workspace-media-gallery")
                expect(pictures.get_by_text("霍巴特海滨，1960年代")).to_be_visible()
                expect(pictures.get_by_text("公共历史线索 · 不是个人证据")).to_have_count(0)

        expect(page.locator(".user-message")).to_have_count(10)
        expect(page.locator(".assistant-message")).to_have_count(11)
        assert len(agent_requests) == 10, f"Expected ten agent turns, got {len(agent_requests)}"
        assert len(answer_requests) == 10, f"Expected ten memory answers, got {len(answer_requests)}"
        assert all(request.get("language") == "zh-CN" for request in agent_requests)
        assert all("MEMORY_SPARK_" not in request.get("text", "") for request in agent_requests)
        assert "MEMORY_SPARK_" not in page.locator("body").inner_text()
        assert not page_errors, "Browser page errors: " + "; ".join(page_errors)

        output = Path(__file__).resolve().parents[1] / "output" / "playwright" / "chat-ten-rounds-zh.png"
        output.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output), full_page=True)
        browser.close()


if __name__ == "__main__":
    main()
