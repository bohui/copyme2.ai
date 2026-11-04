"""Reset coordination without changing a database or live Langfuse data."""

from pathlib import Path
import shlex
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import reset_database as module


def page(trace_ids, cursor=None, project_id="memoir-project"):
    return SimpleNamespace(
        data=[SimpleNamespace(trace_id=trace_id, project_id=project_id) for trace_id in trace_ids],
        meta=SimpleNamespace(cursor=cursor),
    )


def score_page(score_ids, cursor=None, project_id="memoir-project"):
    return SimpleNamespace(
        data=[SimpleNamespace(id=score_id, project_id=project_id, subject=None) for score_id in score_ids],
        meta=SimpleNamespace(cursor=cursor),
    )


@pytest.fixture
def client(monkeypatch):
    client = Mock()
    client.api.projects.get.return_value.data = [SimpleNamespace(id="memoir-project", name="memior")]
    client.api.observations.get_many.return_value = page(["trace-a"])
    client.api.scores_v3.get_many_v3.return_value = score_page([])
    monkeypatch.setattr(module, "prompt_client", lambda _: client)
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://fixture.invalid/disposable")
    monkeypatch.setattr(module.shutil, "which", lambda _: "/fixture/supabase")
    return client


def test_snapshot_covers_all_pages_and_deduplicates_traces(client):
    client.api.observations.get_many.side_effect = [
        page(["trace-b", "trace-a"], "next"), page([], "continue"), page(["trace-b", "trace-c"]),
    ]
    client.api.scores_v3.get_many_v3.side_effect = [
        score_page(["score-b", "score-a"], "next-score"), score_page([], "continue-score"),
        score_page(["score-b", "score-c"]),
    ]
    assert module.langfuse_history(client) == ("memior", ["trace-a", "trace-b", "trace-c"],
                                             ["score-a", "score-b", "score-c"])
    requests = [call.kwargs for call in client.api.observations.get_many.call_args_list]
    assert [request["cursor"] for request in requests] == [None, "next", "continue"]
    assert all(request["from_start_time"].year == 1970 for request in requests)
    assert len({request["to_start_time"] for request in requests}) == 1
    score_requests = [call.kwargs for call in client.api.scores_v3.get_many_v3.call_args_list]
    assert [request["cursor"] for request in score_requests] == [None, "next-score", "continue-score"]
    assert all(request["fields"] == "subject" for request in score_requests)
    assert all(request["from_timestamp"] == requests[0]["from_start_time"] for request in score_requests)
    assert all(request["to_timestamp"] == requests[0]["to_start_time"] for request in score_requests)


@pytest.mark.parametrize("projects", [[], ["another-project"], ["memoir", "another-project"]])
def test_rejects_keys_for_another_project_or_multiple_projects(client, projects):
    client.api.projects.get.return_value.data = [SimpleNamespace(id=name, name=name) for name in projects]
    with pytest.raises(ValueError, match="Memoir project only"):
        module.langfuse_history(client)
    client.api.observations.get_many.assert_not_called()


def test_rejects_out_of_scope_observations(client):
    client.api.observations.get_many.return_value = page(["other-trace"], project_id="other-project")
    with pytest.raises(ValueError, match="outside the reset scope"):
        module.langfuse_history(client)


def test_rejects_out_of_scope_scores(client):
    client.api.scores_v3.get_many_v3.return_value = score_page(["other-score"], project_id="other-project")
    with pytest.raises(ValueError, match="score outside the reset scope"):
        module.langfuse_history(client)


@pytest.mark.parametrize("kind", ["observations", "scores"])
def test_rejects_repeated_cursor(client, kind):
    if kind == "observations":
        client.api.observations.get_many.return_value = page(["trace-a"], "same")
    else:
        client.api.scores_v3.get_many_v3.return_value = score_page(["score-a"], "same")
    with pytest.raises(ValueError, match="pagination did not advance"):
        module.langfuse_history(client)


def test_preflights_before_supabase_and_deletes_in_batches_afterward(client, monkeypatch, capsys):
    client.api.observations.get_many.return_value = page([f"trace-{i:04}" for i in range(1001)])

    def delete_traces(*, trace_ids):
        # Langfuse starts one parallel audit-log transaction for each trace.
        if len(trace_ids) > 100:
            raise RuntimeError("Transaction API error: Unable to start a transaction in the given time.")

    client.api.trace.delete_multiple.side_effect = delete_traces

    def run(command, *, check):
        client.api.projects.get.assert_called_once()
        client.api.observations.get_many.assert_called_once()
        client.api.scores_v3.get_many_v3.assert_called_once()
        client.api.trace.delete_multiple.assert_not_called()
        client.api.legacy.score_v1.delete.assert_not_called()
        assert check is True
        assert command == ["supabase", "db", "reset", "--db-url",
                           "postgresql://fixture.invalid/disposable", "--no-seed", "--yes"]

    monkeypatch.setattr(module.subprocess, "run", run)
    module.reset_database(include_langfuse=True, credential_file=Path("credentials.env"))
    batches = [call.kwargs["trace_ids"] for call in client.api.trace.delete_multiple.call_args_list]
    assert [len(batch) for batch in batches] == [100] * 10 + [1]
    assert sorted(trace_id for batch in batches for trace_id in batch) == [
        f"trace-{i:04}" for i in range(1001)
    ]
    client.shutdown.assert_called_once()
    assert "submitted 1001 traces" in capsys.readouterr().out
    assert not client.api.prompts.method_calls
    assert not client.api.datasets.method_calls
    assert not client.api.dataset_items.method_calls
    assert not client.api.projects.delete.called


def test_scores_without_traces_are_cleared_without_touching_datasets(client, monkeypatch):
    client.api.observations.get_many.return_value = page([])
    response = score_page(["session-score", "experiment-score"])
    response.data[0].subject = SimpleNamespace(kind="session", id="session-id")
    response.data[1].subject = SimpleNamespace(kind="experiment", id="experiment-id")
    client.api.scores_v3.get_many_v3.return_value = response
    monkeypatch.setattr(module.subprocess, "run", Mock())
    module.reset_database(include_langfuse=True, credential_file=Path("credentials.env"))
    assert [call.kwargs["score_id"] for call in client.api.legacy.score_v1.delete.call_args_list] == [
        "experiment-score", "session-score",
    ]
    client.api.trace.delete_multiple.assert_not_called()
    assert not client.api.datasets.method_calls


def test_linked_scores_use_trace_cascades_including_traces_missing_observations(client, monkeypatch):
    response = score_page(["trace-score", "observation-score"])
    response.data[0].subject = SimpleNamespace(kind="trace", id="score-only-trace")
    response.data[1].subject = SimpleNamespace(kind="observation", id="observation-id", trace_id="trace-a")
    client.api.scores_v3.get_many_v3.return_value = response
    monkeypatch.setattr(module.subprocess, "run", Mock())
    module.reset_database(include_langfuse=True, credential_file=Path("credentials.env"))
    client.api.trace.delete_multiple.assert_called_once_with(trace_ids=["score-only-trace", "trace-a"])
    client.api.legacy.score_v1.delete.assert_not_called()


def test_linked_score_missing_its_trace_stops_preflight(client):
    response = score_page(["observation-score"])
    response.data[0].subject = SimpleNamespace(kind="observation", id="observation-id", trace_id=None)
    client.api.scores_v3.get_many_v3.return_value = response
    with pytest.raises(ValueError, match="without its owning trace"):
        module.langfuse_history(client)


def test_standalone_scores_are_deleted_before_traces(client, monkeypatch):
    client.api.scores_v3.get_many_v3.return_value = score_page(["standalone-score"])
    monkeypatch.setattr(module.subprocess, "run", Mock())

    def delete_traces(**kwargs):
        client.api.legacy.score_v1.delete.assert_called_once_with(score_id="standalone-score")

    client.api.trace.delete_multiple.side_effect = delete_traces
    module.reset_database(include_langfuse=True, credential_file=Path("credentials.env"))


def test_false_does_not_need_langfuse_credentials_or_connect(client, monkeypatch):
    monkeypatch.setattr(module, "prompt_client", lambda _: pytest.fail("Langfuse was contacted"))
    run = Mock()
    monkeypatch.setattr(module.subprocess, "run", run)
    module.reset_database(include_langfuse=False, credential_file=Path("missing.env"))
    run.assert_called_once()
    client.shutdown.assert_not_called()


@pytest.mark.parametrize("kind", ["observations", "scores"])
def test_preflight_failure_leaves_supabase_untouched(client, monkeypatch, kind):
    if kind == "observations":
        client.api.observations.get_many.side_effect = RuntimeError("unavailable")
    else:
        client.api.scores_v3.get_many_v3.side_effect = RuntimeError("unavailable")
    run = Mock()
    monkeypatch.setattr(module.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="Supabase was not reset"):
        module.reset_database(include_langfuse=True, credential_file=Path("credentials.env"))
    run.assert_not_called()
    client.api.trace.delete_multiple.assert_not_called()
    client.api.legacy.score_v1.delete.assert_not_called()
    client.shutdown.assert_called_once()


def test_failed_supabase_reset_does_not_delete_traces(client, monkeypatch):
    monkeypatch.setattr(module.subprocess, "run", Mock(side_effect=subprocess.CalledProcessError(1, "supabase")))
    with pytest.raises(RuntimeError, match="Langfuse history was not deleted"):
        module.reset_database(include_langfuse=True, credential_file=Path("credentials.env"))
    client.api.trace.delete_multiple.assert_not_called()
    client.api.legacy.score_v1.delete.assert_not_called()
    client.shutdown.assert_called_once()


@pytest.mark.parametrize("kind", ["traces", "scores"])
def test_deletion_failure_reports_partial_reset(client, monkeypatch, kind):
    monkeypatch.setattr(module.subprocess, "run", Mock())
    if kind == "traces":
        client.api.trace.delete_multiple.side_effect = RuntimeError("unavailable")
    else:
        client.api.scores_v3.get_many_v3.return_value = score_page(["score-a"])
        client.api.legacy.score_v1.delete.side_effect = RuntimeError("unavailable")
    with pytest.raises(RuntimeError, match="Supabase was reset.*cleanup may be partial"):
        module.reset_database(include_langfuse=True, credential_file=Path("credentials.env"))
    client.shutdown.assert_called_once()


@pytest.mark.parametrize("arguments, expected", [([], True), (["--include-langfuse", "true"], True),
                                               (["--include-langfuse", "false"], False)])
def test_cli_defaults_to_langfuse_and_accepts_opt_out(monkeypatch, arguments, expected):
    reset = Mock()
    monkeypatch.setattr(module, "reset_database", reset)
    monkeypatch.setattr(module.sys, "argv", ["reset_database.py", *arguments])
    assert module.main() == 0
    assert reset.call_args.kwargs["include_langfuse"] is expected


def test_invalid_boolean_cannot_start_reset(monkeypatch):
    reset = Mock()
    monkeypatch.setattr(module, "reset_database", reset)
    monkeypatch.setattr(module.sys, "argv", ["reset_database.py", "--include-langfuse", "typo"])
    with pytest.raises(SystemExit):
        module.main()
    reset.assert_not_called()


@pytest.mark.parametrize("arguments, expected", [([], "true"), (["include-langfuse=false"], "false")])
def test_make_forwards_parameter_and_keeps_backend_lock(arguments, expected):
    result = subprocess.run(["make", "--no-print-directory", "-n", "db-reset", *arguments],
                            cwd=module.ROOT, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    command = shlex.split(result.stdout.splitlines()[0])
    assert command[1:3] == ["scripts/backend_operation_lock.py", "--"]
    assert Path(command[3]).name == "make"
    assert command[4:] == ["--no-print-directory", "_db-reset"]
    assert f'--include-langfuse "{expected}"' in result.stdout
