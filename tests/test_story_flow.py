import json

from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.store import MemoryStore


class FakeSupabaseUserStorage:
    """External Supabase boundary used by the API contract tests."""

    def __init__(self, *, anonymous: bool = True):
        self.user_id = "00000000-0000-0000-0000-000000000001"
        self.is_anonymous = anonymous
        self._profile = {}
        self._memories = []

    def profile(self):
        return dict(self._profile)

    def save_profile(self, profile):
        self._profile = dict(profile)
        return [self._profile]

    def save_memory(self, text, *, kind="memoir", source_paths=None):
        row = {
            "id": f"memory-{len(self._memories) + 1}",
            "user_id": self.user_id,
            "kind": kind,
            "content": text,
            "source_paths": source_paths or [],
        }
        self._memories.append(row)
        return [row]

    def memories(self):
        return list(reversed(self._memories))


def _client(storage):
    return TestClient(
        create_app(
            MemoryStore(),
            story_storage_factory=lambda authorization: storage,
        )
    )


def _auth_headers():
    return {"Authorization": "Bearer supabase-test-token"}


def _complete_rounds(client):
    for round_number in range(1, 6):
        response = client.post(
            "/v1/story/rounds",
            headers=_auth_headers(),
            json={"round": round_number, "answer": f"A memory from round {round_number}."},
        )
        assert response.status_code == 200
        assert response.json()["rounds_completed"] == round_number


def test_anonymous_story_has_five_rounds_then_requires_identity_link():
    storage = FakeSupabaseUserStorage()
    client = _client(storage)

    initial = client.get("/v1/story/state", headers=_auth_headers())

    assert initial.status_code == 200
    assert initial.json()["rounds_required"] == 5
    assert initial.json()["next_action"] == "answer"

    _complete_rounds(client)

    state = client.get("/v1/story/state", headers=_auth_headers())
    blocked = client.post(
        "/v1/story/rounds",
        headers=_auth_headers(),
        json={"round": 6, "answer": "This answer must not be accepted."},
    )

    assert state.json()["next_action"] == "link_identity"
    assert blocked.status_code == 403
    assert blocked.headers["X-Error-Code"] == "AUTH_REQUIRED"
    assert len(storage._memories) == 5


def test_linked_user_gets_one_free_chapter_but_full_memoir_is_paywalled():
    storage = FakeSupabaseUserStorage()
    client = _client(storage)
    _complete_rounds(client)
    storage.is_anonymous = False

    state = client.get("/v1/story/state", headers=_auth_headers())
    chapter = client.post("/v1/story/free-chapter", headers=_auth_headers())
    full_memoir = client.post("/v1/story/full-memoir", headers=_auth_headers())

    assert state.json()["next_action"] == "free_chapter"
    assert chapter.status_code == 200
    assert chapter.json()["chapter"]["chapter_number"] == 1
    assert full_memoir.status_code == 402
    assert full_memoir.headers["X-Error-Code"] == "PAYMENT_REQUIRED"
    assert json.loads(storage._memories[-1]["content"])["chapter_number"] == 1


def test_user_profile_cannot_self_grant_full_memoir_payment():
    storage = FakeSupabaseUserStorage(anonymous=False)
    storage._profile = {
        "story_flow": {
            "rounds_completed": 5,
            "free_chapter_claimed": True,
            "payment_status": "paid",
        }
    }
    client = _client(storage)

    response = client.post("/v1/story/full-memoir", headers=_auth_headers())

    assert response.status_code == 402
    assert response.headers["X-Error-Code"] == "PAYMENT_REQUIRED"
