"""Lock down workspace reveal after a previously collapsed workspace."""

import json

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    places = [
        ("Hobart", -42.8826, 147.3257),
        ("Melbourne", -37.8136, 144.9631),
    ]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1030, "height": 580}, device_scale_factor=1)
        turn_number = 0

        def agent_turn(route) -> None:
            nonlocal turn_number
            place, latitude, longitude = places[min(turn_number, len(places) - 1)]
            turn_number += 1
            body = {
                "reply": f"Let’s stay with what you remember about {place}.",
                "trace": [],
                "trace_mode": "codex",
                "place_journey": {
                    "schema_version": 1,
                    "status": "active",
                    "revision": turn_number,
                    "place": place,
                    "hierarchy": ["Earth", "Australia", place],
                    "granularity": "city",
                    "latitude": latitude,
                    "longitude": longitude,
                    "duration_ms": 1,
                },
                "place_journey_change": {"changed": True, "kind": "created", "revision": turn_number},
            }
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

        page.route("**/api/v1/memoir/agent/turn", agent_turn)
        page.goto("http://127.0.0.1:3010/memoir", wait_until="networkidle")
        page.get_by_role("button", name="Begin my story").click()

        textbox = page.get_by_role("textbox", name="Your message")
        textbox.fill("I remember Hobart.")
        page.get_by_role("button", name="Send message").click()
        expect(page.locator(".context-visible")).to_be_visible()
        page.set_viewport_size({"width": 823, "height": 580})
        layout_display = page.locator(".conversation-layout").evaluate("element => getComputedStyle(element).display")
        assert layout_display == "grid", f"workspace layout became {layout_display} at CSS width 823px"

        page.locator("[data-action='toggle-workspace']").click()
        expect(page.locator(".story-shell.workspace-collapsed")).to_be_visible()

        textbox = page.get_by_role("textbox", name="Your message")
        textbox.fill("Now I remember Melbourne.")
        page.get_by_role("button", name="Send message").click()
        expect(page.locator(".assistant-message")).to_have_count(3)

        shell = page.locator(".story-shell")
        shell_classes = shell.get_attribute("class") or ""
        assert "context-visible" in shell_classes, shell_classes
        assert "workspace-collapsed" not in shell_classes
        assert page.locator(".conversation-layout").evaluate("element => getComputedStyle(element).display") == "grid"
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert turn_number == 2

        page.set_viewport_size({"width": 760, "height": 580})
        assert page.locator(".conversation-layout").evaluate("element => getComputedStyle(element).flexDirection") == "column"

        browser.close()
        print("Workspace reveal passed: a newly triggered place reopens a previously collapsed workspace.")


if __name__ == "__main__":
    main()
