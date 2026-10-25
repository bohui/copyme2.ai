"""Host checks for the composer's separate evidence-to-prose review."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

REVIEW_VERSION = 3
CRAFT_CRITERIA = ('focus', 'scene_craft', 'voice', 'supported_vulnerability',
    'retrospective_reflection', 'transformation', 'reader_resonance', 'fairness')


class ReviewValue(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class ReviewRef(ReviewValue):
    source_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)


class Finding(ReviewValue):
    verdict: Literal['supported', 'unsupported', 'contradicted', 'uncertainty_lost', 'attribution_lost', 'editorial']
    severity: Literal['blocking', 'warning', 'info']
    explanation: str = Field(min_length=1)


class ProseExcerpt(ReviewValue):
    section_id: str = Field(min_length=1)
    field: Literal['text', 'title', 'subtitle', 'caption', 'alt']
    excerpt: str = Field(min_length=1)


class ProseCheck(ProseExcerpt):
    verdict: Literal['supported', 'unsupported', 'contradicted', 'uncertainty_lost', 'attribution_lost']
    source_refs: list[ReviewRef] = Field(max_length=64)
    explanation: str = Field(min_length=1)


class Contribution(ReviewValue):
    source_ref: ReviewRef
    quote: str = Field(min_length=1)
    disposition: Literal['represented', 'deferred']
    prose: list[ProseExcerpt] = Field(max_length=64)
    reason: str = Field(min_length=1)


class CraftProse(ProseExcerpt):
    excerpt: str = Field(min_length=1, max_length=160)


class CraftSource(ReviewValue):
    source_ref: ReviewRef
    excerpt: str = Field(min_length=1, max_length=160)


class CraftRating(ReviewValue):
    criterion: Literal['focus', 'scene_craft', 'voice', 'supported_vulnerability',
        'retrospective_reflection', 'transformation', 'reader_resonance', 'fairness']
    applicability: Literal['applicable', 'not_applicable', 'insufficient_evidence']
    score: int | None = Field(ge=0, le=3)
    confidence: Literal['high', 'medium', 'low']
    confidence_basis: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=300)
    source_evidence: list[CraftSource] = Field(max_length=2)
    prose_evidence: list[CraftProse] = Field(max_length=2)
    suggested_follow_up: str | None = Field(max_length=240)


class CraftReport(ReviewValue):
    rubric_id: Literal['memoir-craft-v1']
    ratings: list[CraftRating] = Field(min_length=8, max_length=8)


class GroundingReview(ReviewValue):
    contract_version: Literal[3]
    ready_for_user_review: bool
    publication_approved: Literal[False]
    findings: list[Finding] = Field(max_length=256)
    prose_checks: list[ProseCheck] = Field(max_length=1024)
    contributions: list[Contribution] = Field(max_length=128)


class Review(GroundingReview):
    craft: CraftReport


def _ref_key(ref):
    return ref['source_id'], str(ref['version']), ref['char_start'], ref['char_end']


def _ref(ref):
    return dict(zip(('source_id', 'version', 'char_start', 'char_end'), _ref_key(ref)))


def review_requirements(request, draft, manuscript):
    """Enumerate exact reader prose and canonical originals, never infer facts."""
    prose = []

    def fields(section_id, value, names, refs):
        for name in names:
            if isinstance(value.get(name), str) and value[name]:
                prose.append(dict(section_id=section_id, field=name, excerpt=value[name],
                    source_refs=[_ref(ref) for ref in refs]))

    if draft.get('title'):
        fields('__draft_title', draft, ('title',), draft['title_source_refs'])
    bodies = [(chapter['id'], chapter) for chapter in manuscript.get('chapters', [])]
    if manuscript['kind'] == 'sample_storyline':
        bodies.append(('sample_storyline', manuscript['storyline']))
    for chapter_id, chapter in bodies:
        fields(chapter_id + '__heading', chapter, ('title', 'subtitle'), chapter['source_refs'])
        for block in chapter['blocks']:
            fields(chapter_id + '__' + block['id'], block, ('text', 'caption', 'alt'), block['source_refs'])
    sources = {(source['id'], str(source['version'])): source for source in request['sources']}
    contributions = {}
    for event in request['events']:
        for ref in event['source_refs']:
            key = _ref_key(ref)
            source = sources[(key[0], key[1])]
            offset = request.get('context', {}).get('source_windows', {}).get(key[0], {}).get('char_start', 0)
            quote = source['text'][key[2]-offset:key[3]-offset]
            if not quote or key[2] < offset or key[3] > offset + len(source['text']):
                raise ValueError('Review requires the complete authorized original span')
            contributions[key] = dict(source_ref=_ref(ref), quote=quote)
    context = request.get('context', {})
    preferences = context.get('preferences', {})
    intent = context.get('editorial_request')
    followups = (request.get('policy', {}).get('max_followup_questions', 0) > 0
        and not preferences.get('excluded_topics') and not preferences.get('paused_topics')
        and not (isinstance(intent, dict) and intent.get('follow_ups_allowed') is False))
    return dict(contract_version=REVIEW_VERSION, prose=prose, contributions=list(contributions.values()),
        craft_context=dict(rubric_id='memoir-craft-v1', criteria=list(CRAFT_CRITERIA),
            stage='formal_draft' if request.get('trigger', {}).get('composition_authorized') else 'partial',
            output_kind=draft['kind'], author_instruction=intent, followups_allowed=bool(followups)))


def review_ready(review):
    if (not isinstance(review, dict) or review.get('ready_for_user_review') is not True
            or review.get('publication_approved') is not False or not isinstance(review.get('findings'), list)):
        return False
    return all(isinstance(finding, dict)
        and finding.get('severity') in ('warning', 'info')
        and finding.get('verdict') in ('supported', 'editorial')
        and isinstance(finding.get('explanation'), str) and finding['explanation'].strip()
        for finding in review['findings'])


def review_errors(review, requirements):
    """Validate witnesses; semantic truth still requires the separate reviewer."""
    try:
        value = GroundingReview.model_validate({key: item for key, item in review.items() if key != 'craft'}
            if isinstance(review, dict) else review).model_dump()
    except ValidationError:
        return ['REVIEW_CONTRACT_REQUIRED']
    errors = []
    if not review_ready(value):
        errors.append('SEMANTIC_REVIEW_BLOCKED')
    expected = {(unit['section_id'], unit['field']): unit for unit in requirements['prose']}
    checks = {(unit['section_id'], unit['field']): unit for unit in value['prose_checks']}
    if len(checks) != len(value['prose_checks']) or set(checks) != set(expected):
        errors.append('PROSE_AUDIT_INCOMPLETE')
    for key, check in checks.items():
        unit = expected.get(key)
        if unit is None:
            continue
        if (check['excerpt'] != unit['excerpt'] or check['verdict'] != 'supported'
                or not check['source_refs'] or not check['explanation'].strip()
                or any(_ref_key(ref) not in {_ref_key(r) for r in unit['source_refs']}
                       for ref in check['source_refs'])):
            errors.append('PROSE_EVIDENCE_FAILED')
    required = {_ref_key(item['source_ref']): item for item in requirements['contributions']}
    covered = {_ref_key(item['source_ref']): item for item in value['contributions']}
    if len(covered) != len(value['contributions']) or set(covered) != set(required):
        errors.append('CONTRIBUTION_AUDIT_INCOMPLETE')
    for key, item in covered.items():
        original = required.get(key)
        if original is None:
            continue
        if item['quote'] != original['quote'] or not item['reason'].strip():
            errors.append('CONTRIBUTION_EVIDENCE_FAILED')
        if item['disposition'] == 'deferred':
            if item['prose']:
                errors.append('DEFERRED_CONTRIBUTION_HAS_PROSE')
            continue
        if not item['prose']:
            errors.append('REPRESENTED_CONTRIBUTION_HAS_NO_PROSE')
        for witness in item['prose']:
            unit = expected.get((witness['section_id'], witness['field']))
            if (unit is None or not witness['excerpt'].strip() or witness['excerpt'] not in unit['excerpt']
                    or not any(_ref_key(ref)[:2] == key[:2]
                        and ref['char_start'] < key[3] and ref['char_end'] > key[2]
                        for ref in unit['source_refs'])):
                errors.append('CONTRIBUTION_PROSE_MISMATCH')
    return list(dict.fromkeys([*errors, *_craft_errors(review.get('craft'), requirements)]))


def _craft_errors(report, requirements):
    """Bind advisory observations; neither a low score nor NA blocks writing."""
    try:
        ratings = CraftReport.model_validate(report).model_dump()['ratings']
    except ValidationError:
        return ['CRAFT_CONTRACT_REQUIRED']
    if {row['criterion'] for row in ratings} != set(CRAFT_CRITERIA):
        return ['CRAFT_CRITERIA_INCOMPLETE']
    errors = []
    units = {(unit['section_id'], unit['field']): unit for unit in requirements['prose']}
    originals = {_ref_key(item['source_ref']): item for item in requirements['contributions']}
    for row in ratings:
        applicable = row['applicability'] == 'applicable'
        if (not row['reason'].strip() or not row['confidence_basis'].strip()
                or applicable and row['score'] is None
                or not applicable and row['score'] is not None
                or applicable and (not row['source_evidence'] or not row['prose_evidence'])):
            errors.append('CRAFT_RATING_INVALID')
        if row['suggested_follow_up'] is not None and (row['applicability'] != 'insufficient_evidence'
                or not row['suggested_follow_up'].strip()
                or requirements.get('craft_context', {}).get('followups_allowed') is not True):
            errors.append('CRAFT_FOLLOWUP_FORBIDDEN')
        for witness in row['source_evidence']:
            original = originals.get(_ref_key(witness['source_ref']))
            if original is None or not witness['excerpt'].strip() or witness['excerpt'] not in original['quote']:
                errors.append('CRAFT_SOURCE_MISMATCH')
        for witness in row['prose_evidence']:
            unit = units.get((witness['section_id'], witness['field']))
            if unit is None or not witness['excerpt'].strip() or witness['excerpt'] not in unit['excerpt']:
                errors.append('CRAFT_PROSE_MISMATCH')
            elif row['source_evidence'] and not any(_ref_key(ref) == _ref_key(source['source_ref'])
                    for ref in unit['source_refs'] for source in row['source_evidence']):
                errors.append('CRAFT_PROSE_MISMATCH')
    return errors
