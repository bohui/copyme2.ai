"""Application-owned, bounded phase policy; no model/provider calls."""
import pytest
from pydantic import ValidationError
from apps.api.conversation_phase import PhaseState, PhaseProposal, resolve_phase


def apply(state=None, *, action=None, phase=None, narration=False, turn='00000000-0000-4000-8000-000000000001', **kwargs):
    return resolve_phase(state, PhaseProposal(action=action, phase=phase), source_turn_id=turn, has_narration=narration, **kwargs)


def test_legacy_narration_resumes_but_empty_journey_starts_gently():
    assert apply().phase == 'comfort'
    assert apply(narration=True).phase == 'explore'


@pytest.mark.parametrize('phase', ['comfort','explore','shape'])
def test_explicit_preferences_survive_automatic_proposals_and_reload(phase):
    state=apply(action=phase)
    assert state.selection=='explicit' and state.preferred_phase==phase
    restored=PhaseState.model_validate_json(state.model_dump_json())
    assert apply(restored,phase='explore',narration=True)==restored


def test_shape_needs_explicit_choice_and_correction_retains_preference():
    with pytest.raises(ValueError): apply(phase='shape')
    state=apply(action='shape')
    corrected=apply(state,action='correction')
    assert corrected.phase=='explore' and corrected.preferred_phase=='shape'
    assert corrected.selection=='explicit'


def test_pause_persists_until_explicit_resume():
    paused=apply(action='pause')
    assert apply(paused,phase='explore')==paused
    assert not apply(paused,action='resume').paused


def test_replay_and_stale_proposals_do_not_increment_or_overwrite():
    state=apply(action='shape')
    assert apply(state,action='shape')==state
    assert apply(state,phase='explore',expected_revision=0)==state


def test_automatic_mode_is_an_explicit_choice():
    state=apply(action='comfort')
    state=apply(state,action='automatic',narration=True,turn='00000000-0000-4000-8000-000000000002')
    assert state.selection=='automatic' and state.preferred_phase is None and state.phase=='explore'


@pytest.mark.parametrize('value',[{'phase':'trust'}, {'revision':-1}, {'paused':'false'}, {'schema_version':2}, {'private_reasoning':'secret'}])
def test_envelope_rejects_unknown_or_untyped_state(value):
    with pytest.raises(ValidationError): PhaseState.model_validate(value)

@pytest.mark.parametrize('text,action', [('pause','pause'),('请暂停一下。','pause'),('Shape my story','shape'),('帮我整理故事','shape'),('Keep talking','comfort'),('换个话题','skip')])
def test_explicit_current_controls(text,action):
    from apps.api.conversation_phase import explicit_action
    assert explicit_action(text)==action

@pytest.mark.parametrize('text',["I don't want to pause", 'He told me to stop', '"shape my story"', '别暂停', '他说不要再讲了'])
def test_reports_quotes_and_negation_do_not_change_preference(text):
    from apps.api.conversation_phase import explicit_action
    assert explicit_action(text) is None

@pytest.mark.parametrize('value',[{'selection':'explicit'}, {'preferred_phase':'shape'}])
def test_incoherent_preferences_are_rejected(value):
    with pytest.raises(ValidationError): PhaseState.model_validate(value)

@pytest.mark.parametrize('text',["I want to pause", "Let's pause", 'Can we stop for now?', '我想暂停一下', '先不聊了', 'Pause?'])
def test_ordinary_direct_pause_requests(text):
    from apps.api.conversation_phase import explicit_action
    assert explicit_action(text)=='pause'

@pytest.mark.parametrize('text',['This memory is upsetting. I want to pause.', '这段回忆很难受。请暂停一下。'])
def test_pause_after_current_disclosure(text):
    from apps.api.conversation_phase import explicit_action
    assert explicit_action(text)=='pause'

@pytest.mark.parametrize('text',['这段回忆让我难受，我想暂停一下。','This is upsetting, I want to pause.'])
def test_direct_trailing_first_person_pause(text):
    from apps.api.conversation_phase import explicit_action
    assert explicit_action(text)=='pause'

@pytest.mark.parametrize('text',['他说，我想暂停一下。','He said, I want to pause.', '她说“我想暂停一下。”'])
def test_reported_trailing_request_is_not_control(text):
    from apps.api.conversation_phase import explicit_action
    assert explicit_action(text) is None

@pytest.mark.parametrize('text',['She said:\nI want to pause.\nThose were her words.','她说：\n我想暂停一下。\n这是她的原话。'])
def test_multiline_report_does_not_gain_current_user_authority(text):
    from apps.api.conversation_phase import explicit_action
    assert explicit_action(text) is None
