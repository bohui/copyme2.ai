import pytest

from apps.api.profile_intake import (
    apply_explicit_story_stage,
    extract_profile_updates,
    merge_profile_updates,
    validate_profile_updates,
)


def test_extracts_and_removes_explicit_profile_context():
    visible, updates = extract_profile_updates(
        "That gives us a beautiful place to begin.\n"
        "[[MEMORY_SPARK_PROFILE]]"
        '{"name":"Mina","birth_year":1974,"childhood_place":"Geelong",'
        '"story_focus":{"who":"my grandmother","where":"the back garden",'
        '"when":"the late 1980s","what":"summer afternoons"}}'
        "[[/MEMORY_SPARK_PROFILE]]"
    )

    assert visible == "That gives us a beautiful place to begin."
    assert updates == {
        "name": "Mina",
        "birth_year": 1974,
        "childhood_place": "Geelong",
        "story_focus": {
            "who": "my grandmother",
            "where": "the back garden",
            "when": "the late 1980s",
            "what": "summer afternoons",
        },
    }


def test_profile_merge_preserves_existing_focus_and_discards_invalid_values():
    merged = merge_profile_updates(
        {"name": "Mina", "story_focus": {"who": "my grandmother", "when": "the 1980s"}},
        {"birth_year": 1974, "story_focus": {"where": "Geelong", "what": "summer afternoons", "who": 17}},
    )

    assert merged == {
        "name": "Mina",
        "birth_year": 1974,
        "story_focus": {
            "who": "my grandmother",
            "where": "Geelong",
            "when": "the 1980s",
            "what": "summer afternoons",
        },
    }


def test_profile_validation_drops_unbounded_birth_year():
    assert validate_profile_updates({"name": "Mina", "birth_year": 1799}) == {"name": "Mina"}


def test_explicit_chinese_thirty_plus_cue_overrides_only_the_story_stage():
    assert apply_explicit_story_stage(
        "三十岁以后，我把阳台改成小花园。",
        {"story_focus": {"who": "我", "what": "把阳台改成小花园", "life_stage": "young_adulthood"}},
    ) == {
        "story_focus": {
            "who": "我",
            "what": "把阳台改成小花园",
            "life_stage": "midlife",
        }
    }


def test_explicit_story_stage_guard_does_not_infer_without_the_cue():
    assert apply_explicit_story_stage(
        "我后来把阳台改成小花园。",
        {"story_focus": {"life_stage": "young_adulthood"}},
    ) == {"story_focus": {"life_stage": "young_adulthood"}}


def test_explicit_story_stage_guard_respects_author_correction_and_subject_scope():
    assert apply_explicit_story_stage(
        "不是三十岁以后，是小时候，我把阳台改成小花园。",
        {"story_focus": {"life_stage": "childhood", "what": "把阳台改成小花园"}},
    ) == {"story_focus": {"life_stage": "childhood", "what": "把阳台改成小花园"}}
    assert apply_explicit_story_stage(
        "妈妈三十岁以后开始工作，那时我五岁。",
        {"story_focus": {"life_stage": "childhood", "when": "我五岁"}},
    ) == {"story_focus": {"life_stage": "childhood", "when": "我五岁"}}


def test_explicit_story_stage_guard_does_not_promote_relative_age_before_author_age():
    text = "三十岁以后，我姐姐开始工作，那时我五岁。"
    updates = apply_explicit_story_stage(
        text,
        {"story_focus": {"life_stage": "midlife", "when": "我五岁"}},
    )
    assert updates == {"story_focus": {"when": "我五岁"}}
    assert merge_profile_updates(
        {"story_focus": {"life_stage": "childhood"}}, updates
    ) == {"story_focus": {"life_stage": "childhood", "when": "我五岁"}}


def test_later_chinese_correction_overrides_an_earlier_midlife_statement():
    text = "三十岁以后，我开始工作。更正：其实是我姐姐三十岁以后开始工作。"
    assert apply_explicit_story_stage(
        text, {"story_focus": {"life_stage": "midlife"}}
    ) is None


@pytest.mark.parametrize("text", [
    "我姐姐三十岁以后开始工作，那时我五岁。",
    "我哥哥三十岁以后开始工作，那时我五岁。",
    "妈妈三十岁以后开始工作，那时我五岁。",
    "不是三十岁以后，是小时候，我在院子里玩耍。",
])
def test_explicit_story_stage_guard_drops_only_an_ambiguous_midlife_override(text):
    updates = {"story_focus": {"life_stage": "midlife", "when": "我五岁"}}

    # A model-supplied midlife value is not evidence when the cue belongs to a
    # relative or is explicitly negated. Removing just that value lets the
    # previously validated stage survive the normal profile merge.
    assert apply_explicit_story_stage(text, updates) == {
        "story_focus": {"when": "我五岁"}
    }
    assert merge_profile_updates(
        {"story_focus": {"life_stage": "childhood"}},
        apply_explicit_story_stage(text, updates),
    ) == {"story_focus": {"life_stage": "childhood", "when": "我五岁"}}


def test_explicit_story_stage_guard_accepts_first_person_age_subject():
    assert apply_explicit_story_stage(
        "我三十岁以后开始照顾孩子。",
        {"story_focus": {"life_stage": "young_adulthood"}},
    ) == {"story_focus": {"life_stage": "midlife"}}


def test_story_stage_guard_does_not_promote_a_date_only_correction_to_midlife():
    updates = apply_explicit_story_stage(
        "更正：我大约一九九三年去大理，二〇〇二年前后改工作室，两处都保持大概表达。",
        {"story_focus": {"life_stage": "midlife", "when": "大约一九九三年"}},
    )
    assert updates == {"story_focus": {"when": "大约一九九三年"}}
    assert merge_profile_updates(
        {"story_focus": {"life_stage": "later_life"}}, updates
    ) == {"story_focus": {"life_stage": "later_life", "when": "大约一九九三年"}}


def test_story_stage_guard_accepts_author_age_inside_a_correction():
    assert apply_explicit_story_stage(
        "更正：我三十岁以后开始照顾孩子。",
        {"story_focus": {"life_stage": "young_adulthood"}},
    ) == {"story_focus": {"life_stage": "midlife"}}


def test_language_updates_are_validated_and_preserve_other_profile_fields():
    assert merge_profile_updates({'name': '慧博'}, {'preferred_language': 'zh-CN'}) == {
        'name': '慧博', 'preferred_language': 'zh-CN',
    }
    for value in ('invalid', '', None, {}, []):
        assert validate_profile_updates({'preferred_language': value}) is None


def test_extracts_and_removes_legacy_html_profile_context():
    visible, updates = extract_profile_updates(
        '慧博，你好。\n'
        '<!-- profile: {"who":"慧博","when":"1983年4月",'
        '"where":"河南省开封市中心医院（出生地）；现居悉尼","what":""} -->'
    )

    assert visible == '慧博，你好。'
    assert updates == {
        'name': '慧博',
        'birth_date_expression': '1983年4月',
        'birth_place': '河南省开封市中心医院（出生地）；现居悉尼',
    }
