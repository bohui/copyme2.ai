"""Run explicitly against a task-owned source frontend; never a deployed site."""
import asyncio
import json
import os

import pytest

from scripts import memoir_skill_eval_suite as suite
from scripts.memoir_skill_eval_application import ControlledApplication


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
def test_cli_game_play_reload_new_context_and_revocation_have_browser_witnesses(tmp_path, locale):
    assert os.getenv('MEMOIR_BROWSER_URL'), 'Start the task-owned source frontend for this explicit browser check'
    from scripts.run_memoir_skill_evaluation import main
    assert main(['--execute', '--controlled-application', '--browser-url', os.environ['MEMOIR_BROWSER_URL'],
        '--case', f'memoir-story-game/play/{locale}', '--output-root', str(tmp_path), '--max-skill-calls', '16']) == 1
    result = json.loads((tmp_path / 'receipt.json').read_text())
    row, = result['results']
    assert row['contract']['status'] == 'pass', row
    assert row['canonical_delivery'] and row['positive_delivery']
    assert row['witnesses']['browser_observed']
    native = json.loads((tmp_path / row['witnesses']['receipt_path']).read_text())
    browser = native['game']['browser']
    assert browser['visits'] == ['initial', 'reload', 'new_context']
    assert browser['revoked'] and not browser['external_network_allowed']
    assert len(native['game']['published_game']['scenes']) == 2
