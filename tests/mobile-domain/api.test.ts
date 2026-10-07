import test from "node:test";
import assert from "node:assert/strict";
import {
  createMemoirApi,
  MemoirApiError,
  NdjsonDecoder,
  parseWireJson,
  type FetchTransport,
  type FetchOptions,
} from "../../packages/api-client/src/index.ts";
import type { TurnEvent } from "../../packages/contracts/src/index.ts";
import {
  parseTurnEvent,
  TurnReceiptSchema,
  PrivateDraftSchema,
} from "../../packages/contracts/src/index.ts";
import {
  initialTurnState,
  reduceTurn,
} from "../../packages/memoir-domain/src/index.ts";
const id = "ca68709e-8af3-4fc9-b62d-98bd6a0c1e0c";
function response(
  body: string,
  status = 200,
  headers: Record<string, string> = {},
) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { "Content-Type": "application/json", ...headers },
    text: async () => body,
  };
}
test("API injects current bearer, canonical path, exact command and validates boundaries", async () => {
  const calls: { url: string; init: FetchOptions }[] = [];
  let token = "first";
  const fetch: FetchTransport = async (url, init) => {
    calls.push({ url, init });
    return response(
      '{"project_id":"p","reply":"Saved","conversation_saved":true,"source_sequence":1730000000000000001}',
    );
  };
  const api = createMemoirApi({
    baseUrl: "https://memoir.example/api/v1/memoir",
    fetch,
    getToken: async () => token,
  });
  const result = await api.turn({
    text: "A memory",
    client_turn_id: id,
    project_id: "p",
  });
  token = "rotated";
  await api.turn({ text: "A memory", client_turn_id: id, project_id: "p" });
  assert.equal(
    calls[0]!.url,
    "https://memoir.example/api/v1/memoir/agent/turn",
  );
  assert.equal(calls[1]!.init.headers.Authorization, "Bearer rotated");
  assert.equal(result.source_sequence, "1730000000000000001");
  assert.deepEqual(JSON.parse(calls[0]!.init.body!), {
    text: "A memory",
    client_turn_id: id,
    project_id: "p",
  });
  assert.throws(() => api.turn({ text: "", project_id: "p" }));
  assert.equal(calls.length, 2);
});
test("JSON fallback emits one authoritative result; NDJSON EOF remains provisional", async () => {
  const events: TurnEvent[] = [];
  const api = createMemoirApi({
    baseUrl: "https://memoir.example/api/v1/memoir",
    getToken: async () => "token",
    fetch: async () => response('{"reply":"Saved","conversation_saved":true}'),
  });
  assert.equal(
    (
      await api.streamTurn(
        { text: "hi" },
        { onEvent: (event) => events.push(event) },
      )
    ).terminal,
    "result",
  );
  assert.equal(events.length, 1);
  const chunks = [Buffer.from('{"type":"text_delta","text":"hello"}\n')];
  let cancelled = false;
  const streamApi = createMemoirApi({
    baseUrl: "https://memoir.example/api/v1/memoir",
    getToken: async () => "token",
    fetch: async () => ({
      ...response(""),
      headers: { "Content-Type": "application/x-ndjson" },
      body: {
        getReader: () => ({
          read: async () =>
            chunks.length
              ? { done: false, value: chunks.shift()! }
              : { done: true },
          cancel: async () => {
            cancelled = true;
          },
        }),
      },
    }),
  });
  let state = initialTurnState({
    ownerId: "o",
    projectId: "p",
    clientTurnId: id,
    generation: 1,
  });
  const outcome = await streamApi.streamTurn(
    { text: "hi" },
    {
      onEvent: (event) => {
        state = reduceTurn(state, {
          type: "event",
          context: state.context,
          event,
        });
      },
    },
  );
  assert.equal(outcome.terminal, "eof");
  assert.equal(state.reply, "hello");
  assert.equal(state.committed, false);
  assert.equal(cancelled, true);
});
test("transport never automatically retries an uncertain mutation and redacts raw provider errors", async () => {
  let calls = 0;
  const api = createMemoirApi({
    baseUrl: "https://memoir.example/api/v1/memoir",
    getToken: async () => "token",
    fetch: async () => {
      calls++;
      return response(
        '{"error":{"code":"PROVIDER_SETUP_FAILED","message":"secret source text","retryable":true}}',
        503,
        { "X-Request-ID": "safe-id" },
      );
    },
  });
  await assert.rejects(
    api.turn({ text: "private" }),
    (error) =>
      error instanceof MemoirApiError &&
      error.code === "PROVIDER_SETUP_FAILED" &&
      !JSON.stringify(error).includes("secret"),
  );
  assert.equal(calls, 1);
});
test("unknown additive events are ignored while malformed known events fail validation", () => {
  assert.deepEqual(
    parseTurnEvent({ type: "future_event", data: { anything: true } }),
    { type: "unknown", event_type: "future_event" },
  );
  assert.throws(() =>
    parseTurnEvent({
      type: "conversation_saved",
      data: { reply: "not a receipt" },
    }),
  );
  assert.throws(() =>
    new NdjsonDecoder({ maxEvents: 1 }).push(
      Buffer.from('{"type":"heartbeat"}\n{"type":"heartbeat"}\n'),
    ),
  );
  assert.deepEqual(
    parseWireJson(
      '{"escaped":"\\\"1234567890123456789","integer":1234567890123456789,"float":2.5,"negative":-1234567890123456789}',
    ),
    {
      escaped: '"1234567890123456789',
      integer: "1234567890123456789",
      float: 2.5,
      negative: "-1234567890123456789",
    },
  );
});
test("receipt source acceptance never turns into a saved exchange and private drafts retain server state", () => {
  const receipt = TurnReceiptSchema.parse({
    schema_version: 1,
    client_turn_id: id,
    project_id: "p",
    state: "source_accepted",
    conversation_saved: false,
    server_turn_id: null,
    source_id: "s",
    source_version: "1",
    source_sequence: "1730000000000000001",
    conversation_sequence: null,
    project_ordinal: null,
    narrator_text: "hi",
    reply: null,
    source_status: "active",
    source_processing_state: "pending",
    enrichment_state: "unknown",
    recall_status: {
      rounds_completed: 3,
      free_rounds: 20,
      payment_required: false,
      paid: false,
    },
  });
  const state = initialTurnState({
    ownerId: "o",
    projectId: "p",
    clientTurnId: id,
    generation: 1,
  });
  const next = reduceTurn(state, {
    type: "reconciled",
    context: state.context,
    receipt,
  });
  assert.equal(next.sourceAccepted, true);
  assert.equal(next.committed, false);
  assert.equal(
    PrivateDraftSchema.parse({
      preview: null,
      status: "stale",
      updating: true,
      revision: 3,
      host_authorized: true,
    }).status,
    "stale",
  );
});
test("reconciliation clears a previously displayed reply withheld after source revocation", () => {
  const receipt = TurnReceiptSchema.parse({
    schema_version: 1,
    client_turn_id: id,
    project_id: "p",
    state: "conversation_saved",
    conversation_saved: true,
    server_turn_id: "memory-id",
    source_id: "s",
    source_version: "2",
    source_sequence: "2",
    conversation_sequence: "1",
    project_ordinal: "1",
    narrator_text: null,
    reply: null,
    source_status: "withdrawn",
    source_processing_state: "succeeded",
    enrichment_state: "unknown",
    recall_status: {
      rounds_completed: 1,
      free_rounds: 20,
      payment_required: false,
      paid: false,
    },
  });
  let state = initialTurnState({
    ownerId: "o",
    projectId: "p",
    clientTurnId: id,
    generation: 1,
  });
  state = reduceTurn(state, {
    type: "event",
    context: state.context,
    event: { type: "text_delta", text: "old private reply" },
  });
  state = reduceTurn(state, {
    type: "reconciled",
    context: state.context,
    receipt,
  });
  assert.equal(state.committed, true);
  assert.equal(state.reply, "");
  assert.equal(state.contentUnavailable, true);
  assert.equal(state.savedMemoryId, "memory-id");
});
test("withdrawn uncommitted source blocks queued replay and late events", () => {
  const receipt = TurnReceiptSchema.parse({
    schema_version: 1,
    client_turn_id: id,
    project_id: "p",
    state: "source_accepted",
    conversation_saved: false,
    server_turn_id: null,
    source_id: "s",
    source_version: "2",
    source_sequence: "2",
    conversation_sequence: null,
    project_ordinal: null,
    narrator_text: null,
    reply: null,
    source_status: "withdrawn",
    source_processing_state: "succeeded",
    enrichment_state: "unknown",
    recall_status: {
      rounds_completed: 1,
      free_rounds: 20,
      payment_required: false,
      paid: false,
    },
  });
  const initial = initialTurnState({
    ownerId: "o",
    projectId: "p",
    clientTurnId: id,
    generation: 1,
  });
  const state = reduceTurn(initial, {
    type: "reconciled",
    context: initial.context,
    receipt,
  });
  assert.equal(state.replayBlocked, true);
  assert.equal(state.phase, "rejected");
  assert.equal(state.sourceStatus, "withdrawn");
  assert.equal(
    reduceTurn(state, { type: "queued", context: state.context }),
    state,
  );
  assert.equal(
    reduceTurn(state, {
      type: "event",
      context: state.context,
      event: { type: "text_delta", text: "stale" },
    }),
    state,
  );
});
test("source detail requires exact citation version and validates current authorized source", async () => {
  const calls: string[] = [];
  const api = createMemoirApi({
    baseUrl: "https://memoir.example/api/v1/memoir",
    getToken: async () => "token",
    fetch: async (url) => {
      calls.push(url);
      return response(
        JSON.stringify({
          schema_version: 1,
          id,
          project_id: "p",
          version: "2",
          sequence: "1730000000000000001",
          text: "Current words",
          source_kind: "narrator_chat",
          status: "active",
          language: "en-AU",
          created_at: "2026-10-07T00:00:00Z",
        }),
      );
    },
  });
  assert.equal((await api.sourceDetail("p", id, "2")).version, "2");
  assert.ok(
    calls[0]?.endsWith(`/user/projects/p/sources/${id}?expected_version=2`),
  );
  assert.throws(() => api.sourceDetail("p", id, "9007199254740991000000000"));
});
