"""Runtime fixture contract coverage without starting a browser or provider."""
import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from apps.api.conversation_recovery import ConversationHistory
from test_browser_recovery_routes import (BrowserTransport, Route, replace_playwright, CapturedBrowserBoot)
import test_recall_browser as recall_browser
import test_stage_readiness_browser as stage_browser


class StoryTransport(BrowserTransport):
    clock = SimpleNamespace(install=lambda: None)

    def set_default_timeout(self, timeout): pass

    def request(self, path, **options):
        route = Route(path, **options)
        route.request.post_data_json = options.get('payload')
        self.handlers['**/api/v1/memoir/**'](route)
        assert route.response is not None
        return route


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
@pytest.mark.parametrize('developer', [False, True])
@pytest.mark.parametrize('anonymous', [False, True])
def test_recall_runtime_registers_owned_history_and_persists_the_acknowledged_turn(monkeypatch, locale, developer, anonymous):
    def visit(transport):
        response = transport.request('/projects', method='POST', payload={'mode': 'self'}, token='token')
        project_id = response.body['id']
        history_path = '/user/projects/' + project_id + '/history?limit=100'
        history = ConversationHistory.model_validate(transport.request(history_path, token='token').body)
        assert history.project_id == project_id and history.items == [] and history.next_cursor is None
        packet = {'project_id': project_id, 'client_turn_id': '60c00000-0000-4000-8000-000000000010',
                  'text': 'The storyteller said: A memory from the garden', 'conversation_text': 'A memory from the garden'}
        streamed = transport.request('/agent/turn', method='POST', payload=packet, token='token')
        events = [json.loads(line) for line in streamed.response['body'].splitlines()]
        saved = next(event['data'] for event in events if event['type'] == 'conversation_saved')
        history = ConversationHistory.model_validate(transport.request(history_path, token='token').body)
        assert len(history.items) == 1
        item = history.items[0]
        assert item.client_turn_id == packet['client_turn_id'] == saved['client_turn_id']
        assert item.server_turn_id == saved['server_turn_id'] and str(UUID(item.server_turn_id)) == item.server_turn_id
        assert item.narrator_text == packet['conversation_text'] and item.reply == saved['reply']
        assert item.source_status == 'active' and item.source_version == '1'
        assert transport.request(history_path, token='wrong-owner').status == 401
        assert transport.request('/user/projects/foreign/history?limit=100', token='token').status == 404
        for path, method, status in [
            (history_path, 'POST', 405),
            ('/user/projects/' + project_id + '/history?cursor=malformed', 'GET', 422),
            ('/user/projects/' + project_id + '/history?limit=1&limit=2', 'GET', 422),
            ('/user/projects/' + project_id + '/history?unexpected=true', 'GET', 422),
            ('/user/projects/' + project_id + '/not-history', 'GET', 404),
        ]:
            rejected = transport.request(path, method=method, token='token')
            assert rejected.status == status and 'items' not in rejected.body
        assert transport.request(history_path, token='token').body['items'][0]['client_turn_id'] == packet['client_turn_id']
    transport = StoryTransport(visit)
    replace_playwright(monkeypatch, recall_browser, transport)
    with pytest.raises(CapturedBrowserBoot):
        recall_browser.test_final_reply_package_selection_refresh_and_payment(locale, anonymous, developer)


def test_busy_recall_runtime_restores_canonical_legacy_text_and_project_scoped_openings(monkeypatch):
    def visit(transport):
        history = ConversationHistory.model_validate(transport.request(
            '/user/projects/history-project/history?limit=100', token='token').body)
        assert history.project_id == 'history-project' and len(history.items) == 1
        assert history.items[0].narrator_text == 'I remember my childhood garden.'
        assert history.items[0].reply == 'Tell me about that garden.'
        legacy = transport.request('/user/conversations', token='token').body
        assert all(item.get('project_id') == 'history-project' for item in legacy['items'] if item['id'] == 'guest')
    transport = StoryTransport(visit)
    replace_playwright(monkeypatch, recall_browser, transport)
    with pytest.raises(CapturedBrowserBoot):
        recall_browser.test_account_history_and_busy_preview_resume_without_manual_retry()


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
@pytest.mark.parametrize('mapped', [False, True])
def test_stage_runtime_keeps_place_evidence_and_uses_only_the_eligible_draft_stage(monkeypatch, locale, mapped):
    def visit(transport):
        config = transport.request('/agent/config', token='fixture-only').body
        assert not config.get('show_thinking_steps')
        status = transport.request('/story/state', token='fixture-only').body['recall_status']
        assert status['rounds_completed'] == (20 if mapped else 5)
        assert status['paid'] is mapped and status['payment_required'] is False
        project = transport.request('/projects/stage-project', token='fixture-only').body
        place = transport.request('/agent/turn', method='POST', token='fixture-only', payload={}).body['place_journey']
        assert place['place'] == 'Chengde'  # Never erase the unmapped cue to hide its workspace.
        assert ('latitude' in place) is mapped
        assert bool(project['profile'].get('memory_places')) is mapped
        history = ConversationHistory.model_validate(transport.request(
            '/user/projects/stage-project/history?limit=100', token='fixture-only').body)
        assert history.project_id == 'stage-project' and history.items == []
    transport = StoryTransport(visit)
    replace_playwright(monkeypatch, stage_browser, transport)
    with pytest.raises(CapturedBrowserBoot):
        stage_browser.test_stage_rings_and_saved_private_draft(locale, mapped)
