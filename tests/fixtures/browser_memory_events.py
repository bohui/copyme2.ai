"""Synthetic canonical event response for the standalone renderer journeys.

The real router/RPC/worker persistence contract is exercised separately by
test_shared_memory_browser.py. These journeys control the public API seam.
"""
from urllib.parse import parse_qs, urlsplit


SCHOOL_QUOTE = "I started school around 1964 in Hobart."


def school_events(route, *, present=True, completed_rounds=1):
    project_id = parse_qs(urlsplit(route.request.url).query)["project_id"][0]
    route.fulfill(json={
        "project_id": project_id,
        "completed_rounds": completed_rounds,
        "events": [{
            "id": "e-school", "revision": 1, "kind": "event",
            "title": "Started school", "place": "Hobart",
            "life_stage": "childhood",
            "temporal": {"expression": "around 1964", "precision": "approximate",
                         "year_start": 1964, "year_end": 1964},
            "source_refs": [{"source_id": "synthetic-school-answer", "version": 1,
                             "quote": SCHOOL_QUOTE}],
        }] if present else [],
        "processing": {"pending_inputs": False},
    })
