"""Opt-in real web-proxy smoke: four synthetic replies, no API replacements.

Creates an anonymous test memoir through the UI. Its account/project and saved
test exchanges remain available for readback; never use an existing customer
session. This is a normal-route rendering/save smoke, not candidate acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from playwright.sync_api import expect, sync_playwright


OBSERVE = r"""
(() => {
  window.proxySmoke = [];
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (url, options) => {
    if (!String(url).endsWith('/agent/turn')) return originalFetch(url, options);
    const row = {started: performance.now(), events: {}, earlyUnlock: false, errors: 0};
    window.proxySmoke.push(row);
    const response = await originalFetch(url, options);
    row.httpStatus = response.status;
    row.contentType = response.headers.get('content-type');
    // Observe the native reader before handing each unchanged packet to the
    // UI. A competing clone can lag and falsely report an early unlock.
    const getReader = response.body.getReader.bind(response.body);
    response.body.getReader = (...args) => {
      const reader = getReader(...args);
      const read = reader.read.bind(reader);
      const decoder = new TextDecoder();
      let pending = '';
      reader.read = async (...readArgs) => {
        const packet = await read(...readArgs);
        try {
          pending += decoder.decode(packet.value, {stream: !packet.done});
          const lines = pending.split('\n');
          pending = lines.pop();
          if (packet.done && pending) { lines.push(pending); pending = ''; }
          for (const line of lines.filter(s => s.trim())) {
            const event = JSON.parse(line);
            if (event.type === 'text_delta' && !event.text) continue;
            row.events[event.type] ??= (performance.now() - row.started) / 1000;
            if (event.type === 'error') row.errors++;
          }
        } catch {
          row.observerFailed = true;
        }
        return packet;
      };
      return reader;
    };
    return response;
  };
  new MutationObserver(() => {
    const row = window.proxySmoke.at(-1);
    if (!row || !row.events.text_delta) return;
    const text = [...document.querySelectorAll('.assistant-message .message-text')].at(-1);
    if (text && !text.hidden && text.textContent.trim()) {
      row.firstRenderedText ??= (performance.now() - row.started) / 1000;
    }
    const button = document.querySelector('#chat-form button[type=submit]');
    if (button && !button.disabled && !row.events.conversation_saved) row.earlyUnlock = true;
  }).observe(document, {subtree: true, childList: true, attributes: true, characterData: true});
})();
"""


def smoke(origin, timeout):
    root = Path(__file__).resolve().parents[1]
    paths = ['apps/web/client/memoir/client.js', 'apps/api/codex_runtime.py',
        'apps/api/codex_worker_service.py', 'apps/api/interview_plan.py',
        'apps/api/conversation_locale.py', 'scripts/smoke_conversation_proxy.py']
    print(json.dumps({'kind': 'frozen_proxy_smoke', 'revision': subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], text=True).strip(), 'foreground_generation_budget': 3,
        'source_sha256': hashlib.sha256(b''.join((root / path).read_bytes() for path in paths)).hexdigest(),
        'per_generation_timeout_s': timeout,
        'cases': ['first', 'later_replay', 'later_name_change', 'resumed_pause'],
        'measurement': 'Browser render + real proxy event receipt; normal service configuration'}), flush=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.add_init_script(OBSERVE)
            page.goto(origin.rstrip('/') + '/memoir', wait_until='networkidle', timeout=30000)
            page.get_by_role('button', name='Begin my story').click()
            expect(page.locator('#chat-input')).to_be_visible(timeout=30000)
            print(json.dumps({'kind': 'synthetic_test_project', 'path': page.url.split('/memoir/')[-1]}), flush=True)
            assert page.evaluate('proxySmoke.length') == 0, 'The introduction must not generate a model reply'
            # Keep the opening turn profile-neutral so its saved reply is
            # eligible for replay before the later name correction advances
            # the canonical preference revision and fences older replies.
            cases = [('first', 'I love walking along the harbour near my home.'),
                ('later_replay', 'I also like tending herbs on weekends.'),
                ('later_name_change', 'Please call me Rowan instead.'),
                ('resumed_pause', 'I would like to pause here. Please do not ask another question.')]
            saved_reply = None
            for index, (case, text) in enumerate(cases):
                if case == 'resumed_pause':
                    page.reload(wait_until='networkidle')
                    expect(page.locator('#chat-input')).to_be_visible(timeout=30000)
                    toggle = page.locator('[data-action=toggle-chat-history]')
                    if toggle.count() and toggle.get_attribute('aria-expanded') == 'false': toggle.click()
                    # A profile correction invalidates older generated replies
                    # under the canonical read fence. Verify the accepted
                    # testimony survives reload, then let the resumed turn
                    # generate a fresh reply under the new preference revision.
                    expected_sources = [item[1] for item in cases[:index]]
                    page.wait_for_function('expected => [...document.querySelectorAll(".user-message .message-text")]'
                        '.map(node => node.innerText.replace(/\\s+/g," ").trim()).filter(Boolean).slice(-expected.length)'
                        '.join("\\n") === expected.map(value => value.replace(/\\s+/g," ").trim()).join("\\n")',
                        arg=expected_sources, timeout=30000)
                    print(json.dumps({'kind': 'proxy_smoke_reload', 'restored_source_count': len(expected_sources),
                        'assistant_count': page.locator('.assistant-message').count()}), flush=True)
                    assert page.evaluate('proxySmoke.length') == 0, 'Reload must not resubmit saved testimony'
                elif case == 'later_name_change':
                    # Reload before the profile correction. The canonical read
                    # fence may replay this saved reply or hide it if an
                    # asynchronous preference update has already advanced the
                    # revision; either result must preserve the testimony and
                    # never duplicate a visible reply.
                    page.reload(wait_until='networkidle')
                    expect(page.locator('#chat-input')).to_be_visible(timeout=30000)
                    toggle = page.locator('[data-action=toggle-chat-history]')
                    if toggle.count() and toggle.get_attribute('aria-expanded') == 'false': toggle.click()
                    expected_sources = [item[1] for item in cases[:index]]
                    page.wait_for_function('expected => [...document.querySelectorAll(".user-message .message-text")]'
                        '.map(node => node.innerText.replace(/\\s+/g," ").trim()).filter(Boolean).slice(-expected.length)'
                        '.join("\\n") === expected.map(value => value.replace(/\\s+/g," ").trim()).join("\\n")',
                        arg=expected_sources, timeout=30000)
                    replay_count = page.evaluate('expected => [...document.querySelectorAll(".assistant-message .message-text")]'
                        '.filter(node => node.innerText.replace(/\\s+/g," ").trim() === expected.replace(/\\s+/g," ").trim()).length',
                        saved_reply)
                    assert replay_count in {0, 1}, 'A saved reply may be fenced, but must never duplicate'
                    print(json.dumps({'kind': 'proxy_smoke_replay', 'restored_match_count': replay_count,
                        'reply_fenced': replay_count == 0,
                        'assistant_count': page.locator('.assistant-message').count()}), flush=True)
                    assert page.evaluate('proxySmoke.length') == 0, 'Reload must not resubmit saved testimony'
                before = page.evaluate('proxySmoke.length')
                page.locator('#chat-input').fill(text)
                page.locator('#chat-form button[type=submit]').click()
                page.wait_for_function('n => proxySmoke.length === n + 1 && proxySmoke.at(-1).events.conversation_saved',
                    arg=before, timeout=timeout * 1000)
                expect(page.locator('#chat-form button[type=submit]')).to_be_enabled(timeout=10000)
                row = page.evaluate('proxySmoke.at(-1)')
                saved_reply = page.locator('.assistant-message .message-text').last.inner_text()
                print(json.dumps({'kind': 'proxy_smoke_receipt', 'case': case,
                    'http_status': row['httpStatus'], 'content_type': row['contentType'],
                    'events': row['events'], 'first_rendered_text_s': row.get('firstRenderedText'),
                    'early_unlock': row['earlyUnlock'], 'errors': row['errors'],
                    'question_count': saved_reply.count('?') + saved_reply.count('？')}), flush=True)
                assert row['httpStatus'] == 200 and 'ndjson' in row['contentType']
                assert row['errors'] == 0 and not row.get('observerFailed') and not row['earlyUnlock']
                assert row.get('firstRenderedText') is not None and saved_reply.strip()
                assert 'reply_complete' in row['events']
                assert row['events']['text_delta'] <= row['events']['conversation_saved']
                # A pure name correction is complete with a direct acknowledgement;
                # it must not force an unrelated interview question. A pause also
                # deliberately has no question, while the opening offers one.
                question_count = saved_reply.count('?') + saved_reply.count('？')
                allowed_questions = {1} if case == 'first' else {0, 1}
                assert question_count in allowed_questions
                # Saved history can collapse older exchanges. Inspect the full
                # history before counting, using the rendered control.
                toggle = page.locator('[data-action=toggle-chat-history]')
                if toggle.count() and toggle.get_attribute('aria-expanded') == 'false': toggle.click()
                expect(page.locator('.user-message .message-text')).to_have_count(index + 1)
                normalized = saved_reply.replace('\\n', ' ').split()
                assert page.evaluate('expected => [...document.querySelectorAll(".assistant-message .message-text")]'
                    '.filter(node => node.innerText.replace(/\\s+/g," ").trim() === expected).length === 1',
                    ' '.join(normalized)), 'The saved reply must render exactly once'
                print(json.dumps({'kind': 'proxy_smoke_result', 'case': case, 'status': 'saved',
                    'timings': row['events'], 'first_rendered_text_s': row['firstRenderedText'],
                    'early_unlock': row['earlyUnlock'], 'duplicate_reply': False}), flush=True)
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', default='http://127.0.0.1:3010')
    parser.add_argument('--timeout', type=int, default=120)
    args = parser.parse_args()
    if not 0 < args.timeout <= 120: parser.error('Timeout must be between 1 and 120 seconds')
    try:
        smoke(args.origin, args.timeout)
    except Exception as error:
        print(json.dumps({'kind': 'proxy_smoke_failed', 'failure_class': type(error).__name__}), flush=True)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
