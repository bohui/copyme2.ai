from __future__ import annotations

import argparse

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Memory Spark anonymous-auth smoke journey.")
    parser.add_argument("--base-url", default="http://127.0.0.1:3010")
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
        page.goto(args.base_url, wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        expect(page.get_by_text("Start with a conversation.")).to_be_visible()
        page.get_by_role("button", name="Begin my story").click()
        expect(page.get_by_role("main", name="Memory Spark conversation")).to_be_visible()
        expect(page.get_by_role("textbox", name="Your message")).to_be_visible()
        browser.close()


if __name__ == "__main__":
    main()
