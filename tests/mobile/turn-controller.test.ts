import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { TurnController } from "../../apps/mobile/src/turn-controller";
import {
  MemoirApiError,
  type MemoirApi,
  type StreamOptions,
  type StreamOutcome,
} from "@memoir/api-client";
import type { TurnInput, TurnReceipt } from "@memoir/contracts";
import type { TurnOutboxItem, TurnState } from "@memoir/memoir-domain";
import type { Vault } from "../../apps/mobile/src/platform/vault";
const command = {
  project_id: "story",
  client_turn_id: "11111111-1111-4111-8111-111111111111",
  text: "hello",
};
const second = {
  ...command,
  client_turn_id: "22222222-2222-4222-8222-222222222222",
  text: "next",
};
const hash = async (value: string) =>
  createHash("sha256").update(value).digest("hex");
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function receipt(overrides: Partial<TurnReceipt> = {}): TurnReceipt {
  return {
    schema_version: 1,
    client_turn_id: command.client_turn_id,
    project_id: "story",
    state: "not_found",
    conversation_saved: false,
    server_turn_id: null,
    source_id: null,
    source_version: null,
    source_sequence: null,
    conversation_sequence: null,
    project_ordinal: null,
    narrator_text: null,
    reply: null,
    source_status: null,
    source_processing_state: null,
    enrichment_state: "unknown",
    recall_status: {
      rounds_completed: 0,
      free_rounds: 20,
      payment_required: false,
      paid: false,
    },
    ...overrides,
  };
}
function setup() {
  const rows = new Map<string, TurnOutboxItem>();
  const writes: string[] = [];
  let now = 1000;
  let putFailure = false;
  const saved: { item: TurnOutboxItem; reply: string; state: TurnState }[] = [];
  const changes: TurnState[] = [];
  let stream = async (
    _command: TurnInput,
    _options: StreamOptions,
  ): Promise<StreamOutcome> => ({ terminal: "eof" });
  let readReceipt = async () => receipt();
  let sends = 0;
  let reads = 0;
  const vault = {
    owner: "user",
    putOutbox: async (id: string, value: unknown) => {
      if (putFailure) throw new Error("disk full");
      rows.set(id, JSON.parse(JSON.stringify(value)) as TurnOutboxItem);
      writes.push(id);
    },
    listOutbox: async () => [...rows].map(([id, value]) => ({ id, value })),
    deleteOutbox: async (id: string) => {
      rows.delete(id);
    },
  } as unknown as Vault;
  const api = {
    streamTurn: async (input: TurnInput, options: StreamOptions) => {
      sends++;
      return stream(input, options);
    },
    turnReceipt: async () => {
      reads++;
      return readReceipt();
    },
  } as unknown as MemoirApi;
  const controller = new TurnController({
    api,
    vault,
    ownerId: "user",
    hash,
    now: () => now,
    random: () => 0,
    onChange: (state) => changes.push(state),
    onSaved: (item, reply, state) => saved.push({ item, reply, state }),
  });
  return {
    controller,
    vault,
    rows,
    writes,
    saved,
    changes,
    setStream: (value: typeof stream) => {
      stream = value;
    },
    setReceipt: (value: typeof readReceipt) => {
      readReceipt = value;
    },
    setNow: (value: number) => {
      now = value;
    },
    failPut: (value: boolean) => {
      putFailure = value;
    },
    counts: () => ({ sends, reads }),
  };
}
test("enqueue is durable before composer-clear callback and never sends when persistence fails", async () => {
  const f = setup();
  f.failPut(true);
  let cleared = false;
  await assert.rejects(
    f.controller.send(command, {
      onQueued: () => {
        cleared = true;
      },
    }),
    /disk full/,
  );
  assert.equal(cleared, false);
  assert.equal(f.counts().sends, 0);
  f.failPut(false);
  const item = await f.controller.enqueue(command);
  assert.equal(f.rows.has(item.operationId), true);
  assert.equal(f.counts().sends, 0);
  await f.controller.runQueued(item);
  assert.equal((await f.controller.pending())[0]?.state, "uncertain");
});
test("uncommitted EOF retries the same immutable payload only after authoritative receipt read", async () => {
  const f = setup();
  await f.controller.send(command);
  const item = (await f.controller.pending())[0]!;
  f.setStream(async (input) => {
    assert.deepEqual(input, command);
    assert.equal(f.counts().reads, 1);
    return { terminal: "eof" };
  });
  await f.controller.retry(item);
  assert.equal(f.counts().sends, 2);
  assert.equal(f.saved.length, 0);
  await assert.rejects(
    f.controller.retry({
      ...item,
      command: { ...item.command, text: "changed" },
    }),
    /payload/i,
  );
});
test("conversation_saved is durably acknowledged before optional enrichment ends", async () => {
  const f = setup();
  const tail = deferred<StreamOutcome>();
  const acknowledged = deferred<void>();
  f.setStream(async (input, options) => {
    options.onEvent({
      type: "conversation_saved",
      data: {
        project_id: "story",
        turn_id: "runtime",
        reply: input.text,
        conversation_saved: true,
      },
    });
    acknowledged.resolve();
    return tail.promise;
  });
  const ongoing = f.controller.send(command);
  await acknowledged.promise;
  for (let n = 0; n < 20 && f.saved.length === 0; n++)
    await new Promise((resolve) => setImmediate(resolve));
  assert.equal(f.saved.length, 1);
  assert.equal(f.saved[0]!.state.committed, true);
  assert.equal((await f.controller.pending()).length, 0);
  f.setStream(async (_input, options) => {
    options.onEvent({
      type: "result",
      data: { reply: "next reply", conversation_saved: true },
    });
    return { terminal: "result" };
  });
  await f.controller.send(second);
  assert.equal(f.saved.length, 2);
  tail.resolve({ terminal: "error" });
  await ongoing;
  assert.equal(f.saved.length, 2);
});
test("duplicate retries share a single reconciliation/send and cannot regenerate committed reply", async () => {
  const f = setup();
  await f.controller.send(command);
  const item = (await f.controller.pending())[0]!;
  const read = deferred<TurnReceipt>();
  f.setReceipt(() => read.promise);
  const first = f.controller.retry(item),
    duplicate = f.controller.retry(item);
  read.resolve(
    receipt({
      state: "conversation_saved",
      conversation_saved: true,
      server_turn_id: "saved",
      reply: "original",
    }),
  );
  await Promise.all([first, duplicate]);
  assert.deepEqual(f.counts(), { sends: 1, reads: 1 });
  assert.equal(f.saved.length, 1);
  assert.equal(f.saved[0]!.reply, "original");
  await f.controller.retry(item);
  assert.equal(f.counts().sends, 1);
});
test("committed withdrawn receipt does not resend and exposes cleared-content state to UI", async () => {
  const f = setup();
  await f.controller.send(command);
  const item = (await f.controller.pending())[0]!;
  f.setReceipt(async () =>
    receipt({
      state: "conversation_saved",
      conversation_saved: true,
      server_turn_id: "saved",
      source_id: "source",
      source_status: "withdrawn",
      source_version: "2",
    }),
  );
  await f.controller.retry(item);
  assert.equal(f.counts().sends, 1);
  assert.equal(f.saved.length, 1);
  assert.equal(f.saved[0]!.reply, "");
  assert.equal(f.saved[0]!.state.contentUnavailable, true);
});
test("withdrawn source acceptance blocks replay; active accepted source has no automatic retry loop", async () => {
  const f = setup();
  await f.controller.send(command);
  let item = (await f.controller.pending())[0]!;
  f.setReceipt(async () =>
    receipt({
      state: "source_accepted",
      source_id: "source",
      source_status: "withdrawn",
      source_version: "2",
    }),
  );
  await f.controller.retry(item);
  assert.equal(f.counts().sends, 1);
  assert.equal(f.rows.get(item.operationId)?.state, "rejected");
  const g = setup();
  await g.controller.send(command);
  item = (await g.controller.pending())[0]!;
  g.setReceipt(async () =>
    receipt({
      state: "source_accepted",
      source_id: "source",
      source_status: "active",
      source_version: "1",
      narrator_text: "hello",
    }),
  );
  await g.controller.retry(item);
  assert.equal(g.counts().sends, 2);
  assert.equal(g.saved.length, 0);
  assert.equal(g.rows.get(item.operationId)?.state, "uncertain");
});
test("401 pauses the durable original and 429 persists Retry-After across stale caller retry", async () => {
  const f = setup();
  f.setStream(async () => {
    throw new MemoirApiError("UNAUTHENTICATED", 401, "authenticate", false);
  });
  await f.controller.send(command);
  assert.equal((await f.controller.pending())[0]?.state, "paused");
  assert.equal(f.saved.length, 0);
  const g = setup();
  g.setStream(async () => {
    throw new MemoirApiError(
      "RATE_LIMITED",
      429,
      "retry",
      true,
      undefined,
      12000,
    );
  });
  await g.controller.send(command);
  const item = (await g.controller.pending())[0]!;
  assert.equal(item.nextAttemptAt, 13000);
  await assert.rejects(
    g.controller.retry({ ...item, nextAttemptAt: null }),
    (error) =>
      error instanceof MemoirApiError && error.code === "RETRY_NOT_DUE",
  );
  assert.equal(g.counts().reads, 0);
  g.setNow(13000);
  g.setReceipt(async () =>
    receipt({
      state: "conversation_saved",
      conversation_saved: true,
      server_turn_id: "saved",
      reply: "original",
    }),
  );
  await g.controller.retry(item);
  assert.equal(g.counts().sends, 1);
});
test("disposed/cancelled ignored transport retains durable outbox and never emits stale callbacks", async () => {
  const f = setup();
  const entered = deferred<StreamOptions>();
  const end = deferred<StreamOutcome>();
  f.setStream(async (_input, options) => {
    entered.resolve(options);
    return end.promise;
  });
  const running = f.controller.send(command);
  const options = await entered.promise;
  const before = f.changes.length;
  f.controller.dispose();
  options.onEvent({
    type: "conversation_saved",
    data: { project_id: "story", reply: "late", conversation_saved: true },
  });
  end.resolve({ terminal: "result" });
  await running;
  assert.equal(f.saved.length, 0);
  assert.equal(f.changes.length, before);
  assert.equal(f.rows.has(command.client_turn_id), true);
  const g = setup();
  const entered2 = deferred<StreamOptions>();
  const end2 = deferred<StreamOutcome>();
  g.setStream(async (_input, opts) => {
    entered2.resolve(opts);
    return end2.promise;
  });
  const running2 = g.controller.send(command);
  const options2 = await entered2.promise;
  g.controller.cancel(command.client_turn_id);
  options2.onEvent({ type: "text_delta", text: "late" });
  end2.resolve({ terminal: "eof" });
  await running2;
  assert.equal(g.saved.length, 0);
  assert.equal(g.rows.has(command.client_turn_id), true);
});
test("cross-owner items and duplicate UUID changed bodies cannot overwrite durable payload", async () => {
  const f = setup();
  const item = await f.controller.enqueue(command);
  await assert.rejects(
    f.controller.runQueued({ ...item, ownerId: "someone-else" }),
    /account|owner/i,
  );
  assert.equal(f.counts().sends, 0);
  await assert.rejects(
    f.controller.enqueue({ ...command, text: "replace" }),
    /payload/i,
  );
  assert.equal(f.rows.get(item.operationId)?.command.text, "hello");
});
test("foreground check reconciles only and never sends pending or accepted source", async () => {
  const f = setup();
  await f.controller.send(command);
  const item = (await f.controller.pending())[0]!;
  await f.controller.check(item);
  assert.deepEqual(f.counts(), { sends: 1, reads: 1 });
  f.setReceipt(async () =>
    receipt({
      state: "source_accepted",
      source_id: "s",
      source_version: "1",
      source_status: "active",
      narrator_text: "hello",
    }),
  );
  await f.controller.check(item);
  assert.deepEqual(f.counts(), { sends: 1, reads: 2 });
  assert.equal(f.saved.length, 0);
  f.setReceipt(async () =>
    receipt({
      state: "conversation_saved",
      conversation_saved: true,
      server_turn_id: "saved",
      reply: "recovered",
    }),
  );
  await f.controller.check(item);
  assert.equal(f.saved[0]!.reply, "recovered");
  assert.equal(f.counts().sends, 1);
});
test("same-project durable pending turn blocks a new logical command, including after restart", async () => {
  const f = setup();
  await f.controller.enqueue(command);
  assert.equal(await f.controller.hasPending("story"), true);
  await assert.rejects(
    f.controller.enqueue(second),
    (error) =>
      error instanceof MemoirApiError && error.code === "PENDING_TURN_EXISTS",
  );
  assert.equal(f.rows.size, 1);
  assert.equal(f.counts().sends, 0);
});
test("accepted server source mismatching immutable command is blocked rather than replayed", async () => {
  const f = setup();
  await f.controller.send(command);
  const item = (await f.controller.pending())[0]!;
  f.setReceipt(async () =>
    receipt({
      state: "source_accepted",
      source_id: "s",
      source_version: "1",
      source_status: "active",
      narrator_text: "another source",
    }),
  );
  await f.controller.retry(item);
  assert.equal(f.counts().sends, 1);
  assert.equal(f.rows.get(item.operationId)?.lastErrorCode, "PAYLOAD_CONFLICT");
});
test("incorrectly scoped receipt is rejected without a model request", async () => {
  const f = setup();
  await f.controller.send(command);
  const item = (await f.controller.pending())[0]!;
  f.setReceipt(async () => receipt({ project_id: "another-project" }));
  await f.controller.retry(item);
  assert.equal(f.counts().sends, 1);
  assert.equal(f.rows.get(item.operationId)?.state, "rejected");
  assert.equal(
    f.rows.get(item.operationId)?.lastErrorCode,
    "RECEIPT_SCOPE_MISMATCH",
  );
});
test("confirmed discard waits for interrupted transport to settle, then removes only local outbox", async () => {
  const f = setup();
  const entered = deferred<StreamOptions>();
  const tail = deferred<StreamOutcome>();
  f.setStream(async (_input, options) => {
    entered.resolve(options);
    return tail.promise;
  });
  const ongoing = f.controller.send(command);
  const options = await entered.promise;
  const item = (await f.controller.pending())[0]!;
  const before = f.changes.length;
  let removed = false;
  const discard = f.controller.discard(item).then(() => {
    removed = true;
  });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(options.signal?.aborted, true);
  assert.equal(removed, false);
  assert.equal(f.rows.has(item.operationId), true);
  options.onEvent({
    type: "conversation_saved",
    data: {
      project_id: "story",
      reply: "late server result",
      conversation_saved: true,
    },
  });
  await f.controller.retry(item);
  assert.equal(f.counts().sends, 1);
  tail.resolve({ terminal: "eof" });
  await Promise.all([ongoing, discard]);
  assert.equal(removed, true);
  assert.equal(f.rows.has(item.operationId), false);
  assert.equal(f.saved.length, 0);
  assert.equal(f.changes.length, before);
  options.onEvent({ type: "text_delta", text: "late after discard" });
  assert.equal(f.changes.length, before);
  assert.deepEqual(f.counts(), { sends: 1, reads: 0 });
  await f.controller.discard(item);
  await f.controller.retry(item);
  assert.equal(f.counts().sends, 1);
  await assert.rejects(f.controller.enqueue(command), /discard/i);
});
test("discard fences an enqueue still committing its durable row before deleting", async () => {
  const f = setup();
  const original = f.vault.putOutbox;
  const entered = deferred<TurnOutboxItem>();
  const commit = deferred<void>();
  f.vault.putOutbox = async (id, value) => {
    entered.resolve(value as TurnOutboxItem);
    await commit.promise;
    await original(id, value);
  };
  const enqueue = f.controller.enqueue(command);
  const item = await entered.promise;
  const discard = f.controller.discard(item);
  commit.resolve();
  await Promise.all([enqueue, discard]);
  assert.equal(f.rows.size, 0);
  assert.equal(f.counts().sends, 0);
});
