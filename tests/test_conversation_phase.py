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


def test_shape_needs_explicit_choice():
    with pytest.raises(ValueError): apply(phase='shape')


@pytest.mark.parametrize('action', ['pause', 'resume', 'correction'])
def test_pause_and_event_correction_are_not_phase_actions(action):
    with pytest.raises(ValidationError): apply(action=action)


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

@pytest.mark.parametrize('text,action', [('Shape my story','shape'),('帮我整理故事','shape'),('Keep talking','comfort'),('继续聊聊','comfort'),('Explore a memory','explore'),('聊聊一段回忆','explore'),('换个话题','skip')])
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

@pytest.mark.parametrize('text',["I want to pause", "Let's continue", 'resume', '我想暂停一下', '继续'])
def test_leaving_or_returning_does_not_change_mode(text):
    from apps.api.conversation_phase import explicit_action
    assert explicit_action(text) is None

@pytest.mark.parametrize('text',['他说，我想整理我的故事。','He said, shape my story.', '她说“整理我的故事。”'])
def test_reported_trailing_request_is_not_control(text):
    from apps.api.conversation_phase import explicit_action
    assert explicit_action(text) is None

@pytest.mark.parametrize('text',['She said:\nShape my story.\nThose were her words.','她说：\n整理我的故事。\n这是她的原话。'])
def test_multiline_report_does_not_gain_current_user_authority(text):
    from apps.api.conversation_phase import explicit_action
    assert explicit_action(text) is None
