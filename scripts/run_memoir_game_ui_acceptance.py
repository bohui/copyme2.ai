#!/usr/bin/env python3
"""Approve/play fictional campaign games through the real UI after 50 saved turns."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.memoir_fifty_readback import CASE_IDS, CHECKPOINTS, _original_cases
from scripts.run_memoir_supabase_evaluation import CASE_EMAILS, private_json
from scripts.run_memoir_live_skills import save


def ready_cases(receipt):
    ready = {}
    for case in receipt.get('evaluation', {}).get('cases', []):
        if case.get('status') != 'completed':
            continue
        rounds = case.get('rounds', [])
        if (case.get('case_id') not in CASE_IDS or len(rounds) != 50
                or [r.get('round') for r in rounds] != list(range(1, 51))
                or any(r.get('status') != 'completed' or not r.get('reply', '').strip()
                    or not r.get('accepted_source_id') for r in rounds)
                or len({r.get('accepted_source_id') for r in rounds}) != 50
                or sorted(c['milestone'] for c in case.get('checkpoints', [])) != list(CHECKPOINTS)
                or not case.get('evidence_validated')):
            raise ValueError('completed_case_evidence_invalid')
        if case.get('user_email') != CASE_EMAILS[case['case_id']]:
            raise ValueError('fixed_case_owner_required')
        ready[case['case_id']] = case
    return ready


def exercise(case, original, base, output, settings):
    from playwright.sync_api import expect, sync_playwright
    import psycopg
    result = dict(case_id=case['case_id'], owner_id=case['owner_id'], project_id=case['project_id'],
        status='running', scope='fictional author approval; real UI, Auth, API, Supabase and provider',
        started_at=datetime.now(timezone.utc).isoformat(), conversation_turns_submitted=0,
        synthetic_person_permissions=True, errors=[], game_responses=[], photo_responses=[])
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    receipt_path = output / 'receipt.json'
    save(receipt_path, result)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1280, 'height': 900}, has_touch=True)
            page = context.new_page()
            history = {}
            def observed(response):
                path = urlsplit(response.url).path
                if response.ok and path.endswith('/user/projects/' + case['project_id'] + '/history'):
                    snapshot = response.json()
                    if snapshot.get('project_id') == case['project_id']:
                        history.clear(); history.update(snapshot)
                if '/story-game' in path:
                    result['game_responses'].append(dict(method=response.request.method, path=path, status=response.status))
                if response.ok and (path.endswith('/story/readiness') or '/agent/places/' in path and path.endswith('/photos')):
                    try:
                        body = response.json()
                        if path.endswith('/story/readiness'):
                            workspace = body.get('derived_workspace') or {}
                            places = workspace.get('places') or []
                            result['location_readback'] = dict(authoritative=workspace.get('authoritative') is True,
                                places=len(places), coordinate_pairs=sum(p.get('latitude') is not None and p.get('longitude') is not None for p in places))
                        else:
                            photos = body.get('photos') or []
                            result['photo_responses'].append(dict(status=body.get('status'), searching=body.get('searching'),
                                photos=len(photos), attributed_sources=sum(bool(p.get('source_url')) for p in photos)))
                    except (ValueError, TypeError, AttributeError):
                        result['readback_metadata_unavailable'] = True
                if response.status >= 400 and '/api/v1/memoir/' in path:
                    result['errors'].append(dict(path=path, status=response.status))
            page.on('response', observed)
            try:
                page.goto(base + '/memoir')
                page.locator('details:has(#agent-email) > summary').click()
                page.locator('#agent-email').fill(case['user_email'])
                page.locator('#agent-password').fill('test1234')
                with page.expect_response(lambda r: '/auth/v1/token' in r.url and r.request.method == 'POST') as auth:
                    page.locator('[data-auth-action="signin"]').click()
                signed = auth.value.json()
                assert signed['user']['id'] == case['owner_id'], 'authenticated_owner_changed'
                page.goto(base + '/memoir/interview/' + case['project_id'])
                expect(page.locator('.chat-history-toggle')).to_be_visible(timeout=45000)
                if page.locator('.chat-history-toggle').get_attribute('aria-expanded') == 'false':
                    page.locator('.chat-history-toggle').click()
                expect(page.locator('.user-message .message-text')).to_have_count(50, timeout=30000)
                actual = page.locator('.user-message .message-text').all_inner_texts()
                assert actual == original['rounds'], 'UI_originals_differ'
                assert history.get('items') and history.get('next_cursor') is None, 'authoritative_UI_history_missing'
                authorized = [item for item in history['items'] if item.get('reply')]
                expected_ids = ['history-' + item['server_turn_id'] + '-assistant' for item in authorized]
                replies = page.locator('.assistant-message[data-message-id$="-assistant"]')
                expect(replies).to_have_count(len(expected_ids))
                assert replies.evaluate_all('(rows) => rows.map(row => row.dataset.messageId)') == expected_ids, 'UI_reply_authority_differ'
                result['ui_originals_verified'] = 50
                result['ui_replies_verified'] = len(authorized)
                result['saved_replies_verified_in_campaign'] = 50
                result['historical_replies_withheld_by_current_authority'] = sum(
                    bool(item.get('narrator_text')) and not item.get('reply') for item in history['items'])
                result['historical_clues_visible'] = page.locator('.historical-context').count()
                result['photos_visible_in_history'] = page.locator('.assistant-message img').count()
                expect(page.locator('.private-draft-status')).to_contain_text('50', timeout=30000)
                result['draft_round_50_visible'] = True
                opener = page.locator('[data-story-game]').filter(visible=True).first
                expect(opener).to_be_visible(timeout=30000)
                opener.click()
                modal = page.locator('.story-game-modal')
                expect(modal).to_be_visible()
                complete = page.locator('[data-complete-memoir]')
                if complete.count():
                    complete.click()
                    expect(page.locator('[data-game-consent]')).to_be_visible(timeout=180000)
                consent = page.locator('[data-game-consent]')
                if consent.count():
                    consent.locator('input').check()
                    consent.locator('[data-generate-game]').click()
                    expect(page.locator('[data-game-review]')).to_be_visible(timeout=180000)
                review = page.locator('[data-game-review]')
                result['author_review_performed'] = bool(review.count())
                if review.count():
                    expect(review.locator('[data-game-permission]')).to_have_count(2)
                    expect(page.locator('[data-story-game-player]')).to_have_count(0)
                    result['exact_candidate_review_sha256'] = hashlib.sha256(review.inner_text().encode()).hexdigest()
                    for checkbox in review.locator('input').all():
                        checkbox.check()
                    review.locator('[data-publish-game]').click()
                player = page.locator('[data-story-game-player]')
                expect(player).to_be_visible(timeout=30000)
                first = player.get_attribute('data-game-scene')
                stage = page.locator('.game-stage')
                stage.focus(); page.keyboard.down('ArrowRight')
                page.wait_for_function("Number(document.querySelector('[data-story-game-player]').dataset.gamePosition)>540")
                page.keyboard.up('ArrowRight')
                page.locator('[data-game-interact]').click()
                expect(page.locator('.game-dialogue')).to_be_visible()
                stage.focus(); page.keyboard.down('ArrowRight')
                page.wait_for_function("first=>document.querySelector('[data-story-game-player]').dataset.gameScene!==first", arg=first)
                page.keyboard.up('ArrowRight')
                page.locator('.game-text-equivalent summary').click()
                assert page.locator('.game-text-equivalent section').count() == 2
                result.update(two_scenes_travelled=True, reviewed_dialogue_visible=True, text_equivalent_visible=True)
                page.screenshot(path=str(output / 'published-game.png'))
                page.reload()
                opener = page.locator('[data-story-game]').filter(visible=True).first
                expect(opener).to_be_visible(timeout=45000)
                opener.click()
                expect(player).to_be_visible(timeout=30000)
                result['published_game_recovers_after_reload'] = True
                # The browser never receives provider receipts or original lineage.
                with psycopg.connect(settings['MEMOIR_PUBLICATION_DATABASE_URL']) as connection:
                    row = connection.execute('''select id,state,model_receipt,candidate_digest,
                        jsonb_array_length(candidate->'game'->'scenes'),jsonb_array_length(candidate->'game'->'npcs')
                        from public.user_story_game where user_id=%s and project_id=%s and state='published' ''',
                        (case['owner_id'], case['project_id'])).fetchone()
                    assert row and row[2]['status'] == 'completed' and row[2].get('response_id') and row[2].get('model')
                    assert row[4:] == (2, 2)
                    result.update(game_id=str(row[0]), model_receipt=row[2], candidate_digest=row[3])
                result['status'] = 'passed'
            finally:
                if result['status'] != 'passed':
                    page.screenshot(path=str(output / 'failure.png'))
                context.close(); browser.close()
    except Exception as error:
        result.update(status='failed', error_class=type(error).__name__)
        message = str(error)
        if isinstance(error, AssertionError) and message.replace('_', '').isalnum() and len(message) < 90:
            result['reason'] = message
    result['completed_at'] = datetime.now(timezone.utc).isoformat()
    save(receipt_path, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--case', choices=CASE_IDS)
    parser.add_argument('--execute', action='store_true', help='Approve fictional adults/candidate and privately publish via UI')
    parser.add_argument('--web-base', default='http://127.0.0.1:3011')
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    args = parser.parse_args()
    parsed = urlsplit(args.web_base)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost'} or parsed.query or parsed.fragment or parsed.path:
        parser.error('Use a known local Memoir frontend origin')
    receipt = private_json(args.run_dir / 'receipt.json')
    ready = ready_cases(receipt)
    selected = [args.case] if args.case else [case for case in CASE_IDS if case in ready]
    if not args.execute:
        print(json.dumps(dict(ready=list(ready), selected=selected, browser_started=False, writes=0)))
        return 0
    if not selected or any(case not in ready for case in selected):
        raise ValueError('Fifty complete original rounds and ten checkpoints are required before game acceptance')
    from dotenv import dotenv_values
    settings = dotenv_values(args.env_file, interpolate=False)
    originals = {case['id']: case for case in _original_cases()}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    results = [exercise(ready[case], originals[case], args.web_base,
        args.run_dir / 'ui-games' / (case + '-' + stamp), settings) for case in selected]
    print(json.dumps([dict(case_id=r['case_id'], status=r['status'], error_class=r.get('error_class')) for r in results]))
    return 0 if all(r['status'] == 'passed' for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
