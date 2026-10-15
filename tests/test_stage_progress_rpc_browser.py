"""Run the production ring/reload/recovery checks through real extraction RPCs."""
import os

import pytest

import stage_progress_fixture
import test_stage_readiness_browser as browser_checks
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database
from test_shared_memory_events_postgres import literal, rpc


pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires isolated source frontend')


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
@pytest.mark.parametrize('recovery', ['ready', 'delayed-fences'])
def test_primary_narration_rings_with_short_cues_and_persisted_reload(sql, monkeypatch, locale, recovery):
    def extract_stage(sql, project, source, stage):
        ref = {'source_id':source['id'], 'version':source['version'], 'quote':source['text'],
               'char_start':0, 'char_end':len(source['text'])}
        # All fixture words are principal narration, while placement has only
        # a two-character cue. Readiness must retain the full primary account.
        cue = {**ref, 'quote':source['text'][:2], 'char_end':2}
        proposal = {'kind':'event', 'title':'Synthetic ' + stage, 'life_stage':stage,
                    'source_refs':[ref], 'stage_evidence':[cue]}
        rpc(sql, 'apply_user_memory_events', f"{literal(project)},"
            f"{literal([{'id':source['id'],'version':source['version']}])}::jsonb,{literal([proposal])}::jsonb")

    # Reuse the inspected CSS/pixel checks without changing PR69-owned fixtures.
    # This substitutes only the synthetic extraction boundary, never totals.
    monkeypatch.setattr(stage_progress_fixture, 'link_stage', extract_stage)
    browser_checks.test_canonical_stage_rings_render_saved_words_and_reload(sql, monkeypatch, locale, recovery)
