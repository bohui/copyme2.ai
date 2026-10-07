"""Exercise request locale negotiation through real server HTML and the browser.

Run against an isolated Next frontend with MEMOIR_BROWSER_URL. Only the API/auth
boundary is synthetic; the request config, locale matcher and UI are real.
"""

import os

import pytest
from playwright.sync_api import expect, sync_playwright


pytestmark = pytest.mark.skipif(
    not os.getenv("MEMOIR_BROWSER_URL"), reason="Requires isolated source frontend"
)


@pytest.mark.parametrize(
    "accept_language,expected_locale",
    [
        ("en_US,zh-CN;q=0.9", "zh-CN"),
        ("invalid_locale", "en-AU"),
        ("zh-CN;q=2,en-AU;q=0.8", "en-AU"),
        ("zh-CN;q=NaN,en-AU;q=0.8", "en-AU"),
        ("en-AU;q=0,zh-CN;q=0.8", "zh-CN"),
        ("fr-FR,zh-CN;q=0.8,en-AU;q=0.5", "zh-CN"),
        ("en-AU;q=0.4,zh-CN;q=0.9", "zh-CN"),
        ("*", "en-AU"),
    ],
)
def test_request_locale_has_safe_first_render_and_hydration(accept_language, expected_locale):
    base = os.environ["MEMOIR_BROWSER_URL"]
    with sync_playwright() as pw:
        options = {}
        if executable := os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE"):
            options["executable_path"] = executable
        browser = pw.chromium.launch(**options)
        context = browser.new_context(extra_http_headers={"Accept-Language": accept_language})
        # No provider or account calls are needed for locale negotiation.
        context.route("https://**/*", lambda route: route.abort())
        context.route("**/api/v1/memoir/**", lambda route: route.fulfill(
            content_type="application/json",
            body='{"auth_mode":"test"}' if route.request.url.endswith("/agent/config") else '{}',
        ))
        page = context.new_page()
        response = page.goto(base + "/memoir?locale-contract=1", wait_until="networkidle")
        assert response is not None and response.status == 200
        assert f'<html lang="{expected_locale}"' in response.text()
        expect(page.locator("html")).to_have_attribute("lang", expected_locale)
        heading = "用自己的话，讲述自己的人生" if expected_locale == "zh-CN" else "Start with a conversation."
        language_label = "语言" if expected_locale == "zh-CN" else "Language"
        expect(page.get_by_role("heading", name=heading)).to_be_visible()
        expect(page.get_by_role("combobox", name=language_label)).to_have_value(expected_locale)
        assert page.url == base + "/memoir?locale-contract=1"
        browser.close()
