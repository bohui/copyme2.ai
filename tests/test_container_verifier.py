from scripts.verify_container_stack import header_value


def test_header_value_is_case_insensitive():
    assert header_value({"x-api-namespace": "memoir"}, "X-API-Namespace") == "memoir"
