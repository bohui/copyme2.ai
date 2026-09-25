from uuid import UUID

from fastapi.testclient import TestClient

from apps.api.codex_worker_service import CodexWorker, app


def test_worker_allocates_stable_distinct_os_identities(tmp_path):
    worker = CodexWorker(home_root=tmp_path)
    first = worker._uid_for(str(UUID("11111111-1111-4111-8111-111111111111")))
    second = worker._uid_for(str(UUID("22222222-2222-4222-8222-222222222222")))

    assert first == worker._uid_for("11111111-1111-4111-8111-111111111111")
    assert first != second
    assert 20000 <= first < 60000
    assert 20000 <= second < 60000


def test_worker_home_permissions_separate_sibling_homes(monkeypatch, tmp_path):
    monkeypatch.setattr("apps.api.codex_worker_service.os.chown", lambda path, uid, gid: None)
    tmp_path.chmod(0o711)
    worker = CodexWorker(home_root=tmp_path)

    home = worker._home("11111111-1111-4111-8111-111111111111", 20000)

    assert tmp_path.stat().st_mode & 0o777 == 0o711
    assert home.stat().st_mode & 0o777 == 0o700
    assert (home / "config.toml").stat().st_mode & 0o777 == 0o600


def test_worker_endpoint_requires_private_secret(monkeypatch):
    monkeypatch.setenv("MEMORY_SPARK_CODEX_WORKER_SECRET", "test-secret")
    client = TestClient(app)

    response = client.post(
        "/internal/codex/turn",
        json={
            "user_id": "11111111-1111-4111-8111-111111111111",
            "text": "hello",
        },
    )

    assert response.status_code == 401
