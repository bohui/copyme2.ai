"""Stage volume through real persistence/correction RPCs on disposable PostgreSQL."""
import json
from pathlib import Path

import pytest

from apps.api.stage_readiness import readiness
from stage_progress_fixture import save_stage_source
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database, resolve
from test_shared_memory_events_postgres import literal, rpc
from test_agent_commit_postgres import OTHER, as_user


def reference(source, start=0, end=None):
    end = len(source['text']) if end is None else end
    return {'source_id': source['id'], 'version': source['version'],
            'quote': source['text'][start:end], 'char_start': start, 'char_end': end}


def persist(sql, project, source, *, event=None, stage='childhood', cue=None, background=None):
    proposal = {'kind': 'event', 'title': 'Synthetic school account', 'life_stage': stage,
                'source_refs': [reference(source)],
                'stage_evidence': [cue or reference(source)]}
    if event:
        proposal.update(existing_id=event['id'], expected_revision=event['revision'])
    if background:
        proposal['temporal'] = {'expression':'unknown', 'precision':'unknown', 'basis':[reference(background)]}
    rpc(sql, 'apply_user_memory_events', f"{literal(project)},"
        f"{literal([{'id': source['id'], 'version': source['version']}])}::jsonb,"
        f"{literal([proposal])}::jsonb")
    # A fresh session reads the real current revision, including correction writes.
    return json.loads(sql("select row_to_json(e) from public.user_memory_event e "
                          "where data->>'title'='Synthetic school account';").stdout)


def stages(sql, project):
    return rpc(sql, 'read_lifetime_stage_readiness', literal(project))['stages']


def legacy_writers(sql):
    root = Path(__file__).resolve().parents[1]
    old = (root / 'supabase/migrations/202610080001_memory_event_noop.sql').read_text()
    old = old[old.index('create or replace function'):old.index('revoke all on function')]
    sql(old.replace('public.apply_user_memory_events(', 'public.apply_user_memory_events_before_photos('))
    old_correction = (root / 'supabase/migrations/202610040001_shared_memory_events.sql').read_text()
    old_correction = old_correction[old_correction.index('create or replace function public.correct_user_memory_event('):]
    sql(old_correction[:old_correction.index('revoke all on function')])
    sql("alter table public.user_memory_event_source alter column stage_progress_role set default 'legacy';")


def test_workspace_correction_moves_all_saved_direct_narration(sql):
    project = resolve(sql)['project_id']
    source = save_stage_source(sql, project, '忆' * 300)
    event = persist(sql, project, source)
    assert stages(sql, project)['childhood'] == readiness(300)
    assert rpc(sql, 'set_lifetime_event_correction', f"{literal(project)},'{event['id']}',"
               f"{event['revision']},'{{\"life_stage\":\"midlife\"}}','Actually this was in midlife.'") == {'changed': True}
    reloaded = stages(sql, project)
    assert reloaded['childhood'] == readiness(0)
    assert reloaded['midlife'] == readiness(300)
    assert stages(sql, project) == reloaded


def test_multi_turn_enrichment_keeps_prior_primary_narration(sql):
    project = resolve(sql)['project_id']
    first = save_stage_source(sql, project, '童' * 300)
    event = persist(sql, project, first)
    second = save_stage_source(sql, project, '学' * 100)
    event = persist(sql, project, second, event=event)
    assert stages(sql, project)['childhood'] == readiness(400)
    assert stages(sql, project)['midlife'] == readiness(0)
    # A later cue need not repeat either full primary account.
    third = save_stage_source(sql, project, '校' * 157)
    persist(sql, project, third, event=event, cue=reference(third, 0, 2))
    assert stages(sql, project)['childhood'] == readiness(557)


def test_short_placement_cue_does_not_truncate_primary_narration(sql):
    project = resolve(sql)['project_id']
    source = save_stage_source(sql, project, '忆' * 1000)
    persist(sql, project, source, cue=reference(source, 0, 4))
    assert stages(sql, project)['childhood'] == readiness(1000)


def test_author_stage_override_survives_later_enrichment(sql):
    project = resolve(sql)['project_id']
    first = save_stage_source(sql, project, '童' * 300)
    event = persist(sql, project, first)
    rpc(sql, 'set_lifetime_event_correction', f"{literal(project)},'{event['id']}',"
        f"{event['revision']},'{{\"life_stage\":\"midlife\"}}','Actually this was in midlife.'")
    event['revision'] += 1
    second = save_stage_source(sql, project, '学' * 100)
    event = persist(sql, project, second, event=event, stage='childhood', cue=reference(second, 0, 2))
    assert event['life_stage'] == 'midlife'
    assert stages(sql, project)['midlife'] == readiness(400)
    assert stages(sql, project)['childhood'] == readiness(0)


def test_dependency_can_become_primary_without_downgrading_earlier_primary_links(sql):
    project = resolve(sql)['project_id']
    original = save_stage_source(sql, project, '童' * 100)
    cue = save_stage_source(sql, project, '学' * 200)
    event = persist(sql, project, original, cue=reference(original, 0, 2), background=cue)
    assert stages(sql, project)['childhood'] == readiness(100)
    # The cue's pending manifest permits real enrichment of the same event.
    promoted = persist(sql, project, cue, event=event, cue=reference(original, 0, 2))
    assert promoted['revision'] == event['revision'] + 1
    assert stages(sql, project)['childhood'] == readiness(300)
    # Existing primary refs stay primary even when later reused as placement cues.
    third = save_stage_source(sql, project, '校' * 157)
    persist(sql, project, third, event=promoted, cue=reference(original))
    assert stages(sql, project)['childhood'] == readiness(457)


def test_roles_do_not_bypass_owner_revision_version_or_author_exclusion(sql):
    project = resolve(sql)['project_id']
    first = save_stage_source(sql, project, '童' * 300)
    event = persist(sql, project, first)
    assert rpc(sql, 'read_lifetime_stage_readiness', literal(project), owner=OTHER, check=False).returncode
    assert sql(as_user("update public.user_memory_event_source set stage_progress_role='primary';"), check=False).returncode
    assert sql(as_user("select public.apply_user_memory_events_before_photos('none','[]','[]');"), check=False).returncode
    stale = rpc(sql, 'set_lifetime_event_correction', f"{literal(project)},'{event['id']}',0,"
                "'{\"life_stage\":\"midlife\"}','Actually this was in midlife.'", check=False)
    assert stale.returncode
    assert stages(sql, project)['childhood'] == readiness(300)
    rpc(sql, 'unlink_user_memory_event_source', f"{literal(project)},'{event['id']}',"
        f"{event['revision']},'{first['id']}','Remove this synthetic source.'")
    assert all(value == readiness(0) for value in stages(sql, project).values())
    next_source = save_stage_source(sql, project, '学' * 100)
    current = json.loads(sql("select row_to_json(e) from public.user_memory_event e;").stdout)
    proposal = {'kind':'event', 'title':current['data']['title'], 'existing_id':event['id'],
                'expected_revision':current['revision'], 'life_stage':'childhood',
                'source_refs':[reference(first),reference(next_source)], 'stage_evidence':[reference(next_source)]}
    rejected = rpc(sql, 'apply_user_memory_events', f"{literal(project)},"
                   f"{literal([{'id':next_source['id'],'version':1}])}::jsonb,{literal([proposal])}::jsonb", check=False)
    assert rejected.returncode and 'removed source link' in rejected.stderr
    assert all(value == readiness(0) for value in stages(sql, project).values())


def test_edit_requires_new_version_attribution_and_withdrawal_removes_it(sql):
    project = resolve(sql)['project_id']
    first = save_stage_source(sql, project, '童' * 300)
    event = persist(sql, project, first)
    rpc(sql, 'change_user_narrator_source', f"{literal(project)},'{first['id']}',1,'edit','更正童年'")
    assert stages(sql, project)['childhood'] == readiness(0)
    event['revision'] += 1
    edited = {**first, 'text':'更正童年', 'version':2}
    persist(sql, project, edited, event=event, cue=reference(edited, 0, 2))
    assert stages(sql, project)['childhood'] == readiness(4)
    rpc(sql, 'change_user_narrator_source', f"{literal(project)},'{first['id']}',2,'withdraw',null")
    assert all(value == readiness(0) for value in stages(sql, project).values())


@pytest.mark.parametrize('short_cue', [False, True])
def test_upgrade_restores_provable_stage_and_primary_attribution_without_rewriting_evidence(sql, short_cue):
    root = Path(__file__).resolve().parents[1]
    migration = (root / 'supabase/migrations/202610150003_canonical_stage_readiness.sql').read_text()
    # Simulate rows produced by the actual pre-upgrade persistence body.
    legacy_writers(sql)
    try:
        project = resolve(sql)['project_id']
        source = save_stage_source(sql, project, '忆' * 300)
        event = persist(sql, project, source, cue=reference(source, 0, 4) if short_cue else None)
        rpc(sql, 'set_lifetime_event_correction', f"{literal(project)},'{event['id']}',"
            f"{event['revision']},'{{\"life_stage\":\"midlife\"}}','Actually this was in midlife.'")
        before = sql('select record from public.user_memory_event_revision order by revision;').stdout
        sql(migration)
        assert sql('select record from public.user_memory_event_revision order by revision;').stdout == before
        view = stages(sql, project)
        assert view['childhood'] == readiness(0)
        # At its first model revision, the longer quote occurs in no contextual
        # role, so the immutable union proves it was primary narration.
        assert view['midlife'] == readiness(300)
        sql(migration)
        assert stages(sql, project) == view
    finally:
        sql(migration)


def test_legacy_union_records_cannot_distinguish_primary_from_background(sql):
    root = Path(__file__).resolve().parents[1]
    migration = (root / 'supabase/migrations/202610150003_canonical_stage_readiness.sql').read_text()
    legacy_writers(sql)
    try:
        project = resolve(sql)['project_id']
        source = save_stage_source(sql, project, '忆' * 300)
        full, cue = reference(source), reference(source, 0, 4)
        common = {'kind':'event', 'title':'Indistinguishable old records', 'life_stage':'childhood',
                  'stage_evidence':[cue], 'temporal':{'expression':'unknown', 'precision':'unknown', 'basis':[full]}}
        proposals = [{**common, 'source_refs':[ref]} for ref in [full,cue]]
        rpc(sql, 'apply_user_memory_events', f"{literal(project)},"
            f"{literal([{'id':source['id'],'version':1}])}::jsonb,{literal(proposals)}::jsonb")
        records = json.loads(sql("select jsonb_agg(record - array['id','change_sequence']) "
                                 "from public.user_memory_event_revision;").stdout)
        # One proposal has 300 primary words; the other has four, with the
        # longer quote only a temporal dependency. Their saved records match.
        assert len(records) == 2 and records[0] == records[1]
        event_id = sql('select id from public.user_memory_event order by id limit 1;').stdout.strip()
        later = save_stage_source(sql, project, '学' * 10)
        enrichment = {**common, 'existing_id':event_id, 'expected_revision':1,
                      'source_refs':[reference(later)], 'temporal':{'expression':'unknown','precision':'unknown'}}
        rpc(sql, 'apply_user_memory_events', f"{literal(project)},"
            f"{literal([{'id':later['id'],'version':1}])}::jsonb,{literal([enrichment])}::jsonb")
        sql(migration)
        # A later revision no longer lists the long quote as temporal context,
        # but its accumulated link does not become proof of primary ownership.
        assert stages(sql, project)['childhood'] == readiness(14)
    finally:
        sql(migration)
