from __future__ import annotations

import argparse
import re
import time

from playwright.sync_api import sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify that starting a memoir opens the chat before background setup finishes.")
    parser.add_argument("--base-url", default="http://127.0.0.1:3010")
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=1)

        def delay_journey(route) -> None:
            time.sleep(1.5)
            route.continue_()

        page.route("**/api/v1/memoir/projects/*/journey", delay_journey)
        page.goto(args.base_url, wait_until="networkidle")
        page.get_by_role("button", name="Begin my story").click()
        page.wait_for_timeout(350)

        observed = {
            "url": page.url,
            "chat_main": page.get_by_role("main", name="Mira conversation").count(),
            "loading": page.locator("#app .loading").count(),
            "assistant_messages": page.locator(".assistant-message .message-text").count(),
        }
        page.wait_for_timeout(1800)

        browser.close()

        assert re.search(r"/memoir/interview/project_[^/]+$", observed["url"]), observed["url"]
        assert observed["chat_main"] == 1
        assert observed["loading"] == 0
        assert observed["assistant_messages"] >= 1


if __name__ == "__main__":
    main()
