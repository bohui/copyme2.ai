import json
import logging
from uuid import UUID

from apps.api.codex_worker_service import WorkerTurnInput
from apps.api.diagnostics import failure_class, log_diagnostic, new_request_id


def test_request_ids_are_bounded_and_failure_classes_are_stable():
    assert new_request_id("diag:test-1") == "diag:test-1"
    generated = new_request_id("bad id with spaces")
    assert len(generated) == 36
    assert failure_class(status_code=504) == "timeout"
    assert failure_class(status_code=502) == "upstream_unavailable"


def test_diagnostic_log_allowlist_excludes_private_values(caplog):
    logger = logging.getLogger("tests.diagnostics")
    with caplog.at_level(logging.INFO, logger="tests.diagnostics"):
        log_diagnostic(
            logger,
            "synthetic_failure",
            "diag-test",
            component="memoir.test",
            status="failed",
            failure_class="timeout",
            prompt="private storyteller text",
            reply="private model reply",
        )
    record = json.loads(caplog.records[0].message.split(" ", 1)[1])
    assert record == {
        "component": "memoir.test",
        "event": "synthetic_failure",
        "failure_class": "timeout",
        "request_id": "diag-test",
        "status": "failed",
    }


def test_worker_input_accepts_only_bounded_diagnostic_id():
    payload = WorkerTurnInput(
        user_id=UUID(int=1),
        text="synthetic",
        diagnostic_request_id="diag-worker-1",
    )
    assert payload.diagnostic_request_id == "diag-worker-1"
