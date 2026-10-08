"""Authenticated progressive story acceptance; external model/auth are controlled."""
import asyncio
import json
import sys

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from test_shared_memory_events_postgres import (
    database, attachment_database, private_database, event_database, sql,
    ROOT, OWNER, OTHER, TURN, rpc, deliver_latest,
)
from memoir_postgres_workflow import PostgresRest


@pytest.mark.parametrize("locale", ["en-AU", "zh-CN"])
def test_authenticated_story_saves_scoped_canonical_drafts_at_rounds_five_ten_and_fifteen(sql, tmp_path, monkeypatch, locale):
    from apps.api import agent_routes
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
    from apps.api.memory_event_worker import MemoryEventWorker, MemoirLaneBroker
    from apps.api.story_routes import build_router

    words = {
        "en-AU": ("As a child I started school around 1964.",
                  "At that school I carried a blue bag.",
                  "At that school my teacher was Ms Chen.", "Thanks.", "Tell me more."),
        "zh-CN": ("小时候，我大约在1964年开始上学。",
                  "在那所学校，我背着一个蓝色书包。",
                  "在那所学校，我的老师是陈老师。", "谢谢。", "请继续讲。"),
    }[locale]
    original, detail, teacher, acknowledgement, reply = words
    profile = {"preferred_language": locale, "conversation_language": {
        "locale": locale, "source": "explicit", "revision": 1}}
    PostgresRest(sql, OWNER).storage().save_profile(profile)
    monkeypatch.setenv("MEMORY_SPARK_DISABLE_PRIVDROP", "1")
    monkeypatch.setenv("MEMORY_SPARK_TASK_DB", str(tmp_path / "tasks.sqlite"))

    def storage(authorization):
        if authorization != "Bearer synthetic-author":
            raise HTTPException(401)
        return PostgresRest(sql, OWNER).storage()

    monkeypatch.setattr(agent_routes, "authenticated_storage", storage)
    app = FastAPI()
    app.include_router(agent_routes.router)
    app.include_router(build_router(storage))
    controls = {role: tmp_path / (role + ".json") for role in ("collector", "workspace", "author_timeline", "composer")}
    controls["collector"].write_text(json.dumps({"reply": reply}))
    controls["workspace"].write_text(json.dumps({"reply": {
        "people": [], "relationships": [], "timeline": [], "place_journeys": []}}))

    async def scenario():
        async def readiness(reader, writer):
            writer.close()
            await writer.wait_closed()
        server = await asyncio.start_server(readiness, "127.0.0.1", 0)
        base = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1"
        providers = {role: CodexWorker(home_root=tmp_path / (role + "-homes"), base_url=base,
            command=[sys.executable, str(ROOT / "tests/fixtures/issue6_controlled_app_server.py"), str(control)])
            for role, control in controls.items()}
        worker_app = FastAPI()
        @worker_app.post("/internal/codex/turn")
        async def turn(payload: WorkerTurnInput):
            return await providers[payload.agent_role].turn(payload)
        transport = httpx.ASGITransport(app=worker_app)
        monkeypatch.setattr(agent_routes, "runtime", CodexRuntime(home_root=tmp_path / "api-homes",
            worker_url="http://controlled-worker.invalid", worker_secret="synthetic", worker_transport=transport))
        headers = {"Authorization": "Bearer synthetic-author"}
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://story.test") as client:
                async with httpx.AsyncClient(transport=httpx.MockTransport(PostgresRest(sql, OWNER, service=True).handle)) as db:
                    broker = MemoirLaneBroker(url="http://synthetic.invalid", key="synthetic", client=db)
                    worker = MemoryEventWorker(broker, worker_url="http://controlled-worker.invalid",
                        worker_secret="synthetic", worker_transport=transport)
                    event_id = None
                    source_ids = []
                    for number in range(1, 16):
                        text = {1: original, 6: detail, 11: teacher}.get(number, acknowledgement)
                        response = await client.post("/v1/agent/turn", headers=headers, json={
                            "project_id": "project", "client_turn_id": f"00000000-0000-4000-8000-{number:012d}",
                            "source_kind": "narrator_transcript" if number == 6 else "narrator_chat",
                            "text": text, "language": locale})
                        assert response.status_code == 200, response.text
                        assert response.json()["reply"] == reply
                        view = rpc(sql, "read_user_memory_events", "'project'")
                        assert view["completed_rounds"] == number and len(view["sources"]) == number
                        assert view["sources"][-1]["text"] == text and view["sources"][-1]["language"] == locale
                        assert view["sources"][-1]["kind"] == ("narrator_transcript" if number == 6 else "narrator_chat")
                        if number in (1, 6, 11):
                            source_ids.append(view["sources"][-1]["id"])
                        if number == 4:
                            early = await client.get("/v1/story/private-draft?project_id=project", headers=headers)
                            assert early.status_code == 200 and early.json()["preview"] is None
                        if number % 5:
                            continue
                        source = next(s for s in view["sources"] if s["id"] == source_ids[-1])
                        reference = {"source_id": source["id"], "version": source["version"], "quote": source["text"],
                                     "char_start": 0, "char_end": len(source["text"])}
                        proposal = {"id": "school", "kind": "event", "title": "Started school", "source_refs": [reference]}
                        if event_id is None:
                            proposal.update(life_stage="childhood", stage_evidence=[reference], temporal={
                                "expression": "around 1964" if locale == "en-AU" else "大约在1964年",
                                "precision": "approximate", "year_start": 1964, "year_end": 1964,
                                "basis": [reference]})
                        else:
                            proposal.update(existing_id=event_id, expected_revision=view["events"][0]["revision"])
                        controls["author_timeline"].write_text(json.dumps({"reply": {"events": [proposal]}}, ensure_ascii=False))
                        prose = " ".join(words[:number // 5])
                        controls["composer"].write_text(json.dumps({"mode": "composer", "prose": prose,
                            "title": "Starting school" if locale == "en-AU" else "开始上学",
                            "summary": original, "calls": str(tmp_path / "calls.jsonl")}, ensure_ascii=False))
                        await broker.drain_once()
                        lanes = deliver_latest(sql)
                        assert (await worker.execute_lane(lanes["timeline_lane_id"]))["status"] == "saved"
                        assert (await worker.execute_lane(lanes["composer_lane_id"]))["status"] == "saved"
                        canonical = rpc(sql, "read_user_memory_events", "'project'")
                        event = canonical["events"][0]
                        event_id = event_id or event["id"]
                        assert len(canonical["events"]) == 1 and event["id"] == event_id
                        assert event["revision"] == number // 5 and event["life_stage"] == "childhood"
                        assert event["temporal"]["precision"] == "approximate" and event["temporal"]["year_start"] == 1964
                        assert {ref["source_id"] for ref in event["source_refs"]} == set(source_ids)
                        originals = {s["id"]: s["text"] for s in canonical["sources"]}
                        for ref in event["source_refs"]:
                            assert originals[ref["source_id"]][ref["char_start"]:ref["char_end"]] == ref["quote"]
                        assert canonical["processing"] == {"extracted_through": number, "pending_inputs": 0}
                        saved_response = await client.get("/v1/story/private-draft?project_id=project", headers=headers)
                        assert saved_response.status_code == 200
                        saved = saved_response.json()
                        assert saved["status"] == "ready" and saved["covered_round"] == number and saved["milestone"] == number
                        assert not saved["updating"] and saved["preview"]["text"] == prose
                        assert {id for section in saved["sections"] for id in section["event_ids"]} == {event_id}
                        assert [m["milestone"] for m in saved["milestones"]] == list(range(5, number + 1, 5))
                        assert all(m["state"] == "completed" for m in saved["milestones"])

                    before = rpc(sql, "read_user_memory_events", "'project'")
                    private_before = (await client.get("/v1/story/private-draft?project_id=project", headers=headers)).json()
                    rpc(sql, "accept_user_narrator_source", f"'other-project','{TURN}','A different project memory.'")
                    rpc(sql, "accept_user_narrator_source", f"'project','{TURN}','Another owner memory.'", owner=OTHER)
                    assert rpc(sql, "read_user_memory_events", "'project'") == before
                    assert (await client.get("/v1/story/private-draft?project_id=project", headers=headers)).json() == private_before
                    assert rpc(sql, "read_user_memory_events", "'project'", owner=OTHER)["events"] == []
                    assert rpc(sql, "read_user_memory_events", "'other-project'")["events"] == []
                    assert (await client.get("/v1/story/events?project_id=project", headers=headers)).status_code == 403
                    assert (await client.get("/v1/story/private-draft?project_id=project")).status_code == 401
                    state = (await client.get("/v1/story/state", headers=headers)).json()
                    assert state["recall_status"]["rounds_completed"] == 15
                    assert not state["recall_status"]["payment_required"] and not state["family_features_enabled"]
        finally:
            server.close()
            await server.wait_closed()
    asyncio.run(scenario())
