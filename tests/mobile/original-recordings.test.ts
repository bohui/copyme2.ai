import assert from "node:assert/strict";
import test from "node:test";
import {
  TurnInputSchema,
  TranscriptionInputSchema,
  TranscriptionSchema,
} from "../../packages/contracts/src/index";
import { canonicalTurnPayload } from "../../packages/memoir-domain/src/outbox";
import {
  editTranscript,
  transcriptTurnFields,
} from "../../apps/mobile/src/platform/media";
const id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const other = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
test("ordered recording identities survive schema validation and distinguish turn retries", () => {
  const turn = {
    text: "Edited words with typed clarification",
    source_kind: "narrator_transcript" as const,
    recording_ids: [id, other],
  };
  assert.deepEqual(TurnInputSchema.parse(turn).recording_ids, [id, other]);
  assert.notEqual(
    canonicalTurnPayload(turn),
    canonicalTurnPayload({ ...turn, recording_ids: [other, id] }),
  );
  assert.throws(() =>
    TurnInputSchema.parse({ ...turn, recording_ids: [id, id] }),
  );
});
test("reference retry is exclusive with complete payload and old results remain schema compatible", () => {
  assert.deepEqual(TranscriptionInputSchema.parse({ recording_id: id }), {
    recording_id: id,
  });
  assert.throws(() =>
    TranscriptionInputSchema.parse({ recording_id: id, audio_base64: "YWJj" }),
  );
  assert.equal(
    TranscriptionSchema.parse({
      text: "old words",
      source: {
        source_kind: "transcript",
        transcription_method: "openai",
        transcription_model: null,
        language: null,
        segments: [],
      },
    }).recording,
    undefined,
  );
});
test("editing dictated text retains recording provenance, owner/project switches cannot use it", () => {
  const draft = {
    text: "ASR words",
    originalText: "ASR words",
    clipId: "local-clip",
    recordingId: id,
    recordingIds: [id],
    ownerId: "owner",
    projectId: "project",
    revision: 0,
    verified: false as const,
    source: {},
  };
  const edited = editTranscript(draft, "Corrected date plus typed additions");
  assert.deepEqual(transcriptTurnFields(edited, "owner", "project"), {
    source_kind: "narrator_transcript",
    recording_ids: [id],
  });
  assert.throws(
    () => transcriptTurnFields(edited, "other", "project"),
    /scope/,
  );
  assert.throws(() => transcriptTurnFields(edited, "owner", "other"), /scope/);
});

test("queued native retries retain ordered recording references and reject another owner", async () => {
  const { createTurnOutboxItem, assertReplayPayload, assertOutboxScope } =
    await import("../../packages/memoir-domain/src/outbox");
  const { createHash } = await import("node:crypto");
  const hash = async (value: string) =>
    createHash("sha256").update(value).digest("hex");
  const command = {
    text: "Edited words and typed clarification",
    project_id: "project",
    client_turn_id: id,
    source_kind: "narrator_transcript" as const,
    recording_ids: [id, other],
  };
  const item = await createTurnOutboxItem({
    ownerId: "owner",
    projectId: "project",
    command,
    hash,
  });
  assert.equal(item.state, "queued");
  assert.deepEqual(JSON.parse(item.payloadJson).recording_ids, [id, other]);
  await assertReplayPayload(item, command, hash);
  await assert.rejects(
    assertReplayPayload(item, { ...command, recording_ids: [other, id] }, hash),
    /Retry payload changed/,
  );
  assert.throws(
    () =>
      assertOutboxScope(
        { ownerId: "other", projectId: "project", environment: "synthetic" },
        item,
      ),
    /scope/,
  );
});

test("safe recording recovery errors retain only an opaque identity and stage", async () => {
  const { mapApiError } = await import("../../packages/api-client/src/errors");
  const result = mapApiError(
    503,
    {
      detail: {
        recording_id: id,
        backend_saved: true,
        private_transcript: "DO_NOT_RETAIN",
        audio_base64: "PRIVATE_BYTES",
      },
    },
    { "X-Error-Code": "RECORDING_TRANSCRIPTION_FAILED" },
  );
  assert.equal(result.recordingId, id);
  assert.equal(result.backendSaved, true);
  assert.ok(!JSON.stringify(result).includes("DO_NOT_RETAIN"));
  assert.ok(!JSON.stringify(result).includes("PRIVATE_BYTES"));
});
