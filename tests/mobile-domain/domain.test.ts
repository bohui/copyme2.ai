import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  NdjsonDecoder,
  mapApiError,
  retryDelay,
  parseWireJson,
} from "../../packages/api-client/src/index.ts";
import {
  initialTurnState,
  reduceTurn,
  compareDecimalSequences,
  formatDateExpression,
  createTurnOutboxItem,
  assertReplayPayload,
  resolveDeepLink,
} from "../../packages/memoir-domain/src/index.ts";
import type { TurnEvent } from "../../packages/contracts/src/index.ts";
import type { TurnState } from "../../packages/memoir-domain/src/index.ts";
import {
  TurnInputSchema,
  CollectionUpdateSchema,
} from "../../packages/contracts/src/index.ts";
const context = {
  ownerId: "owner",
  projectId: "project",
  clientTurnId: "ca68709e-8af3-4fc9-b62d-98bd6a0c1e0c",
  generation: 1,
};
const event = (state: TurnState, value: TurnEvent, ctx = context) =>
  reduceTurn(state, { type: "event", context: ctx, event: value });
const data = {
  turn_id: "server-turn",
  project_id: "project",
  reply: "记忆",
  source_sequence: "1730000000000000001",
};
test("NDJSON decodes every single-byte split, CRLF, and a final newline-free record", () => {
  const decoder = new NdjsonDecoder();
  const result = [];
  for (const byte of Buffer.from(
    '{"type":"text_delta","text":"童年的记忆🌏"}\r\n{"type":"heartbeat"}',
  ))
    result.push(...decoder.push(Uint8Array.of(byte)));
  result.push(...decoder.finish());
  assert.deepEqual(result, [
    { type: "text_delta", text: "童年的记忆🌏" },
    { type: "heartbeat" },
  ]);
});
test("NDJSON is bounded and fails closed for corrupt UTF-8 / JSON", () => {
  assert.throws(
    () => new NdjsonDecoder({ maxLineBytes: 8 }).push(Buffer.from("123456789")),
    /limit/i,
  );
  assert.throws(
    () => new NdjsonDecoder().push(Uint8Array.from([0xc0, 0xaf, 10])),
    /UTF-8/i,
  );
  assert.throws(
    () => new NdjsonDecoder().push(Buffer.from("{bad}\n")),
    /JSON/i,
  );
});
test("lossless transport preserves nanosecond sequences before JSON Number conversion", () => {
  assert.equal(
    (
      parseWireJson(
        '{"source_sequence":1730000000000000001,"text":"1234567890123456789"}',
      ) as { source_sequence: string }
    ).source_sequence,
    "1730000000000000001",
  );
  assert.equal(
    compareDecimalSequences("1730000000000000001", "1730000000000000002"),
    -1,
  );
  assert.equal(compareDecimalSequences("00012", 12), 0);
  assert.throws(
    () => compareDecimalSequences(1730000000000000001, "2"),
    /safe|decimal/i,
  );
  assert.throws(() => compareDecimalSequences("1e20", "2"), /decimal/i);
});
test("reply_complete and uncommitted EOF never claim account save", () => {
  let s = event(initialTurnState(context), { type: "text_delta", text: "记" });
  s = event(s, { type: "reply_complete", data });
  assert.equal(s.replyComplete, true);
  assert.equal(s.committed, false);
  s = reduceTurn(s, { type: "eof", context });
  assert.equal(s.phase, "uncertain");
  assert.equal(s.reply, "记忆");
  assert.equal(s.committed, false);
});
test("conversation_saved is durable through duplicate and failed later enrichment", () => {
  let s = event(initialTurnState(context), {
    type: "conversation_saved",
    data: { ...data, conversation_saved: true },
  });
  s = event(s, {
    type: "conversation_saved",
    data: { ...data, conversation_saved: true },
  });
  assert.equal(s.committed, true);
  assert.equal(s.enrichment, "pending");
  s = event(s, {
    type: "workspace_error",
    data: { turn_id: "server-turn", project_id: "project" },
  });
  s = event(s, { type: "result", data: { ...data, place_journey: null } });
  assert.equal(s.committed, true);
  assert.equal(s.enrichment, "failed");
  assert.equal(reduceTurn(s, { type: "eof", context }).committed, true);
});
test("events are fenced by owner, project, local attempt and server turn", () => {
  const s = event(initialTurnState(context), { type: "reply_complete", data });
  for (const ctx of [
    { ...context, ownerId: "other" },
    { ...context, projectId: "other" },
    { ...context, clientTurnId: "other" },
    { ...context, generation: 2 },
  ])
    assert.equal(event(s, { type: "text_delta", text: "wrong" }, ctx), s);
  assert.equal(
    event(s, {
      type: "conversation_saved",
      data: { ...data, turn_id: "old", conversation_saved: true },
    }),
    s,
  );
  assert.equal(
    event(s, { type: "workspace_update", data: { project_id: "other" } }),
    s,
  );
});
test("401 pauses, 409 reconciles, 429 honors Retry-After and 422 never retries", () => {
  assert.equal(mapApiError(401, {}).recovery, "authenticate");
  assert.equal(mapApiError(409, {}).recovery, "reconcile");
  const error = mapApiError(
    429,
    { error: { code: "RATE_LIMITED", retryable: true } },
    { "Retry-After": "12" },
  );
  assert.equal(
    retryDelay(error, 0, { idempotent: true, random: () => 0 }),
    12000,
  );
  assert.equal(retryDelay(error, 0, { idempotent: false }), null);
  assert.equal(
    retryDelay(mapApiError(422, { error: { retryable: true } }), 0, {
      idempotent: true,
    }),
    null,
  );
  assert.equal(
    mapApiError(
      409,
      { error: { code: "EVENT_REVISION_CONFLICT" } },
      { "X-Request-ID": "r" },
    ).requestId,
    "r",
  );
});
test("stable outbox payload survives restart; changed replay is rejected", async () => {
  const command = {
    text: "我的童年",
    project_id: "project",
    client_turn_id: context.clientTurnId,
  };
  const hash = async (text: string) =>
    createHash("sha256").update(text).digest("hex");
  const item = await createTurnOutboxItem({
    ownerId: "owner",
    projectId: "project",
    command,
    hash,
    now: 123,
  });
  assert.equal(item.operationId, context.clientTurnId);
  assert.equal(item.attempts, 0);
  await assertReplayPayload(JSON.parse(JSON.stringify(item)), command, hash);
  await assert.rejects(
    assertReplayPayload(item, { ...command, text: "different" }, hash),
    /payload/i,
  );
  assert.ok(!JSON.stringify(item).includes("bearer"));
});
test("uncertain dates remain uncertain; collection confirmation validates all stages", () => {
  assert.equal(
    formatDateExpression("the late 1960s", "en-AU"),
    "the late 1960s",
  );
  assert.equal(formatDateExpression("1976-02-31", "zh-CN"), "1976-02-31");
  assert.equal(
    TurnInputSchema.safeParse({ text: "hello", project_id: "../other" })
      .success,
    false,
  );
  assert.equal(
    CollectionUpdateSchema.safeParse({
      expected_revision: 1,
      confirm_ready: true,
      periods: {},
    }).success,
    false,
  );
});
test("deep links allow only declared host and routes; payment return is only a refresh hint", () => {
  const options = { httpsHosts: ["memoir.example"], scheme: "memoir" };
  assert.deepEqual(
    resolveDeepLink("https://memoir.example/projects/my-project", options),
    { kind: "project", projectId: "my-project" },
  );
  assert.deepEqual(
    resolveDeepLink("memoir://payment/return?session_id=cs_123", options),
    { kind: "payment-return" },
  );
  for (const raw of [
    "file:///private/story",
    "javascript:alert(1)",
    "https://evil.example/projects/x",
    "https://memoir.example@evil.example/projects/x",
    "https://memoir.example/projects/..%2Fsecret",
    "memoir://projects/x?access_token=secret",
    "https://memoir.example/projects/x#secret",
  ])
    assert.equal(resolveDeepLink(raw, options), null);
});
