from __future__ import annotations

import argparse
import json

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a place journey renders multiple searched photographs.")
    parser.add_argument("--base-url", default="http://127.0.0.1:3010")
    args = parser.parse_args()

    journey = {
        "schema_version": 1,
        "status": "active",
        "revision": 1,
        "place": "Chengde",
        "hierarchy": ["Earth", "China", "Hebei", "Chengde"],
        "granularity": "city",
        "latitude": 40.9515,
        "longitude": 117.9634,
        "duration_ms": 2800,
        "updated_at": "2026-09-27T00:00:00Z",
    }
    pictures = [{
        "asset_id": f"commons-cached-{index}",
        "kind": "image",
        "title": f"Chengde landscape {index}.jpg",
        "image_url": f"/static/timeline_avatar_child_female.png?photo={index}",
        "source_url": "https://commons.wikimedia.org/wiki/File:Chengde_landscape.jpg",
        "attribution": "Public archive",
        "license": "Public domain",
        "allowed_actions": {"embed": True},
    } for index in range(1, 11)]
    metadata_only_pictures = [{
        "asset_id": f"commons-metadata-{index}",
        "kind": "image",
        "title": f"Chengde archive {index}",
        "source_url": "https://commons.wikimedia.org/wiki/File:Chengde_landscape.jpg",
        "attribution": "Public archive",
        "license": "Public domain",
        "allowed_actions": {"embed": True},
    } for index in range(1, 11)]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
        photo_items = pictures
        page.route("**/api/v1/memoir/agent/turn", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "reply": "What detail stays with you about Chengde?",
                "trace": [],
                "trace_mode": "codex",
                "profile_updates": {"childhood_place": "Chengde"},
                "place_journey": journey,
                "place_journey_change": {"changed": True, "kind": "created", "revision": 1},
            }),
        ))
        page.route("**/place-photos?**", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"items": photo_items}),
        ))

        page.goto(args.base_url, wait_until="networkidle")
        page.get_by_role("button", name="Begin my story").click()
        page.get_by_role("textbox", name="Your message").fill("I remember Chengde.")
        page.get_by_role("button", name="Send message").click()

        gallery = page.locator(".workspace-media-gallery .place-pictures figure")
        expect(gallery).to_have_count(10, timeout=30000)
        titles = gallery.locator("figcaption a").all_text_contents()
        assert len(titles) == 10, titles
        assert all(title for title in titles), titles
        expect(gallery.locator("figcaption small")).to_have_count(10)
        expect(gallery.get_by_text("公共历史线索 · 不是个人证据")).to_have_count(0)

        project_id = page.url.rsplit("/", 1)[-1]

        def hide_project_place_history(route) -> None:
            if route.request.method != "GET":
                route.fallback()
                return
            response = route.fetch()
            body = response.json()
            body.setdefault("profile", {}).pop("memory_places", None)
            route.fulfill(response=response, json=body)

        page.route(f"**/api/v1/memoir/projects/{project_id}", hide_project_place_history)
        photo_items = metadata_only_pictures
        page.route("**/api/v1/memoir/agent/place-journey", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"place_journey": journey}),
        ))
        page.reload(wait_until="networkidle")
        expect(page.get_by_role("heading", name="Chengde", exact=True)).to_be_visible(timeout=30000)
        expect(page.locator(".workspace-media-gallery .place-pictures figure")).to_have_count(10, timeout=30000)
        browser.close()


if __name__ == "__main__":
    main()
