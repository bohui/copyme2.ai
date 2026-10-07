"""Server-render contract for locale negotiation, without a browser dependency."""

import os

import httpx
import pytest


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
        ("en-US;q=1,zh-CN;q=0.1", "en-AU"),
        ("zh-TW;q=1,en-AU;q=0.1", "zh-CN"),
        ("zh-CN;q=0.1,en-GB;q=0.9", "en-AU"),
        ("fr-FR;q=1,zh-SG;q=0.8,en-AU;q=0.1", "zh-CN"),
        ("en-US,zh-CN", "en-AU"),
        ("en-US;q=.9,zh-CN;q=0.1", "zh-CN"),
    ],
)
def test_server_locale_negotiation(accept_language, expected_locale):
    response = httpx.get(
        os.environ["MEMOIR_BROWSER_URL"] + "/memoir?locale-contract=1",
        headers={"Accept-Language": accept_language}, timeout=30, trust_env=False,
    )
    assert response.status_code == 200
    assert f'<html lang="{expected_locale}"' in response.text


@pytest.mark.parametrize("cookie_locale,accept_language,expected_locale", [
    ("zh-CN", "invalid_locale", "zh-CN"),
    ("invalid_locale", "invalid_locale", "en-AU"),
    ("en-AU", "zh-TW;q=1,en-AU;q=0.1", "en-AU"),
    ("zh-CN", "en-US;q=1,zh-CN;q=0.1", "zh-CN"),
])
def test_cookie_allowlist_precedes_browser_negotiation(cookie_locale, accept_language, expected_locale):
    response = httpx.get(
        os.environ["MEMOIR_BROWSER_URL"] + "/memoir",
        headers={"Accept-Language": accept_language},
        cookies={"copyme2_ui_locale": cookie_locale}, timeout=30, trust_env=False,
    )
    assert response.status_code == 200
    assert f'<html lang="{expected_locale}"' in response.text
