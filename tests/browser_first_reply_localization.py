"""Verify the bounded first-reply UI and conversation-language bridge."""

from __future__ import annotations

import argparse
import json

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the first-reply localization browser contract.")
    parser.add_argument("--base-url", default="http://127.0.0.1:3010")
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        automatic = browser.new_context(locale="en-AU")
        automatic_page = automatic.new_page()
        automatic_requests = []

        def automatic_turn(route) -> None:
            automatic_requests.append(route.request.post_data_json)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"reply": "我会陪你慢慢回忆。", "trace": []}),
            )

        automatic_page.route("**/api/v1/memoir/agent/turn", automatic_turn)
        automatic_page.goto(f"{args.base_url}/memoir", wait_until="networkidle")
        automatic_page.get_by_role("button", name="Begin my story").click()
        automatic_page.get_by_role("textbox", name="Your message").fill("我叫慧博，现在生活在悉尼。")
        automatic_page.get_by_role("button", name="Send message").click()

        expect(automatic_page.locator("html")).to_have_attribute("lang", "zh-CN", timeout=15000)
        expect(automatic_page.get_by_text("我会陪你慢慢回忆。")).to_be_visible(timeout=15000)
        assert automatic_requests[-1].get("language") == "zh-CN"
        assert automatic_requests[-1].get("first_reply_localization") is True
        assert any(cookie["name"] == "copyme2_ui_locale_source" and cookie["value"] == "automatic" for cookie in automatic.cookies())
        automatic.close()

        fixed = browser.new_context(locale="en-AU")
        fixed.add_init_script(
            "document.cookie = 'copyme2_ui_locale=en-AU; Path=/; SameSite=Lax'; document.cookie = 'copyme2_ui_locale_source=fixed; Path=/; SameSite=Lax';"
        )
        fixed_page = fixed.new_page()
        fixed_requests = []

        def fixed_turn(route) -> None:
            fixed_requests.append(route.request.post_data_json)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"reply": "I will stay with you as you remember.", "trace": []}),
            )

        fixed_page.route("**/api/v1/memoir/agent/turn", fixed_turn)
        fixed_page.goto(f"{args.base_url}/memoir", wait_until="networkidle")
        fixed_page.get_by_role("button", name="Begin my story").click()
        fixed_page.get_by_role("textbox", name="Your message").fill("我叫慧博，现在生活在悉尼。")
        fixed_page.get_by_role("button", name="Send message").click()

        expect(fixed_page.locator("html")).to_have_attribute("lang", "en-AU", timeout=15000)
        expect(fixed_page.get_by_text("I will stay with you as you remember.")).to_be_visible(timeout=15000)
        assert fixed_requests[-1].get("language") == "zh-CN"
        assert fixed_requests[-1].get("first_reply_localization") is True
        fixed.close()
        browser.close()
        print("First-reply localization switched the automatic UI session and preserved fixed UI choices.")


if __name__ == "__main__":
    main()
