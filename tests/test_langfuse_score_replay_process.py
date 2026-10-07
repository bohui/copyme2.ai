"""Offline transport regressions, not durable Langfuse service acceptance."""

import json
from pathlib import Path
import subprocess
import sys


MODULE = Path(__file__).resolve().parents[1] / "apps/api/trajectory_evaluation.py"

# Each invocation loads the production publisher in a new interpreter. Only
# its SDK transport and publication clock are controlled; no server is used.
PUBLISH_RETAINED_PAYLOAD = r'''
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import socket
import sys

def no_network(*args, **kwargs):
    raise AssertionError("This replay regression must remain offline")

socket.socket.connect = no_network
socket.socket.connect_ex = no_network
socket.create_connection = no_network
spec = importlib.util.spec_from_file_location("replay_publisher", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
publication_clock = datetime.fromisoformat(sys.argv[3])

class PublicationClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return publication_clock.astimezone(tz) if tz else publication_clock.replace(tzinfo=None)

module.datetime = PublicationClock

class Observation:
    trace_id = "synthetic-run-trace"
    id = "synthetic-run-observation"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def update(self, **kwargs):
        pass

class CapturingClient:
    def __init__(self):
        self.scores = []

    def start_as_current_observation(self, **kwargs):
        return Observation()

    def create_score(self, **kwargs):
        timestamp = kwargs.get("timestamp", publication_clock)
        self.scores.append({**kwargs, "timestamp": timestamp.astimezone(timezone.utc).isoformat()})

    def flush(self):
        pass

retained = json.loads(Path(sys.argv[2]).read_text())
client = CapturingClient()
publisher = module.LangfusePublisher(client)
with publisher.case(name="offline-replay", task={"synthetic": True},
                    correlation=retained["correlation"]) as sink:
    sink.publish(retained["trajectory"], retained["scores"])
publisher.flush()
print(json.dumps(client.scores, sort_keys=True))
'''


def test_retained_scores_keep_identity_and_utc_date_across_process_restarts(tmp_path):
    retained = tmp_path / "synthetic-retained-trajectory.json"
    retained.write_text(json.dumps({
        "correlation": {
            "run_id": "synthetic-replay-run",
            "case_id": "synthetic-replay-case",
            "round_id": "001",
            "variant": "baseline",
            "evaluator_version": "synthetic-rubric/1",
        },
        "trajectory": {
            # Local Oct 6 is UTC Oct 5. Keep millisecond precision as well.
            "started_at": "2026-10-06T00:30:00.063+10:00",
            "steps": [{
                "step_id": "step-0001",
                "trace_id": "synthetic-worker-trace",
                "observation_id": "synthetic-worker-observation",
            }],
            "final": {"status": "completed"},
        },
        "scores": [
            {"name": "synthetic_run_quality", "value": 1},
            {"name": "synthetic_step_quality", "value": 1, "step_id": "step-0001"},
        ],
    }))
    before = retained.read_bytes()
    publications = []
    for publication_clock in (
        "2026-10-05T23:59:59+00:00",
        "2026-10-06T00:00:01+00:00",
        "2026-10-07T12:00:00+00:00",
    ):
        process = subprocess.run(
            [sys.executable, "-I", "-c", PUBLISH_RETAINED_PAYLOAD,
             str(MODULE), str(retained), publication_clock],
            cwd=tmp_path,
            # Do not pass credentials or service settings to the subprocess.
            env={},
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        publications.append(json.loads(process.stdout))

    assert retained.read_bytes() == before
    assert all(len(publication) == 2 for publication in publications)
    assert publications[0] == publications[1] == publications[2]
    run_score, step_score = publications[0]
    assert len({run_score["score_id"], step_score["score_id"]}) == 2
    for score in publications[0]:
        assert len(score["score_id"]) == 64
        assert score["timestamp"] == "2026-10-05T14:30:00.063000+00:00"
        assert score["data_type"] == "NUMERIC"
        assert score["value"] == 1
    assert (run_score["trace_id"], run_score["observation_id"]) == (
        "synthetic-run-trace", "synthetic-run-observation",
    )
    assert (step_score["trace_id"], step_score["observation_id"]) == (
        "synthetic-worker-trace", "synthetic-worker-observation",
    )
