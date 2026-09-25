from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def send(page, text: str) -> None:
    page.get_by_role("textbox", name="Your message").fill(text)
    page.get_by_role("button", name="Send message").click()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the anonymous-to-account Memoir browser journey.")
    parser.add_argument("--base-url", default="http://127.0.0.1:3010")
    args = parser.parse_args()

    page_errors: list[str] = []
    failed_requests: list[str] = []
    artifact_dir = Path(__file__).resolve().parents[1] / "output" / "playwright"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("requestfailed", lambda request: failed_requests.append(f"{request.method} {request.url}: {request.failure}"))

        codex_calls = 0

        def codex_turn(route) -> None:
            nonlocal codex_calls
            codex_calls += 1
            response = {
                "reply": "Tell me whatever part of that afternoon is still with you.",
                "trace": [{"kind": "tool", "label": "memory.search", "detail": "Keeping the conversation open."}],
                "trace_mode": "codex",
            }
            if codex_calls > 1:
                response["place_journey"] = {
                    "place": "Hobart",
                    "hierarchy": ["Australia", "Tasmania", "Hobart"],
                    "granularity": "town",
                }
            route.fulfill(status=200, content_type="application/json", body=json.dumps(response))

        page.route("**/api/v1/memoir/agent/turn", codex_turn)

        page.goto(args.base_url, wait_until="networkidle")
        expect(page.get_by_role("heading", name="Start with a conversation.")).to_be_visible()
        page.get_by_role("button", name="Begin my story").click()
        expect(page.get_by_role("main", name="Memory Spark conversation")).to_be_visible()
        expect(page.get_by_role("textbox", name="Your message")).to_be_visible()
        expect(page.get_by_text("Round 1 of 5")).to_have_count(0)
        expect(page.locator(".context-visible")).to_have_count(0)
        send(page, "I remember a summer afternoon near the water.")
        expect(page.locator(".assistant-message")).to_have_count(2)
        expect(page.locator(".context-visible")).to_be_visible()
        expect(page.get_by_role("complementary", name="Places workspace")).to_be_visible()
        page.screenshot(path=str(artifact_dir / "codex-chat-start.png"), full_page=True)

        page.reload(wait_until="networkidle")
        expect(page.get_by_role("main", name="Memory Spark conversation")).to_be_visible()
        expect(page.get_by_role("textbox", name="Your message")).to_be_visible()

        assert not page_errors, "Browser page errors: " + "; ".join(page_errors)
        assert not failed_requests, "Failed browser requests: " + "; ".join(failed_requests)
        browser.close()


if __name__ == "__main__":
    main()
