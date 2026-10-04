from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright
from fixtures.browser_memory_events import SCHOOL_QUOTE, school_events


FAMILY_CHART_STUB = """
window.f3 = {
  createChart: function (selector, data) {
    var target = typeof selector === "string" ? document.querySelector(selector) : selector;
    if (target) {
      target.setAttribute("data-library-mounted", "family-chart");
      target.innerHTML = '<div class="family-chart-library-content">Family chart renderer</div>';
    }
    return {
      setSingleParentEmptyCard: function () { return this; },
      setShowSiblingsOfMain: function () { return this; },
      updateMainId: function () { return this; },
      setCardHtml: function () { return this; },
      setCardDisplay: function () { return this; },
      setCardInnerHtmlCreator: function () { return this; },
      setOnCardClick: function () { return this; },
      setCardXSpacing: function () { return this; },
      setCardYSpacing: function () { return this; },
      updateTree: function () { return this; },
    };
  },
};
"""

VIS_TIMELINE_STUB = """
window.vis = {
  DataSet: function (items) { this.items = items; },
  Timeline: function (container, items, options) {
    container.setAttribute("data-library-mounted", "vis-timeline");
    container.innerHTML = '<div class="vis-timeline-library-content">Timeline renderer</div>';
  },
};
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify paid Family renderer adapters and accessible fallbacks.")
    parser.add_argument("--base-url", default="http://127.0.0.1:3010")
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
        codex_calls = 0
        persisted = None

        page.route(
            "**/api/v1/memoir/story/state",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "payment_status": "paid",
                        "payment_plan": "family_memoir_v1",
                        "payment_features": ["family_tree", "timeline", "expanded_details"],
                        "family_features_enabled": True,
                    }
                ),
            ),
        )

        def codex_turn(route) -> None:
            nonlocal codex_calls, persisted
            codex_calls += 1
            project_id = route.request.post_data_json['project_id']
            response = {"reply": "Tell me more about that family memory.", "trace": [], "trace_mode": "codex"}
            # The fixed opening is product copy; the first real storyteller
            # answer is the first Codex turn.
            if codex_calls >= 1:
                response.update(
                    {
                        "family_features_enabled": True,
                        "family_context": {
                            "schema_version": 1,
                            "project_id": project_id,
                            "revision": 1,
                            "updated_at": "2026-09-26T00:00:00Z",
                            "people": [
                                {"id": "p-mum", "name": "Mei", "family_title": "mother"},
                                {"id": "p-me", "name": "Avery"},
                            ],
                            "relationships": [
                                {"from_person_id": "p-mum", "to_person_id": "p-me", "relationship_type": "parent"}
                            ],
                            "timeline": [
                                {
                                    "id": "e-school",
                                    "title": "Started school",
                                    "date_expression": "around 1964",
                                    "precision": "approximate",
                                    "place": "Hobart",
                                    "person_ids": ["p-me"],
                                }
                            ],
                            "life_periods": [],
                        },
                        "family_context_update": {
                            "schema_version": 1,
                            "project_id": project_id,
                            "changed": True,
                            "persisted": True,
                            "revision": 1,
                            "skills": ["family_tree", "author_timeline"],
                            "added": {"people": 2, "relationships": 1, "timeline": 1, "life_periods": 0},
                            "updated": {"people": 0, "relationships": 0, "timeline": 0, "life_periods": 0},
                        },
                    }
                )
                persisted = response['family_context']
            route.fulfill(status=200, content_type="application/json", body=json.dumps(response))

        page.route("**/api/v1/memoir/agent/turn", codex_turn)
        page.route('**/api/v1/memoir/agent/family-context*', lambda route:
                   route.fulfill(json={'family_features_enabled': True, 'family_context': persisted}))
        page.route("**/api/v1/memoir/story/events?**",
                   lambda route: school_events(route, present=codex_calls > 0))
        fixture_dir = Path(os.environ["MEMOIR_RENDERER_FIXTURES"]) if os.environ.get("MEMOIR_RENDERER_FIXTURES") else None
        expect_fallback = os.environ.get("MEMOIR_RENDERER_EXPECT_FALLBACK") == "1"

        def bundle_response(filename: str, fallback: str):
            if expect_fallback:
                return lambda route: route.abort()
            body = (fixture_dir / filename).read_text(encoding="utf-8") if fixture_dir else fallback
            return lambda route: route.fulfill(content_type="text/javascript", body=body)

        page.route("**/unpkg.com/d3@7.9.0/dist/d3.min.js", bundle_response("d3.min.js", "window.d3 = {};"))
        page.route("**/unpkg.com/family-chart@0.9.0/dist/family-chart.min.js", bundle_response("family-chart.min.js", FAMILY_CHART_STUB))
        page.route("**/unpkg.com/vis-timeline@7.7.3/standalone/umd/vis-timeline-graph2d.min.js", bundle_response("vis-timeline.min.js", VIS_TIMELINE_STUB))
        page.route("**/unpkg.com/**/*.css", lambda route: route.fulfill(content_type="text/css", body=""))

        page.goto(args.base_url, wait_until="networkidle")
        page.get_by_role("button", name="Begin my story").click()
        page.get_by_role("textbox", name="Your message").fill("My mother Mei helped me start school around 1964 in Hobart.")
        page.get_by_role("button", name="Send message").click()
        page.get_by_role('button', name='Family tree', exact=True).click()

        family = page.get_by_role("complementary", name="Family tree workspace")
        if expect_fallback:
            expect(family.locator("[data-renderer-status='fallback']")).to_be_visible()
        else:
            expect(family.locator("[data-library-mounted='family-chart']")).to_be_visible()
        expect(family.locator(".family-person-card strong", has_text="Mei")).to_be_visible()
        navigator = page.locator('.life-stage-navigator')
        expect(navigator).to_be_visible()
        expect(navigator.locator('[data-life-stage-tab]')).to_have_count(7)
        expect(navigator.locator("[data-life-stage-tab='childhood']")).to_have_attribute('aria-pressed', 'true')
        navigator.locator("[data-life-stage-tab='adolescence']").click()
        expect(navigator.locator("[data-life-stage-tab='adolescence']")).to_have_attribute('aria-pressed', 'true')
        expect(navigator.locator("[data-life-stage-tab='childhood']")).to_have_attribute('aria-pressed', 'false')
        navigator.locator("[data-life-stage-tab='adolescence']").press('ArrowRight')
        expect(navigator.locator("[data-life-stage-tab='young_adulthood']")).to_have_attribute('aria-pressed', 'true')
        page.get_by_role("button", name="Timeline").click()
        timeline = page.get_by_role("complementary", name="Timeline workspace")
        if expect_fallback:
            expect(timeline.locator("[data-renderer-status='fallback']")).to_be_visible()
        else:
            expect(timeline.locator("[data-library-mounted='vis-timeline']")).to_be_visible()
        expect(timeline.locator(".timeline-list strong", has_text="Started school")).to_be_visible()
        timeline.get_by_text("Original evidence", exact=True).click()
        expect(timeline.get_by_text(SCHOOL_QUOTE, exact=True)).to_be_visible()
        page.set_viewport_size({"width": 390, "height": 900})
        expect(timeline).to_be_visible()
        expect(navigator).to_be_visible()
        expect(navigator.locator("[data-life-stage-tab='young_adulthood']")).to_have_attribute('aria-pressed', 'true')
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        browser.close()


if __name__ == "__main__":
    main()
