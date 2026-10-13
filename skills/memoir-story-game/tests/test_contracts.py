"""Synthetic public-boundary checks. No provider, live memoir or renderer is used."""
import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('story_game_validation', ROOT / 'scripts' / 'validate.py')
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.request = json.loads((ROOT / 'tests/fixtures/request.json').read_text())
        self.candidate = json.loads((ROOT / 'tests/fixtures/candidate.json').read_text())

    def rebind(self):
        """Synthetic host review only; never imitates real permission authentication."""
        self.candidate['request_digest'] = v.digest(self.request)
        self.candidate['review']['candidate_digest'] = v.candidate_digest(self.candidate)

    def check(self, current=True):
        return v.validate(self.request, self.candidate, self.request if current else None)

    def blocked(self, code):
        result = self.check()
        self.assertEqual(result['status'], 'blocked')
        self.assertIn(code, result['codes'])

    def test_complete_synthetic_two_scene_two_npc_packet_passes(self):
        self.assertEqual(self.check(), {'status': 'valid_offline', 'codes': []})
        self.assertEqual(self.candidate['game'], json.loads((ROOT / 'tests/fixtures/game.json').read_text()))

    def test_schemas_are_valid_draft_2020_12(self):
        for schema in v.SCHEMAS.values():
            Draft202012Validator.check_schema(schema)

    def test_shape_is_necessary_but_not_sufficient(self):
        for phase in ('comfort', 'explore'):
            with self.subTest(phase=phase):
                self.request['phase']['phase'] = phase
                self.blocked('SHAPE_REQUIRED')
        self.request['phase']['phase'] = 'shape'
        self.request['completion'] = None
        self.blocked('COMPLETION_AUTHORITY_REQUIRED')

    def test_no_paused_or_invented_completion_flag(self):
        self.request['phase']['phase'] = 'paused'
        self.blocked('REQUEST_SCHEMA')
        self.request['phase']['phase'] = 'shape'
        self.request['storytelling_complete'] = True
        self.blocked('REQUEST_SCHEMA')

    def test_preview_cannot_admit_a_game(self):
        for kind in ('sample_chapter', 'sample_storyline'):
            with self.subTest(kind=kind):
                self.request['manuscript']['kind'] = kind
                self.blocked('FORMAL_MANUSCRIPT_REQUIRED')

    def test_completion_requires_all_exact_chapter_revisions(self):
        self.request['completion']['chapter_coverage'].pop()
        self.blocked('COMPLETION_COVERAGE')

    def test_completion_requires_successful_validation_and_no_pending_work(self):
        for key, value in [('validation_passed', False), ('pending_count', 1), ('blocking_count', 1)]:
            with self.subTest(key=key):
                original = self.request['completion'][key]
                self.request['completion'][key] = value
                self.blocked('COMPLETION_VALIDATION')
                self.request['completion'][key] = original

    def test_completion_cannot_bind_an_old_manuscript(self):
        self.request['completion']['manuscript_revision'] = 2
        self.blocked('COMPLETION_BINDING')

    def test_separate_adaptation_consent_is_required(self):
        self.request['consent'] = None
        self.blocked('ADAPTATION_CONSENT_REQUIRED')

    def test_composition_permission_is_not_adaptation(self):
        self.request['consent']['purpose'] = 'composition'
        self.blocked('REQUEST_SCHEMA')

    def test_revoked_and_stale_consent_block(self):
        self.request['consent']['status'] = 'revoked'
        self.blocked('ADAPTATION_CONSENT_INVALID')
        self.request['consent']['status'] = 'active'
        self.request['consent']['policy_epoch'] += 1
        self.blocked('ADAPTATION_CONSENT_INVALID')

    def test_modified_original_or_manuscript_fails_digest(self):
        self.request['evidence'][0]['text'] += ' altered'
        self.blocked('SOURCE_MANIFEST_DIGEST')
        self.request['manuscript']['chapters'][0]['text'] += ' altered'
        self.blocked('MANUSCRIPT_DIGEST')

    def test_generated_or_revoked_evidence_cannot_ground_text(self):
        for field, value in [('role', 'assistant'), ('status', 'revoked'), ('adaptation_allowed', False)]:
            with self.subTest(field=field):
                old = self.request['evidence'][0][field]
                self.request['evidence'][0][field] = value
                self.blocked('EVIDENCE_PERMISSION_OR_LINEAGE')
                self.request['evidence'][0][field] = old

    def add_unused_evidence(self, **changes):
        source = {**copy.deepcopy(self.request['evidence'][0]), 'id': 'synthetic-unused-source', **changes}
        self.request['evidence'].append(source)
        self.request['source_manifest_digest'] = v.digest(self.request['evidence'])
        self.request['completion']['source_manifest_digest'] = self.request['source_manifest_digest']
        self.rebind()

    def assert_unused_evidence_blocked(self, **changes):
        self.add_unused_evidence(**changes)
        self.assertTrue(v.schema_valid('request', self.request))
        self.assertTrue(v.schema_valid('candidate', self.candidate))
        self.assertEqual(self.check(), {'status': 'blocked', 'codes': ['EVIDENCE_PERMISSION_OR_LINEAGE']})

    def test_unused_revoked_evidence_is_rejected_with_rebound_hashes(self):
        self.assert_unused_evidence_blocked(status='revoked')

    def test_unused_superseded_evidence_is_rejected_with_rebound_hashes(self):
        self.assert_unused_evidence_blocked(status='superseded')

    def test_unused_denied_evidence_is_rejected_with_rebound_hashes(self):
        self.assert_unused_evidence_blocked(adaptation_allowed=False)

    def test_unused_assistant_evidence_is_rejected_with_rebound_hashes(self):
        self.assert_unused_evidence_blocked(role='assistant')

    def test_unused_contributor_evidence_is_rejected_with_rebound_hashes(self):
        self.assert_unused_evidence_blocked(role='contributor')

    def test_unused_evidence_outside_selected_manuscript_is_rejected_with_rebound_hashes(self):
        self.assert_unused_evidence_blocked(chapter_id='outside-selected-manuscript')

    def test_unused_authorized_evidence_in_selected_manuscript_remains_valid(self):
        self.add_unused_evidence()
        self.assertEqual(self.check(), {'status': 'valid_offline', 'codes': []})

    def test_source_version_and_manuscript_span_are_bound(self):
        self.request['approved_lines'][0]['evidence'][0]['version'] = 2
        self.blocked('EVIDENCE_PERMISSION_OR_LINEAGE')
        self.request['approved_lines'][0]['manuscript']['revision'] = 2
        self.blocked('MANUSCRIPT_SPAN')

    def test_direct_quote_must_match_both_sources(self):
        self.request['approved_lines'][0]['text'] = 'An invented title'
        self.blocked('EVIDENCE_QUOTE')
        self.blocked('MANUSCRIPT_QUOTE')

    def test_out_of_range_original_span_fails(self):
        self.request['approved_lines'][0]['evidence'][0]['end'] = 60000
        self.blocked('EVIDENCE_SPAN')

    def test_unsupported_dialogue_is_not_saved_by_a_fresh_author_review(self):
        self.candidate['game']['texts'][-1]['text'] = 'I secretly became mayor.'
        self.rebind()
        self.blocked('UNAPPROVED_TEXT')

    def test_every_factual_line_needs_a_server_approved_mapping(self):
        self.candidate['grounding'].pop()
        self.rebind()
        self.blocked('GROUNDING_COVERAGE')

    def test_aliases_must_resolve_to_the_reviewed_person(self):
        self.candidate['identities'][0]['person_id'] = 'person-rowan'
        self.rebind()
        self.blocked('NPC_ALIAS_BINDING')

    def test_reviewed_dialogue_cannot_be_reassigned_to_another_npc(self):
        a, b = self.candidate['game']['npcs']
        a['dialogue_text_ids'], b['dialogue_text_ids'] = b['dialogue_text_ids'], a['dialogue_text_ids']
        self.rebind()
        self.blocked('NPC_DIALOGUE_BINDING')

    def test_a_person_mention_is_not_permission_for_that_npc_to_present_a_line(self):
        self.request['approved_lines'][-1]['person_ids'].append('person-cedar')
        a, b = self.candidate['game']['npcs']
        a['dialogue_text_ids'], b['dialogue_text_ids'] = b['dialogue_text_ids'], a['dialogue_text_ids']
        self.rebind()
        self.blocked('NPC_DIALOGUE_BINDING')

    def test_server_uuid_cannot_be_reused_as_browser_npc_id(self):
        canonical = '77777777-7777-4777-8777-777777777777'
        person = self.request['people'][0]
        old_id = person['id']
        person['id'] = canonical
        for line in self.request['approved_lines']:
            line['person_ids'] = [canonical if key == old_id else key for key in line['person_ids']]
            if line['npc_person_id'] == old_id:
                line['npc_person_id'] = canonical
        self.candidate['identities'][0].update(person_id=canonical, npc_id=canonical)
        self.candidate['game']['npcs'][0]['id'] = canonical
        self.rebind()
        self.blocked('CANONICAL_ID_LEAK')

    def test_reviewed_plain_prose_with_colon_is_allowed(self):
        text = 'I remember: I repaired a stool with Rowan.'
        line = self.request['approved_lines'][-1]
        line.update(text=text, mode='reviewed_paraphrase', review_receipt_id='synthetic-paraphrase-review')
        self.candidate['game']['texts'][-1]['text'] = text
        self.rebind()
        self.assertEqual(self.check(), {'status': 'valid_offline', 'codes': []})

    def test_minors_and_unknown_age_need_specific_permission(self):
        for age in ('minor', 'unknown'):
            with self.subTest(age=age):
                self.request['people'][0]['age_category'] = age
                self.blocked('PERSON_SPECIFIC_PERMISSION')

    def test_specific_person_permission_is_subject_and_epoch_bound(self):
        person = self.request['people'][0]
        person['age_category'] = 'minor'
        person['specific_permission'] = {'receipt_id': 'synthetic-specific', 'purpose': 'game_adaptation',
                                         'policy_epoch': 1, 'subject_id': person['id']}
        self.rebind()
        self.assertEqual(self.check()['status'], 'valid_offline')
        person['specific_permission']['subject_id'] = 'someone-else'
        self.blocked('PERSON_SPECIFIC_PERMISSION')

    def test_sensitive_fact_requires_its_own_permission(self):
        self.request['approved_lines'][-1]['sensitive'] = True
        self.blocked('SENSITIVE_PERMISSION')

    def test_denied_person_blocks_even_with_generic_art(self):
        self.request['people'][0]['adaptation_allowed'] = False
        self.blocked('PERSON_PERMISSION')

    def test_author_review_is_required_and_binds_exact_content(self):
        review = self.candidate['review']
        self.candidate['review'] = None
        self.blocked('AUTHOR_REVIEW_REQUIRED')
        self.candidate['review'] = review
        self.candidate['game']['npcs'][0]['x'] += 10
        self.blocked('AUTHOR_REVIEW_BINDING')

    def test_delivery_requires_current_authority(self):
        self.assertIn('CURRENT_AUTHORITY_REQUIRED', self.check(current=False)['codes'])

    def test_correction_revocation_consent_phase_and_fence_races_block(self):
        mutations = [lambda r: r.update(correction_epoch=1), lambda r: r.update(revocation_epoch=1),
                     lambda r: r['consent'].update(revision=2), lambda r: r['phase'].update(phase='explore'),
                     lambda r: r['job'].update(fence=2), lambda r: r['job'].update(expected_artifact_revision=1),
                     lambda r: r['manuscript'].update(revision=2), lambda r: r.update(policy_epoch=2)]
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index):
                current = copy.deepcopy(self.request)
                mutate(current)
                result = v.validate(self.request, self.candidate, current)
                self.assertEqual(result['status'], 'blocked')
                self.assertIn('STALE_AUTHORITY_OR_FENCE', result['codes'])

    def test_replay_key_is_stable_but_lease_takeover_cannot_commit_old_output(self):
        current = copy.deepcopy(self.request)
        self.assertEqual(v.idempotency_key(current), v.idempotency_key(self.request))
        current['job']['fence'] += 1
        self.assertEqual(v.idempotency_key(current), v.idempotency_key(self.request))
        self.assertIn('STALE_AUTHORITY_OR_FENCE', v.validate(self.request, self.candidate, current)['codes'])
        current['correction_epoch'] += 1
        self.assertNotEqual(v.idempotency_key(current), v.idempotency_key(self.request))

    def test_browser_schema_rejects_evidence_authority_code_and_privacy_fields(self):
        for field in ('source_id', 'transcript', 'evidence', 'consent', 'private', 'html', 'javascript', 'url'):
            with self.subTest(field=field):
                game = copy.deepcopy(self.candidate['game'])
                game['npcs'][0][field] = 'never deliver'
                self.assertFalse(v.schema_valid('game', game))

    def test_browser_text_rejects_markup_and_remote_urls(self):
        for text in ('<script>alert(1)</script>', 'https://example.com', '//example.com', 'javascript:alert(1)'):
            with self.subTest(text=text):
                self.candidate['game']['texts'][0]['text'] = text
                self.rebind()
                self.assertEqual(self.check()['status'], 'blocked')

    def test_unknown_asset_and_path_traversal_fail_closed(self):
        self.request['assets'] = self.request['assets'][:1]
        self.rebind()
        self.blocked('ASSET_NOT_ALLOWLISTED')
        self.request['assets'][0]['path'] = 'assets/memoir-story-game/../private.png'
        self.blocked('REQUEST_SCHEMA')

    def test_private_audience_and_fixed_renderer_only(self):
        self.candidate['game']['audience'] = 'public'
        self.blocked('CANDIDATE_SCHEMA')
        self.candidate['game']['audience'] = 'private'
        self.candidate['game']['renderer'] = 'generated-js'
        self.blocked('CANDIDATE_SCHEMA')

    def test_disconnected_scene_or_unsafe_spawn_fails(self):
        self.candidate['game']['scenes'][0]['right'] = None
        self.rebind()
        self.blocked('DISCONNECTED_SCENES')
        self.candidate['game']['scenes'][0]['spawn_x'] = 3000
        self.rebind()
        self.blocked('SPAWN_BOUNDS')

    def test_nonreciprocal_scene_transition_fails(self):
        self.candidate['game']['scenes'][1]['left'] = None
        self.rebind()
        self.blocked('SCENE_CONTINUITY')

    def test_duplicate_ids_and_hidden_text_are_rejected(self):
        self.candidate['game']['texts'].append(copy.deepcopy(self.candidate['game']['texts'][0]))
        self.rebind()
        self.blocked('DUPLICATE_BROWSER_ID')
        self.candidate['game']['texts'][-1]['id'] = 'abcdef00-0000-4000-8000-000000000001'
        self.rebind()
        self.blocked('TEXT_REFERENCE_OR_HIDDEN_TEXT')

    def test_input_parser_rejects_ambiguous_json_and_diagnostics_are_sanitized(self):
        for value in ('{"secret":"private-source","secret":"other"}', '{"secret":NaN}'):
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'bad.json'
                path.write_text(value)
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/validate.py'), '--request', str(path),
                                         '--candidate', str(path)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(json.loads(result.stdout), {'status': 'blocked', 'codes': ['INVALID_INPUT']})
                self.assertNotIn('private-source', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
