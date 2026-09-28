from __future__ import annotations

import argparse
import json
import re

from playwright.sync_api import expect, sync_playwright


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Memoir localization browser contract.")
    parser.add_argument("--base-url", default="http://127.0.0.1:3010")
    args = parser.parse_args()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(locale="en-AU")

        agent_requests = []

        def codex_turn(route) -> None:
            payload = route.request.post_data_json
            agent_requests.append(payload)
            reply = "Tell me whatever part of that afternoon is still with you."
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "reply": reply,
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
                "place_journey_change": {"changed": True, "kind": "created", "revision": 1},
            }))

        page.route("**/api/v1/memoir/agent/turn", codex_turn)
        page.goto(f"{args.base_url}/memoir", wait_until="networkidle")

        expect(page.get_by_role("heading", name="Start with a conversation.")).to_be_visible()
        language = page.get_by_role("combobox", name="Language")
        expect(language).to_have_value("en-AU")

        language.select_option("zh-CN")
        page.wait_for_load_state("networkidle")

        expect(page).to_have_url(re.compile(r"/memoir/?$"))
        expect(page.get_by_role("heading", name="用自己的话，讲述自己的人生")).to_be_visible()
        expect(page.get_by_role("button", name=re.compile("开始讲我的故事"))).to_be_visible()
        expect(page.get_by_role("button", name="帮助我爱的人")).to_be_visible()
        expect(page.get_by_role("heading", name="聊一聊，或许就能想起一些事")).to_be_visible()
        expect(page.get_by_role("combobox", name="语言")).to_have_value("zh-CN")

        page.reload(wait_until="networkidle")
        expect(page.get_by_role("heading", name="用自己的话，讲述自己的人生")).to_be_visible()
        expect(page.get_by_role("combobox", name="语言")).to_have_value("zh-CN")
        page.wait_for_function(
            "() => typeof globalThis.__copyme2Intl?.messages?.Memoir?.conversation?.opening === 'string'"
        )

        project_requests = []
        page.on("request", lambda request: project_requests.append(request) if request.method == "POST" and request.url.endswith("/projects") else None)
        page.locator("[data-action='start-story'][data-mode='self']").click()

        expect(page.get_by_role("main", name="Mira 的对话")).to_be_visible()
        expect(page.get_by_role("heading", name="让我们一起回忆。")).to_be_visible()
        expect(page.get_by_role("textbox", name="您的消息")).to_be_visible()
        expect(page.get_by_text("可以进行语音对话")).to_be_visible()
        expect(page.get_by_text("你好，我是 Mira。很高兴认识你。")).to_be_visible()
        page.get_by_role("button", name="打开个人资料菜单").click()
        expect(page.get_by_text("个人资料").first).to_be_visible()
        expect(page.get_by_text("匿名会话")).to_be_visible()
        expect(page.locator(".profile-dropdown select")).to_have_count(0)
        expect(page.get_by_role("menuitem", name="个人资料", exact=True)).to_be_visible()
        expect(page.get_by_role("menuitem", name="退出登录")).to_be_visible()
        page.get_by_role("textbox", name="您的消息").fill("我记得在霍巴特海边的一个夏日午后。");
        page.get_by_role("button", name="发送消息").click()
        expect(page.get_by_text("Tell me whatever part of that afternoon is still with you.")).to_be_visible(timeout=15000)
        expect(page.get_by_role("complementary", name="地点 工作区")).to_be_visible()
        expect(page.get_by_role("heading", name="地点")).to_be_visible()
        expect(page.get_by_text("大致城市")).to_be_visible()
        assert project_requests, "Expected the UI to create a Memoir project"
        assert project_requests[-1].post_data_json.get("language") is None
        assert agent_requests, "Expected the UI to create a localized Codex turn"
        assert agent_requests[-1].get("language") is None

        page.reload(wait_until="networkidle")
        expect(page.get_by_role("heading", name="让我们一起回忆。")).to_be_visible()
        page.get_by_role("button", name="打开个人资料菜单").click()
        expect(page.locator(".profile-dropdown select")).to_have_count(0)
        expect(page.get_by_text("思考步骤")).to_be_visible()
        assert "Memoir." not in page.locator("body").inner_text(), "A raw translation key leaked into the story shell"

        browser_locale_context = browser.new_context(locale="zh-CN")
        browser_locale_page = browser_locale_context.new_page()
        browser_locale_page.goto(f"{args.base_url}/memoir", wait_until="networkidle")
        expect(browser_locale_page.get_by_role("heading", name="用自己的话，讲述自己的人生")).to_be_visible()
        expect(browser_locale_page.get_by_role("combobox", name="语言")).to_have_value("zh-CN")
        browser_locale_context.close()

        unsupported_locale_context = browser.new_context(locale="fr-FR")
        unsupported_locale_page = unsupported_locale_context.new_page()
        unsupported_locale_page.goto(f"{args.base_url}/memoir", wait_until="networkidle")
        expect(unsupported_locale_page.get_by_role("heading", name="Start with a conversation.")).to_be_visible()
        expect(unsupported_locale_page.get_by_role("combobox", name="Language")).to_have_value("en-AU")
        unsupported_locale_context.close()

        error_context = browser.new_context(locale="zh-CN")
        error_page = error_context.new_page()
        error_page.route(
            "**/api/v1/memoir/projects",
            lambda route: route.fulfill(
                status=500,
                headers={"X-Error-Code": "UNKNOWN_PROVIDER"},
                content_type="application/json",
                body=json.dumps({"detail": "provider secret leaked"}),
            ),
        )
        error_page.goto(f"{args.base_url}/memoir", wait_until="networkidle")
        expect(error_page.get_by_role("heading", name="用自己的话，讲述自己的人生")).to_be_visible()
        error_page.get_by_role("button", name=re.compile("开始讲我的故事")).click()
        expect(error_page.get_by_text("出了点问题，请再试一次。")).to_be_visible()
        assert "provider secret leaked" not in error_page.locator("body").inner_text()
        error_context.close()

        voice_context = browser.new_context(locale="en-AU")
        voice_page = voice_context.new_page()
        voice_page.add_init_script(
            """
            let recorderStarts = 0;
            class FakeTrack { stop() {} }
            class FakeStream {
                getTracks() { return [new FakeTrack()]; }
            }
            class FakeRecorder {
                static isTypeSupported() { return true; }
                constructor() { this.state = "inactive"; this.mimeType = "audio/webm"; this.listeners = {}; }
                addEventListener(name, callback) { this.listeners[name] = callback; }
                start() {
                    this.state = "recording";
                    recorderStarts += 1;
                    if (recorderStarts === 1) window.setTimeout(() => this.stop(), 40);
                }
                stop() {
                    if (this.state === "inactive") return;
                    this.state = "inactive";
                    this.listeners.dataavailable?.({ data: new Blob(["voice"], { type: "audio/webm" }) });
                    this.listeners.stop?.();
                }
            }
            Object.defineProperty(navigator, "mediaDevices", { value: navigator.mediaDevices || {}, configurable: true });
            navigator.mediaDevices.getUserMedia = async () => new FakeStream();
            window.MediaRecorder = FakeRecorder;
            Object.defineProperty(window, "speechSynthesis", { value: undefined, configurable: true });
            """
        )
        voice_agent_requests = []

        def voice_codex_turn(route) -> None:
            voice_agent_requests.append(route.request.post_data_json)
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "reply": "我会陪你慢慢回忆那个午后。",
                "trace": [],
                "trace_mode": "codex",
            }))

        voice_page.route("**/api/v1/memoir/story/transcriptions", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"text": "我叫韩博慧，我想从小时候的一个夏日午后开始。", "source": {"language": "zh"}}),
        ))
        voice_page.route("**/api/v1/memoir/agent/turn", voice_codex_turn)
        voice_page.goto(f"{args.base_url}/memoir", wait_until="networkidle")
        voice_page.get_by_role("button", name="Begin my story").click()
        expect(voice_page.get_by_role("button", name="Start voice conversation")).to_be_visible()
        voice_page.get_by_role("button", name="Start voice conversation").click()
        expect(voice_page.locator("html")).to_have_attribute("lang", "en-AU", timeout=15000)
        expect(voice_page.get_by_text("我会陪你慢慢回忆那个午后。")).to_be_visible(timeout=15000)
        assert voice_agent_requests, "Expected the voice turn to reach the agent"
        assert voice_agent_requests[-1].get("language") is None
        voice_page.get_by_role("button", name="结束语音对话").click()
        voice_page.get_by_role("button", name="打开个人资料菜单").click()
        expect(voice_page.locator(".profile-dropdown select")).to_have_count(0)
        voice_context.close()
        browser.close()


if __name__ == "__main__":
    main()
