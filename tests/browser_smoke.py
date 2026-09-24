from __future__ import annotations

import argparse

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Memory Spark browser smoke journey.")
    parser.add_argument("--base-url", default="http://127.0.0.1:3010")
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
        page.goto(args.base_url, wait_until="networkidle")
        assert page.get_by_text("Your story begins with one gentle question.").is_visible()
        page.get_by_role("button", name="Begin my story").click()
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500)
        assert page.locator("[data-workspace-tab]").count() == 0
        expect(page.get_by_text("What’s your name?")).to_be_visible()
        expect(page.get_by_role("button", name="Speak your answer")).to_be_visible()
        expect(page.get_by_role("button", name="Read this message aloud").first).to_be_visible()
        page.get_by_role("textbox", name="Your answer").fill("Margaret")
        page.get_by_role("button", name="Send answer").click()
        expect(page.get_by_text("When were you born? An exact date or just a year is enough.")).to_be_visible(timeout=5000)
        expect(page.get_by_text("Simulated Codex loop")).to_be_visible(timeout=5000)
        page.locator("details.agent-loop").first.locator("summary").click()
        expect(page.get_by_text("Analyze").first).to_be_visible(timeout=5000)
        expect(page.get_by_text("profile.update").first).to_be_visible(timeout=5000)
        page.get_by_role("textbox", name="Your answer").fill("1958")
        page.get_by_role("button", name="Send answer").click()
        expect(page.get_by_text("Where were you born? A town or country is enough for now.")).to_be_visible(timeout=5000)
        page.get_by_role("textbox", name="Your answer").fill("A small town in Victoria")
        page.get_by_role("button", name="Send answer").click()
        expect(page.get_by_text("What do you remember about getting to school?")).to_be_visible(timeout=5000)
        page.get_by_role("textbox", name="Your answer").fill("My older brother and I walked to school. We passed a little shop.")
        page.get_by_role("button", name="Send answer").click()
        expect(page.get_by_text("Does anything in these public historical references bring back a detail? What felt familiar, and what was different in your own life?")).to_be_visible(timeout=5000)
        expect(page.get_by_role("button", name="Save this memory")).not_to_be_visible()
        page.get_by_role("textbox", name="Your answer").fill("The cold air and the sound of our shoes on the road come back to me.")
        page.get_by_role("button", name="Send answer").click()
        expect(page.get_by_text("What could you see, hear, smell, or feel in that moment?")).to_be_visible(timeout=5000)
        expect(page.get_by_role("button", name="Save this memory")).not_to_be_visible()
        page.get_by_role("textbox", name="Your answer").fill("My brother was beside me, and the shopkeeper always waved to us.")
        page.get_by_role("button", name="Send answer").click()
        expect(page.get_by_role("button", name="Save this memory")).to_be_visible(timeout=5000)
        page.get_by_role("button", name="Save this memory").click()
        expect(page.get_by_role("button", name="Finish my free first chapter")).to_be_visible(timeout=5000)
        page.get_by_role("button", name="Finish my free first chapter").click()
        expect(page.get_by_text("Chapter one is finished, and it’s yours.")).to_be_visible(timeout=5000)
        expect(page.get_by_role("button", name="Chapters")).to_be_visible(timeout=5000)
        page.get_by_role("button", name="Family tree").click()
        expect(page.get_by_role("heading", name="Family tree")).to_be_visible(timeout=5000)
        page.get_by_role("button", name="Timeline").click()
        expect(page.get_by_role("heading", name="Timeline")).to_be_visible(timeout=5000)
        page.reload(wait_until="networkidle")
        expect(page.get_by_role("button", name="Chapters")).to_be_visible(timeout=5000)
        page.screenshot(path="/tmp/memory-spark-mobile.png", full_page=True)
        browser.close()


if __name__ == "__main__":
    main()
