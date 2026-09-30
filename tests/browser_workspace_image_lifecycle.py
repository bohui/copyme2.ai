"""Keep a workspace image visible across late workspace re-renders."""
from __future__ import annotations

import argparse
import json
import time

from playwright.sync_api import expect, sync_playwright


PLACE_JOURNEY = {
    "schema_version": 1,
    "status": "active",
    "revision": 1,
    "place": "Hobart",
    "hierarchy": ["Earth", "Australia", "Tasmania", "Hobart"],
    "granularity": "city",
    "latitude": -42.8826,
    "longitude": 147.3257,
    "duration_ms": 5200,
    "updated_at": "2026-09-30T00:00:00Z",
}

PICTURE = {
    "asset_id": "public-hobart-image",
    "kind": "image",
    "title": "霍巴特海滨",
    "location": "霍巴特",
    "image_url": "/static/copyme2_icon_light.png",
    "source_url": "https://example.com/hobart-reference",
    "allowed_actions": {"embed": True},
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3010")
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960})

        def memory_answer(route) -> None:
            if route.request.method != "POST":
                route.fallback()
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "id": "memory-session-test",
                    "turns": [{"turn": 1}],
                    "follow_ups_offered": 1,
                    "follow_ups_used": 0,
                    "context_cues": [],
                }),
            )

        def codex_turn(route) -> None:
            nonlocal turn_calls
            turn_calls += 1
            if route.request.method != "POST":
                route.fallback()
                return
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "reply": "I hear the waterfront memory.",
                    "trace": [],
                    "trace_mode": "codex",
                    "place_journey": PLACE_JOURNEY,
                    "place_journey_change": {"changed": True, "kind": "created", "revision": 1},
                }),
            )

        def place_photos(route) -> None:
            nonlocal photo_calls
            photo_calls += 1
            time.sleep(0.35)
            items = [PICTURE] if photo_calls == 1 else []
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"items": items, "status": "READY" if items else "NO_MATCH",
                                 "next_cursor": "lifecycle:1" if items else None}),
            )

        turn_calls = 0
        photo_calls = 0

        page.route("**/api/v1/memoir/memory-sessions/*/answers", memory_answer)
        page.route("**/api/v1/memoir/agent/turn", codex_turn)
        page.route("**/place-photos?**", place_photos)
        page.goto(f"{args.base_url}/memoir", wait_until="networkidle")
        page.locator("[data-action='start-story'][data-mode='self']").click()
        expect(page.locator("main.chat-main")).to_be_visible()
        expect(page.locator(".assistant-message .message-text").first).to_be_visible(timeout=10000)
        expect(page.locator(".message-streaming")).to_have_count(0, timeout=10000)
        page.locator("#chat-input").fill("I remember a summer afternoon by the water in Hobart.")
        page.locator("#chat-form button[type='submit']").click()

        gallery = page.locator(".workspace-media-gallery")
        image = gallery.locator("img[alt='霍巴特海滨']")
        expect(image).to_be_visible(timeout=10000)
        expect(page.locator(".message-streaming")).to_have_count(0, timeout=10000)
        page.locator("#chat-input").fill("The light on the water stayed with me.")
        page.locator("#chat-form button[type='submit']").click()
        expect(page.locator(".message-streaming")).to_have_count(0, timeout=10000)
        page.wait_for_timeout(1200)
        expect(image).to_be_visible()
        expect(page.locator(".workspace-media-gallery")).to_have_count(1)
        assert turn_calls == 2
        assert photo_calls >= 2
        browser.close()


if __name__ == "__main__":
    main()
