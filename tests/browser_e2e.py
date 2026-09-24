from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def answer(page, text: str) -> None:
    page.get_by_role("textbox", name="Your answer").fill(text)
    page.get_by_role("button", name="Send answer").click()


def accept_prompt(page, value: str) -> None:
    page.once("dialog", lambda dialog: dialog.accept(value))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the complete Memory Spark first-chapter browser journey.")
    parser.add_argument("--base-url", default="http://127.0.0.1:3010")
    args = parser.parse_args()

    page_errors: list[str] = []
    failed_requests: list[str] = []
    artifact_dir = Path(__file__).resolve().parents[1] / "output" / "playwright"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
        page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("requestfailed", lambda request: failed_requests.append(f"{request.method} {request.url}: {request.failure}"))

        page.goto(args.base_url, wait_until="networkidle")
        expect(page.get_by_role("heading", name="Your story begins with one gentle question.")).to_be_visible()
        expect(page.get_by_role("button", name="Begin my story")).to_be_visible()

        page.get_by_role("button", name="Begin my story").click()
        expect(page.get_by_text("What’s your name?")).to_be_visible()
        expect(page.get_by_role("button", name="Speak your answer")).to_be_visible()
        expect(page.get_by_role("button", name="Read this message aloud").first).to_be_visible()

        answer(page, "Margaret")
        expect(page.get_by_text("When were you born? An exact date or just a year is enough.")).to_be_visible()
        expect(page.get_by_text("Simulated Codex loop")).to_be_visible()
        page.locator("details.agent-loop").first.locator("summary").click()
        expect(page.get_by_text("Analyze").first).to_be_visible()
        expect(page.get_by_text("profile.update").first).to_be_visible()

        answer(page, "1958")
        expect(page.get_by_text("Where were you born? A town or country is enough for now.")).to_be_visible()

        answer(page, "A small town in Victoria")
        expect(page.get_by_text("What do you remember about getting to school?")).to_be_visible()
        expect(page.get_by_text("Public history cues · not personal evidence").first).to_be_visible()

        answer(page, "My older brother and I walked to school. We passed a little shop.")
        expect(page.get_by_text("Does anything in these public historical references bring back a detail? What felt familiar, and what was different in your own life?")).to_be_visible()
        expect(page.get_by_role("button", name="Save this memory")).not_to_be_visible()
        page.get_by_role("button", name="Familiar").first.click()

        answer(page, "The cold air and the sound of our shoes on the road come back to me.")
        expect(page.get_by_text("What could you see, hear, smell, or feel in that moment?")).to_be_visible()
        expect(page.get_by_role("button", name="Save this memory")).not_to_be_visible()

        answer(page, "My brother was beside me, and the shopkeeper always waved to us.")
        expect(page.get_by_text("I have enough detail to shape the first chapter. Save this memory when it feels right.")).to_be_visible()
        expect(page.get_by_role("button", name="Save this memory")).to_be_visible()

        page.get_by_role("button", name="Save this memory").click()
        expect(page.get_by_text("This memory has enough shape to become the first chapter. It is free, and I’ll open the workspace after you finish it.")).to_be_visible()
        page.get_by_role("button", name="Finish my free first chapter").click()
        expect(page.get_by_text("Chapter one is finished, and it’s yours.")).to_be_visible()
        expect(page.get_by_role("button", name="Chapters")).to_be_visible()
        expect(page.get_by_role("heading", name="Where the story begins")).to_be_visible()

        page.get_by_role("button", name="Family tree").click()
        expect(page.get_by_role("heading", name="Family tree")).to_be_visible()
        accept_prompt(page, "Older brother")
        page.get_by_role("button", name="Add person").click()
        expect(page.get_by_text("Older brother").first).to_be_visible()

        page.get_by_role("button", name="Timeline").click()
        expect(page.get_by_role("heading", name="Timeline")).to_be_visible()
        accept_prompt(page, "Walked to school")
        page.get_by_role("button", name="Add moment").click()
        expect(page.get_by_text("Walked to school").first).to_be_visible()

        page.screenshot(path=str(artifact_dir / "first-chapter-workspace.png"), full_page=True)
        page.reload(wait_until="networkidle")
        expect(page.get_by_role("heading", name="Chapters")).to_be_visible()
        expect(page.get_by_role("heading", name="Where the story begins")).to_be_visible()
        page.get_by_role("button", name="Family tree").click()
        expect(page.get_by_text("Older brother").first).to_be_visible()
        page.get_by_role("button", name="Timeline").click()
        expect(page.get_by_text("Walked to school").first).to_be_visible()

        assert not page_errors, "Browser page errors: " + "; ".join(page_errors)
        assert not failed_requests, "Failed browser requests: " + "; ".join(failed_requests)
        browser.close()


if __name__ == "__main__":
    main()
