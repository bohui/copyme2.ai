from __future__ import annotations

import argparse
import json

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify unpaid storytellers do not receive Family workspace surfaces.")
    parser.add_argument("--base-url", default="http://127.0.0.1:3010")
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
        renderer_requests = []
        page.on(
            "request",
            lambda request: renderer_requests.append(request.url)
            if any(name in request.url for name in ("family-chart", "vis-timeline", "d3@7.9.0"))
            else None,
        )

        page.route(
            "**/api/v1/memoir/story/state",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "payment_status": "unpaid",
                        "payment_plan": None,
                        "payment_features": [],
                        "family_features_enabled": False,
                    }
                ),
            ),
        )
        page.route(
            "**/api/v1/memoir/agent/turn",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "reply": "I’m here with you.",
                        "family_features_enabled": False,
                        "family_context": {
                            "people": [{"id": "p1", "name": "Should stay hidden"}],
                            "relationships": [],
                            "timeline": [],
                            "life_periods": [],
                        },
                        "trace": [],
                        "trace_mode": "codex",
                    }
                ),
            ),
        )

        page.goto(args.base_url, wait_until="networkidle")
        page.get_by_role("button", name="Begin my story").click()
        page.get_by_role("textbox", name="Your message").fill("I remember my family.")
        page.get_by_role("button", name="Send message").click()

        expect(page.get_by_role("complementary", name="Family tree workspace")).to_have_count(0)
        expect(page.get_by_role("complementary", name="Timeline workspace")).to_have_count(0)
        expect(page.get_by_text("Should stay hidden")).to_have_count(0)
        assert renderer_requests == []
        browser.close()


if __name__ == "__main__":
    main()
