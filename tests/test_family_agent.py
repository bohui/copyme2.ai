import asyncio

from apps.api.codex_runtime import CodexRuntime, build_system_prompt


def test_family_skill_is_present_only_when_the_server_enables_it():
    disabled = build_system_prompt("(none)", family_enabled=False)
    enabled = build_system_prompt("(none)", family_enabled=True)
    assert "MEMORY_SPARK_FAMILY_TREE" not in disabled
    assert "MEMORY_SPARK_AUTHOR_TIMELINE" not in disabled
    assert "MEMORY_SPARK_FAMILY_TREE" in enabled
    assert "MEMORY_SPARK_AUTHOR_TIMELINE" in enabled


def test_paid_family_turn_returns_validated_context_and_strips_the_marker(monkeypatch):
    class Storage:
        user_id = "11111111-1111-4111-8111-111111111111"

        def __init__(self):
            self.saved_session = None
            self.family_document = None

        def acquire_agent_turn_lease(self, token, lease_seconds):
            return True

        def renew_agent_turn_lease(self, token, lease_seconds):
            return True

        def release_agent_turn_lease(self, token):
            return True

        def agent_session(self):
            return None

        def memories(self):
            return []

        def profile(self):
            return {'preferred_language': 'en-AU'}

        def story_entitlement(self):
            return {
                "status": "paid",
                "plan_key": "family_memoir_v1",
                "family_tree": True,
                "timeline": True,
                "stripe_price_id": "price_family_test",
            }

        def family_context(self, project_id):
            assert project_id == "project-family"
            return self.family_document

        def upsert_family_context(self, project_id, document, expected_revision):
            assert project_id == "project-family"
            assert expected_revision == 0
            self.family_document = {**document, "updated_at": "2026-09-26T00:00:00Z"}
            return {"changed": True, "document": self.family_document}

        @staticmethod
        def agent_path(path):
            return path

        def commit_agent_turn(self, token, thread_id, text, source_paths):
            self.saved_session = thread_id
            return {"content": text, "source_paths": source_paths}

        def put_agent_turn_file(self, token, path, content):
            return path

        def save_profile(self, profile):
            return [profile]

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "thread_id": "thread-family",
                "reply": (
                    "Who was with you?\n"
                    "[[MEMORY_SPARK_FAMILY_TREE]]"
                    '{"people":[{"id":"p-mum","name":"Mei"},{"id":"p-me","name":"Avery"}],'
                    '"relationships":[{"from_person_id":"p-mum","to_person_id":"p-me",'
                    '"relationship_type":"parent"}]}'
                    "[[/MEMORY_SPARK_FAMILY_TREE]]\n"
                    "[[MEMORY_SPARK_AUTHOR_TIMELINE]]"
                    '{"timeline":[{"id":"e-school",'
                    '"title":"Started school","date_expression":"around 1964",'
                    '"precision":"approximate","person_ids":["p-me"]}]}'
                    "[[/MEMORY_SPARK_AUTHOR_TIMELINE]]"
                ),
                "artifacts": [],
            }

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, headers, json):
            assert json["family_enabled"] is True
            assert json["project_id"] == "project-family"
            assert json["family_context"] == {}
            return Response()

    monkeypatch.setattr("apps.api.codex_runtime.httpx.AsyncClient", lambda **kwargs: Client())
    monkeypatch.setenv("STRIPE_PRICE_FAMILY", "price_family_test")

    result = asyncio.run(
        CodexRuntime(
            worker_url="http://codex-worker:8766",
            worker_secret="worker-secret",
            model="test-model",
        ).turn(Storage(), "Tell me about your family.", project_id="project-family")
    )

    assert result["reply"] == "Who was with you?"
    assert result["family_context"]["timeline"][0]["precision"] == "approximate"
    assert result["family_context"]["schema_version"] == 2
    assert result["family_context"]["timeline"][0]["kind"] == "event"
    assert "life_periods" not in result["family_context"]
    assert result["family_context_update"]["persisted"] is True
    assert result["family_context_update"]["changed"] is True
    assert result["family_context_update"]["skills"] == ["family_tree", "author_timeline"]
    assert "MEMORY_SPARK_FAMILY_TREE" not in result["memory"]["content"]
    assert "MEMORY_SPARK_AUTHOR_TIMELINE" not in result["memory"]["content"]
