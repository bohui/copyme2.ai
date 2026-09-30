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
    parser.add_argument("--expect-thinking-steps", action="store_true")
    args = parser.parse_args()

    page_errors: list[str] = []
    failed_requests: list[str] = []
    artifact_dir = Path(__file__).resolve().parents[1] / "output" / "playwright"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
        page.add_init_script(
            """
            class FakeStream {
                getTracks() { return []; }
            }
            class FakeRecorder {
                static isTypeSupported() { return true; }
                constructor() { this.state = "inactive"; this.mimeType = "audio/webm"; this.listeners = {}; }
                addEventListener(name, callback) { this.listeners[name] = callback; }
                start() { this.state = "recording"; }
                stop() { this.state = "inactive"; this.listeners.stop?.(); }
            }
            Object.defineProperty(navigator, "mediaDevices", { value: navigator.mediaDevices || {}, configurable: true });
            navigator.mediaDevices.getUserMedia = async () => new FakeStream();
            window.MediaRecorder = FakeRecorder;
            """
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("requestfailed", lambda request: failed_requests.append(f"{request.method} {request.url}: {request.failure}"))

        codex_calls = 0
        journey_reads = 0

        def codex_turn(route) -> None:
            nonlocal codex_calls
            codex_calls += 1
            request = route.request.post_data_json or {}
            storyteller_text = request.get("text", "")
            response = {
                "reply": "Tell me whatever part of that afternoon is still with you.",
                "trace": [{"kind": "tool", "label": "memory.search", "detail": "Keeping the conversation open."}],
                "trace_mode": "codex",
            }
            if "Hobart" in storyteller_text:
                response["profile_updates"] = {
                    "name": "Avery",
                    "childhood_place": "Hobart",
                    "story_focus": {
                        "who": "my sister",
                        "where": "the waterfront",
                        "when": "a summer afternoon",
                        "what": "the feeling of being together",
                    },
                }
                response["place_journey"] = {
                    "schema_version": 1,
                    "status": "active",
                    "revision": 1,
                    "place": "Hobart",
                    "hierarchy": ["Earth", "Australia", "Tasmania", "Hobart"],
                    "granularity": "city",
                    "latitude": -42.8826,
                    "longitude": 147.3257,
                    "duration_ms": 2800,
                    "updated_at": "2026-09-26T00:00:00Z",
                }
                response["place_journey_change"] = {"changed": True, "kind": "created", "revision": 1}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(response))

        def place_journey_read(route) -> None:
            nonlocal journey_reads
            journey_reads += 1
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "place_journey": {
                    "schema_version": 1,
                    "status": "active",
                    "revision": 1,
                    "place": "Hobart",
                    "hierarchy": ["Earth", "Australia", "Tasmania", "Hobart"],
                    "granularity": "city",
                    "latitude": -42.8826,
                    "longitude": 147.3257,
                    "duration_ms": 2800,
                    "updated_at": "2026-09-26T00:00:00Z",
                },
            }))

        page.route("**/api/v1/memoir/agent/turn", codex_turn)
        page.route("**/api/v1/memoir/agent/place-journey", place_journey_read)

        page.goto(args.base_url, wait_until="networkidle")
        expect(page.get_by_role("heading", name="Start with a conversation.")).to_be_visible()
        page.get_by_role("button", name="Begin my story").click()
        expect(page.get_by_role("main", name="Mira conversation")).to_be_visible()
        expect(page.get_by_role("textbox", name="Your message")).to_be_visible()
        expect(page.locator(".assistant-message .message-label").first).to_have_text("Mira")
        expect(page.locator(".assistant-message .assistant-avatar img").first).to_have_attribute("src", "/static/mira_avatar_en-AU.png")
        expect(page.locator(".assistant-message .assistant-avatar img").first).to_have_attribute("alt", "Mira")
        expect(page.locator(".assistant-message .message-text").first).to_contain_text("Hi, I’m Mira. It’s nice to meet you.")
        expect(page.locator(".assistant-message .message-text").first).to_contain_text("First, what would you like me to call you?")
        assert codex_calls == 0, f"The fixed opening must not start an agent turn; got {codex_calls} call(s)"
        expect(page.locator(".thinking")).to_have_count(0)
        if args.expect_thinking_steps:
            expect(page.locator(".agent-loop")).to_have_count(1)
            expect(page.get_by_text("Thinking steps")).to_be_visible()
        else:
            expect(page.locator(".agent-loop")).to_have_count(0)
            expect(page.get_by_text("Simulated Codex loop")).to_have_count(0)
        expect(page.get_by_text("Round 1 of 5")).to_have_count(0)
        expect(page.locator(".context-visible")).to_have_count(0)
        expect(page.get_by_role("complementary", name="Places workspace")).to_have_count(0)
        expect(page.locator(".place-journey-card")).to_have_count(0)
        page.reload(wait_until="networkidle")
        expect(page.get_by_role("main", name="Mira conversation")).to_be_visible()
        expect(page.get_by_role("button", name="Show all history", exact=True)).to_be_visible()
        expect(page.locator("#chat-history")).to_have_attribute("hidden", "")
        page.get_by_role("button", name="Show all history", exact=True).click()
        expect(page.locator("#chat-history")).not_to_have_attribute("hidden", "")
        expect(page.locator(".assistant-message .message-text").first).to_contain_text("First, what would you like me to call you?")
        expect(page.get_by_role("complementary", name="Places workspace")).to_have_count(0)
        expect(page.locator(".place-journey-card")).to_have_count(0)
        send(page, "I remember a summer afternoon near the water in Hobart.")
        expect(page.locator(".assistant-message")).to_have_count(2)
        expect(page.locator(".profile-trigger-name")).to_have_text("Avery")
        expect(page.locator(".context-visible")).to_be_visible()
        expect(page.get_by_role("complementary", name="Places workspace")).to_be_visible()
        expect(page.locator(".workspace-detail .workspace-intro h2")).to_have_text("Places")
        expect(page.locator(".place-journey-workspace h2")).to_have_text("Hobart")
        assert page.locator(".chat-main").evaluate("element => getComputedStyle(element).position") == "static"
        expect(page.locator(".story-shell.voice-floating")).to_have_count(0)
        expect(page.locator(".cesium-place-journey")).to_have_count(1)
        expect(page.locator(".place-journey-scene.is-cesium-live")).to_have_count(1, timeout=30000)
        expect(page.locator(".cesium-viewer")).to_have_count(1)
        page.get_by_role("button", name="Start voice conversation").click()
        expect(page.locator(".story-shell.voice-floating")).to_have_count(0)
        expect(page.locator(".voice-orb")).to_be_visible()
        assert page.locator(".chat-main").evaluate("element => getComputedStyle(element).position") == "static"
        expect(page.locator(".chat-main")).to_have_attribute("class", "chat-main")
        page.get_by_role("button", name="End voice conversation").click()
        page.wait_for_timeout(3500)
        page.screenshot(path=str(artifact_dir / "codex-chat-start.png"), full_page=True)

        page.reload(wait_until="networkidle")
        expect(page.get_by_role("main", name="Mira conversation")).to_be_visible()
        expect(page.get_by_role("textbox", name="Your message")).to_be_visible()
        expect(page.locator(".place-journey-workspace h2")).to_have_text("Hobart")
        assert journey_reads >= 1, f"Expected startup journey hydration, got {journey_reads} read(s)"

        assert not page_errors, "Browser page errors: " + "; ".join(page_errors)
        assert not failed_requests, "Failed browser requests: " + "; ".join(failed_requests)
        browser.close()


if __name__ == "__main__":
    main()
