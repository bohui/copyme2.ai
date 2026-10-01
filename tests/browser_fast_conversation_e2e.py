"""Verify that a saved conversational reply is usable before workspace work finishes.

Run against the local source server:
MEMOIR_BROWSER_URL=http://localhost:3011 python3 tests/browser_fast_conversation_e2e.py
"""
import argparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3010")
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.add_init_script(
            """
            const originalFetch = window.fetch.bind(window);
            window.turnCalls = 0;
            window.finishFirstWorkspace = null;
            window.finishPhotos = null;
            window.fetch = async (url, options) => {
              if (String(url).includes('/place-photos?')) {
                window.photoCalls = (window.photoCalls || 0) + 1;
                return new Promise(resolve => {
                  window.finishPhotos = () => resolve(new Response(JSON.stringify({items: [], status: window.photoUnavailable ? 'UNAVAILABLE' : 'NO_MATCH'}), {
                    headers: {'Content-Type': 'application/json'},
                  }));
                });
              }
              if (!String(url).endsWith('/agent/turn')) return originalFetch(url, options);
              if (options.headers.Accept !== 'application/x-ndjson') throw Error('Missing streaming Accept');
              const call = ++window.turnCalls;
              const encoder = new TextEncoder();
              return new Response(new ReadableStream({start(controller) {
                const emit = event => controller.enqueue(encoder.encode(JSON.stringify(event) + '\\n'));
                const reply = call === 1 ? 'I hear you. What stands out next?' : 'Tell me more about that moment.';
                emit({type: 'started'});
                emit({type: 'text_delta', text: reply});
                emit({type: 'reply_complete', data: {reply, thread_id: `thread-${call}`, trace: []}});
                emit({type: 'conversation_saved', data: {reply, conversation_saved: true, thread_id: `thread-${call}`, trace: []}});
                if (call === 1) {
                  window.finishFirstWorkspace = () => {
                    emit({type: 'workspace_update', data: {
                      place_journey: {schema_version: 1, status: 'active', revision: 1,
                        place: 'Sydney', hierarchy: ['Earth', 'Australia', 'Sydney'],
                        granularity: 'city', latitude: -33.8688, longitude: 151.2093,
                        duration_ms: 2800},
                      place_journey_change: {changed: true, revision: 1},
                    }});
                    emit({type: 'result', data: {reply, thread_id: `thread-${call}`, trace: []}});
                    controller.close();
                  };
                } else {
                  emit({type: 'result', data: {reply, thread_id: `thread-${call}`, trace: []}});
                  controller.close();
                }
              }}), {headers: {'Content-Type': 'application/x-ndjson'}});
            };
            """
        )
        page.goto(args.base_url, wait_until="networkidle")
        page.get_by_role("button", name="Begin my story").click()
        expect(page.locator(".assistant-message .message-text").first).to_contain_text(
            "First, what would you like me to call you?"
        )

        page.get_by_role("textbox", name="Your message").fill("I remember Sydney.")
        page.get_by_role("button", name="Send message").click()
        expect(page.locator(".assistant-message .message-text").nth(1)).to_have_text(
            "I hear you. What stands out next?"
        )
        expect(page.locator(".thinking")).to_have_count(0)
        expect(page.get_by_role("button", name="Send message")).to_be_enabled()

        page.evaluate("window.finishFirstWorkspace()")
        page.wait_for_function("typeof window.finishPhotos === 'function'")
        expect(page.get_by_role("heading", name="Sydney", exact=True)).to_be_visible()
        expect(page.locator(".workspace-media-gallery [role='status']")).to_have_text("Finding reference photos…")

        page.get_by_role("textbox", name="Your message").fill("The harbour was bright.")
        page.get_by_role("button", name="Send message").click()
        expect(page.locator(".assistant-message .message-text").nth(2)).to_have_text(
            "Tell me more about that moment."
        )
        assert page.evaluate("window.turnCalls") == 2
        expect(page.locator(".thinking")).to_have_count(0)
        expect(page.get_by_role("button", name="Send message")).to_be_enabled()

        page.evaluate("window.photoUnavailable = true; window.finishPhotos()")
        expect(page.locator(".workspace-media-gallery [role='status']")).to_have_text(
            "Photo search could not finish. You can try again."
        )
        page.get_by_role("button", name="Try photo search again").click()
        page.wait_for_function("window.photoCalls === 2")
        page.evaluate("window.photoUnavailable = false; window.finishPhotos()")
        expect(page.get_by_role("heading", name="Sydney", exact=True)).to_be_visible()
        expect(page.locator(".workspace-media-gallery [role='status']")).to_have_text(
            "No matching reference photos were found for this place and period."
        )
        expect(page.locator(".message-streaming")).to_have_count(0)
        print("PASS: reply and next turn complete before delayed workspace enrichment")
        browser.close()


if __name__ == "__main__":
    main()
