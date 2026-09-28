"""Keep the workspace closed until the conversation yields usable context."""

import argparse
import json

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3010")
    args = parser.parse_args()

    turn_calls = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=1)

        def agent_turn(route) -> None:
            nonlocal turn_calls
            turn_calls += 1
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({
                    "reply": "That sounds like a gentle place to begin. What do you remember about it?",
                    "trace": [],
                    "trace_mode": "codex",
                    "conversation_saved": True,
                    "place_journey": None,
                    "place_journey_change": None,
                }),
            )

        page.route("**/api/v1/memoir/agent/turn", agent_turn)
        page.goto(args.base_url, wait_until="networkidle")
        page.get_by_role("button", name="Begin my story").click()
        expect(page.get_by_role("main", name="Mira conversation")).to_be_visible()

        expect(page.locator(".story-shell.conversation-only")).to_be_visible()
        expect(page.locator("#workspace-detail")).to_have_count(0)
        expect(page.locator(".workspace-media-overview")).to_have_count(0)
        expect(page.locator(".place-journey-card")).to_have_count(0)

        page.get_by_role("textbox", name="Your message").fill("I remember an old coat and the smell of rain.")
        page.get_by_role("button", name="Send message").click()
        expect(page.locator(".assistant-message")).to_have_count(2)
        expect(page.locator(".story-shell.conversation-only")).to_be_visible()
        expect(page.locator("#workspace-detail")).to_have_count(0)
        expect(page.locator(".workspace-media-overview")).to_have_count(0)
        expect(page.locator(".place-journey-card")).to_have_count(0)
        assert turn_calls == 1

        browser.close()


if __name__ == "__main__":
    main()
