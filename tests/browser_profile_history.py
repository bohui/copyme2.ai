"""Verify legacy profile markers are removed from restored assistant history."""
import argparse
import json

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3010")
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(args.base_url, wait_until="networkidle")
        page.locator("[data-action='open-memoir']").click()
        expect(page.get_by_role("main", name="Mira conversation")).to_be_visible()

        project_id = page.evaluate("localStorage.getItem('memory-spark-project')")
        history_key = f"memory-spark-chat-history:{project_id}"
        page.evaluate(
            "({key, message}) => sessionStorage.setItem(key, JSON.stringify([message]))",
            {
                "key": history_key,
                "message": {
                    "id": "assistant-message-999",
                    "role": "assistant",
                    "text": '慧博，你好。<!-- profile: {"who":"慧博"} -->',
                },
            },
        )
        page.reload(wait_until="networkidle")
        expect(page.get_by_role("main", name="Mira conversation")).to_be_visible()
        show_history = page.get_by_role("button", name="Show all history", exact=True)
        if show_history.count():
            show_history.click()

        assert "profile:" not in page.locator("body").inner_text()
        assert "慧博，你好。" in page.locator(".assistant-message .message-text").last.inner_text()
        stored = page.evaluate("key => sessionStorage.getItem(key)", history_key)
        assert "profile:" not in (stored or "")
        assert json.loads(stored)[0]["text"] == "慧博，你好。"
        browser.close()


if __name__ == "__main__":
    main()
