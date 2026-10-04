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
