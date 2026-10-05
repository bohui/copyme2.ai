from __future__ import annotations

import argparse
import json

from playwright.sync_api import expect, sync_playwright
from fixtures.browser_memory_events import SCHOOL_QUOTE, school_events


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the paid Family legacy workspace journey.")
    parser.add_argument("--base-url", default="http://127.0.0.1:3010")
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
        codex_calls = 0

        def family_state(route) -> None:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "user_id": "family-test-user",
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

        def codex_turn(route) -> None:
            nonlocal codex_calls, persisted
            codex_calls += 1
            request_payload = json.loads(route.request.post_data or "{}")
            assert request_payload.get("project_id")
            response = {"reply": "Tell me more about that family memory.", "trace": [], "trace_mode": "codex"}
            # The fixed opening is product copy; the first real storyteller
            # answer is the first Codex turn.
            if codex_calls >= 1:
                response["family_features_enabled"] = True
                response["family_context"] = {
                    "schema_version": 1,
                    "project_id": request_payload["project_id"],
                    "revision": 1,
                    "updated_at": "2026-09-26T00:00:00Z",
                    "people": [
                        {"id": "p-mum", "name": "Mei", "family_title": "mother"},
                        {"id": "p-me", "name": "Avery"},
                    ],
                    "relationships": [
                        {"from_person_id": "p-mum", "to_person_id": "p-me", "relationship_type": "parent"}
                    ],
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
                    "life_periods": [],
                }
                response["family_context_update"] = {
                    "schema_version": 1,
                    "project_id": request_payload["project_id"],
                    "changed": True,
                    "persisted": True,
                    "revision": 1,
                    "skills": ["family_tree", "author_timeline"],
                    "added": {"people": 2, "relationships": 1, "timeline": 1, "life_periods": 0},
                    "updated": {"people": 0, "relationships": 0, "timeline": 0, "life_periods": 0},
                }
                persisted = response["family_context"]
            route.fulfill(status=200, content_type="application/json", body=json.dumps(response))

        persisted = {
            "schema_version": 1,
            "project_id": "project-test",
            "revision": 1,
            "updated_at": "2026-09-26T00:00:00Z",
            "people": [{"id": "persisted-person", "name": "Persisted relative"}],
            "relationships": [],
            "timeline": [{"id": "persisted-event", "title": "Persisted moment", "date_expression": "the 1970s", "precision": "range"}],
            "life_periods": [],
        }

        page.route("**/api/v1/memoir/story/state", family_state)
        page.route(
            "**/api/v1/memoir/agent/family-context*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "project_id": "project-test",
                    "family_features_enabled": True,
                    "family_context": persisted,
                    "family_context_update": None,
                }),
            ),
        )
        page.route("**/api/v1/memoir/agent/turn", codex_turn)
        page.route("**/api/v1/memoir/story/events?**",
                   lambda route: school_events(route, present=codex_calls > 0))
        page.goto(args.base_url, wait_until="networkidle")
        page.get_by_role("button", name="Begin my story").click()
        expect(page.get_by_role("main", name="Mira conversation")).to_be_visible()
        page.get_by_role('button', name='Family tree', exact=True).click()
        expect(page.locator(".family-person-card strong", has_text="Persisted relative")).to_be_visible()

        page.get_by_role("textbox", name="Your message").fill("My mother Mei helped me start school around 1964 in Hobart.")
        page.get_by_role("button", name="Send message").click()

        expect(page.get_by_role("complementary", name="Family tree workspace")).to_be_visible()
        expect(page.locator(".family-person-card strong", has_text="Mei")).to_be_visible()
        expect(page.get_by_role("complementary", name="Family tree workspace").get_by_text("mother", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Timeline")).to_be_visible()

        page.get_by_role("button", name="Timeline").click()
        expect(page.get_by_role("heading", name="Timeline")).to_be_visible()
        timeline = page.get_by_role("complementary", name="Timeline workspace")
        expect(timeline.locator(".timeline-list strong", has_text="Started school")).to_be_visible()
        expect(timeline.locator('.timeline-row small')).to_have_text("around 1964 · Approximate date · Hobart · Childhood")
        expect(timeline.get_by_text("Approximate date · Hobart")).to_be_visible()
        timeline.get_by_text("Original evidence", exact=True).click()
        expect(timeline.get_by_text(SCHOOL_QUOTE, exact=True)).to_be_visible()
        browser.close()


if __name__ == "__main__":
    main()
