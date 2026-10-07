import {
  initialTurnState,
  reduceTurn,
  createTurnOutboxItem,
  assertReplayPayload,
  type TurnState,
  type TurnOutboxItem,
  type PayloadHash,
} from "@memoir/memoir-domain";
import { MemoirApiError, retryDelay, type MemoirApi } from "@memoir/api-client";
import type { TurnInput } from "@memoir/contracts";
import type { Vault } from "./platform/vault";

export interface TurnControllerOptions {
  api: Pick<MemoirApi, "streamTurn" | "turnReceipt">;
  vault: Pick<Vault, "owner" | "listOutbox" | "putOutbox" | "deleteOutbox">;
  ownerId: string;
  hash: PayloadHash;
  now?: () => number;
  random?: () => number;
  onChange: (state: TurnState, item: TurnOutboxItem) => void;
  /** contentUnavailable means refresh history; never re-append original narrator text. */
  onSaved: (item: TurnOutboxItem, reply: string, state: TurnState) => void;
}
export interface SendOptions {
  onQueued?: (item: TurnOutboxItem) => void | Promise<void>;
}
type RunMode = "queued" | "retry" | "check";
interface RunningTurn {
  promise: Promise<void>;
  abort: AbortController;
  payloadHash: string;
  projectId: string;
}

/** Each operation has one durable command. All retries read the latest local row
 * and reconcile server state before a single explicitly requested transmission.
 * No timer/background loop regenerates a reply. */
export class TurnController {
  private generation = 0;
  private alive = true;
  private running = new Map<string, RunningTurn>();
  private enqueuing = new Map<string, Promise<TurnOutboxItem>>();
  private acknowledged = new Set<string>();
  private enqueueTail: Promise<unknown> = Promise.resolve();
  private discarding = new Map<string, Promise<void>>();
  private discarded = new Set<string>();
  private readonly now: () => number;
  constructor(private readonly options: TurnControllerOptions) {
    this.now = options.now ?? Date.now;
    if (options.vault.owner !== options.ownerId)
      throw new Error("Vault account owner mismatch");
  }
  dispose() {
    this.alive = false;
    this.generation++;
    for (const task of this.running.values()) task.abort.abort();
  }
  /** Stop listening, not a server rollback. The durable outbox remains recoverable. */
  cancel(operationId: string) {
    this.running.get(operationId)?.abort.abort();
  }
  /** Call only after the UI's explicit local-discard confirmation. This does not
   * delete server evidence or assert that cancelled generation rolled back. */
  discard(item: TurnOutboxItem): Promise<void> {
    this.assertOwner(item);
    const existing = this.discarding.get(item.operationId);
    if (existing) return existing;
    // Fence new retry/enqueue calls synchronously before awaiting anything. Keep
    // this local tombstone even if cleanup fails; the user can retry discard.
    this.discarded.add(item.operationId);
    const pendingEnqueue = this.enqueuing.get(item.operationId);
    const running = this.running.get(item.operationId);
    running?.abort.abort();
    const work = (async () => {
      await assertReplayPayload(item, item.command, this.options.hash);
      await Promise.allSettled([
        ...(pendingEnqueue ? [pendingEnqueue] : []),
        ...(running ? [running.promise] : []),
      ]);
      this.assertOwner(item);
      const row = (await this.options.vault.listOutbox<TurnOutboxItem>()).find(
        (row) => row.id === item.operationId,
      );
      this.assertOwner(item);
      if (row) {
        this.assertOwner(row.value);
        await assertReplayPayload(row.value, item.command, this.options.hash);
        this.assertOwner(item);
        await this.options.vault.deleteOutbox(item.operationId);
      }
    })();
    this.discarding.set(item.operationId, work);
    return work.finally(() => {
      if (this.discarding.get(item.operationId) === work)
        this.discarding.delete(item.operationId);
    });
  }
  private assertOwner(item?: TurnOutboxItem) {
    if (
      !this.alive ||
      this.options.vault.owner !== this.options.ownerId ||
      (item && item.ownerId !== this.options.ownerId)
    )
      throw new Error("Account changed or outbox owner mismatch");
  }
  async pending() {
    this.assertOwner();
    const rows = await this.options.vault.listOutbox<TurnOutboxItem>();
    this.assertOwner();
    return rows
      .map((row) => row.value)
      .filter(
        (item) =>
          item.ownerId === this.options.ownerId && item.state !== "committed",
      );
  }
  async hasPending(projectId: string): Promise<boolean> {
    return (await this.pending()).some((item) => item.projectId === projectId);
  }
  /** Resolve only after durable storage. The caller can now clear its composer. */
  async enqueue(command: TurnInput): Promise<TurnOutboxItem> {
    this.assertOwner();
    if (!command.project_id || !command.client_turn_id)
      throw new Error("Project and stable turn UUID are required");
    const snapshot = { ...command };
    const operationId = command.client_turn_id;
    if (this.discarded.has(operationId))
      throw new Error("Turn UUID was discarded; create a new logical turn");
    const existing = this.enqueuing.get(operationId);
    if (existing) {
      const item = await existing;
      await assertReplayPayload(item, snapshot, this.options.hash);
      return item;
    }
    const work = this.enqueueTail
      .catch(() => undefined)
      .then(async () => {
        const item = await createTurnOutboxItem({
          ownerId: this.options.ownerId,
          projectId: snapshot.project_id!,
          command: snapshot,
          hash: this.options.hash,
          now: this.now(),
        });
        this.assertOwner(item);
        const rows = await this.options.vault.listOutbox<TurnOutboxItem>();
        const row = rows.find((row) => row.id === operationId);
        this.assertOwner(item);
        if (row) {
          this.assertOwner(row.value);
          await assertReplayPayload(row.value, snapshot, this.options.hash);
          return row.value;
        }
        if (
          rows.some(
            (row) =>
              row.value.ownerId === this.options.ownerId &&
              row.value.projectId === item.projectId &&
              row.value.state !== "committed",
          )
        )
          throw new MemoirApiError(
            "PENDING_TURN_EXISTS",
            409,
            "reconcile",
            false,
          );
        if (this.acknowledged.has(operationId))
          throw new Error(
            "Turn UUID already committed; create a new logical turn",
          );
        await this.options.vault.putOutbox(operationId, item);
        this.assertOwner(item);
        return item;
      });
    this.enqueueTail = work;
    this.enqueuing.set(operationId, work);
    try {
      return await work;
    } finally {
      if (this.enqueuing.get(operationId) === work)
        this.enqueuing.delete(operationId);
    }
  }
  async send(command: TurnInput, options: SendOptions = {}) {
    const item = await this.enqueue(command);
    this.assertOwner(item);
    await options.onQueued?.(item);
    this.assertOwner(item);
    await this.runQueued(item);
  }
  runQueued(item: TurnOutboxItem) {
    return this.start(item, "queued");
  }
  retry(item: TurnOutboxItem) {
    return this.start(item, "retry");
  }
  /** Foreground/restart recovery is read-only on the server; it never resends. */
  check(item: TurnOutboxItem) {
    return this.start(item, "check");
  }
  private async start(item: TurnOutboxItem, mode: RunMode): Promise<void> {
    this.assertOwner(item);
    if (this.discarded.has(item.operationId)) return;
    // Check the caller's immutable body even when a duplicate joins existing work.
    await assertReplayPayload(item, item.command, this.options.hash);
    this.assertOwner(item);
    if (this.discarded.has(item.operationId)) return;
    const duplicate = this.running.get(item.operationId);
    if (duplicate) {
      if (
        duplicate.payloadHash !== item.payloadHash ||
        duplicate.projectId !== item.projectId
      )
        throw new Error("Retry payload changed");
      return mode === "check" ? undefined : duplicate.promise;
    }
    if (this.acknowledged.has(item.operationId)) return;
    const abort = new AbortController();
    const task: RunningTurn = {
      abort,
      promise: Promise.resolve(),
      payloadHash: item.payloadHash,
      projectId: item.projectId,
    };
    // The map is populated before any storage or network await in the run.
    this.running.set(item.operationId, task);
    task.promise = this.execute(item, mode, abort).finally(() => {
      if (this.running.get(item.operationId) === task)
        this.running.delete(item.operationId);
    });
    return task.promise;
  }
  private async execute(
    supplied: TurnOutboxItem,
    mode: RunMode,
    abort: AbortController,
  ): Promise<void> {
    const valid = () =>
      this.alive &&
      !abort.signal.aborted &&
      !this.discarded.has(supplied.operationId) &&
      this.options.vault.owner === this.options.ownerId;
    const row = (await this.options.vault.listOutbox<TurnOutboxItem>()).find(
      (row) => row.id === supplied.operationId,
    );
    if (!valid()) return;
    if (!row) {
      if (this.acknowledged.has(supplied.operationId)) return;
      throw new Error("Durable outbox item missing");
    }
    let item = row.value;
    this.assertOwner(item);
    await assertReplayPayload(item, supplied.command, this.options.hash);
    if (
      !Number.isSafeInteger(item.attempts) ||
      item.attempts < 0 ||
      (item.nextAttemptAt !== null && !Number.isFinite(item.nextAttemptAt))
    )
      throw new Error("Invalid outbox retry metadata");
    if (!valid()) return;
    if (item.state === "committed") {
      this.acknowledged.add(item.operationId);
      return;
    }
    if (
      mode !== "check" &&
      item.nextAttemptAt !== null &&
      item.nextAttemptAt > this.now()
    )
      throw new MemoirApiError(
        "RETRY_NOT_DUE",
        429,
        "retry",
        true,
        undefined,
        item.nextAttemptAt - this.now(),
      );
    const context = {
      ownerId: item.ownerId,
      projectId: item.projectId,
      clientTurnId: item.operationId,
      generation: ++this.generation,
    };
    let state = initialTurnState(context);
    let commitWork: Promise<void> | undefined;
    let commitFailure: unknown;
    const emit = () => {
      if (valid() && context.generation === this.generation)
        this.options.onChange(state, item);
    };
    const persist = async (next: TurnOutboxItem) => {
      if (!valid()) return;
      await this.options.vault.putOutbox(next.operationId, next);
      if (valid()) item = next;
    };
    const commit = () => {
      if (!state.committed || commitWork || !valid()) return;
      const savedState = state;
      commitWork = (async () => {
        const committed = {
          ...item,
          state: "committed" as const,
          nextAttemptAt: null,
          lastErrorCode: null,
        };
        await persist(committed);
        if (!valid()) return;
        this.acknowledged.add(item.operationId);
        this.options.onSaved(item, savedState.reply, savedState);
        // Cleanup failure cannot undo the durable saved state; never retransmit it.
        try {
          if (valid()) await this.options.vault.deleteOutbox(item.operationId);
        } catch {
          /* Reconcile/cleanup a committed row on a later launch. */
        }
      })().catch((error) => {
        commitFailure = error;
      });
    };
    const finishCommit = async () => {
      commit();
      await commitWork;
      if (commitFailure && valid()) {
        state = { ...state, errorCode: "LOCAL_SAVE_UNAVAILABLE" };
        emit();
      }
    };
    try {
      // Any previously attempted operation needs a server read, including a stale
      // caller invoking runQueued instead of retry after an interrupted process.
      if (mode !== "queued" || item.attempts > 0 || item.state !== "queued") {
        const receipt = await this.options.api.turnReceipt(
          item.operationId,
          item.projectId,
          { signal: abort.signal },
        );
        if (!valid()) return;
        if (
          receipt.client_turn_id !== item.operationId ||
          receipt.project_id !== item.projectId
        )
          throw new MemoirApiError("RECEIPT_SCOPE_MISMATCH", 0, "stop", false);
        state = reduceTurn(state, { type: "reconciled", context, receipt });
        const expectedText =
          item.command.conversation_text ?? item.command.text;
        if (
          receipt.narrator_text !== null &&
          receipt.narrator_text !== expectedText
        ) {
          state = state.committed
            ? { ...state, reply: "", contentUnavailable: true }
            : {
                ...state,
                phase: "rejected",
                replayBlocked: true,
                errorCode: "PAYLOAD_CONFLICT",
              };
        }
        emit();
        if (state.committed) {
          await finishCommit();
          return;
        }
        if (state.replayBlocked) {
          await persist({
            ...item,
            state: "rejected",
            lastErrorCode: state.errorCode ?? "SOURCE_CHANGED",
            nextAttemptAt: null,
          });
          emit();
          return;
        }
        if (mode === "check") {
          await persist({
            ...item,
            state:
              item.attempts === 0 && item.state === "queued"
                ? "queued"
                : "uncertain",
          });
          emit();
          return;
        }
      }
      if (!valid()) return;
      await persist({
        ...item,
        state: "sending",
        attempts: item.attempts + 1,
        nextAttemptAt: null,
        lastErrorCode: null,
      });
      if (!valid()) return;
      state = reduceTurn(state, { type: "queued", context });
      emit();
      await this.options.api.streamTurn(item.command, {
        signal: abort.signal,
        requestId: item.operationId,
        onEvent: (event) => {
          if (!valid()) return;
          state = reduceTurn(state, { type: "event", context, event });
          emit();
          // Start durable acknowledgment at the saved boundary, while the transport
          // continues optional enrichment and another logical turn becomes available.
          commit();
        },
      });
      if (!valid()) return;
      state = reduceTurn(state, { type: "eof", context });
      if (state.committed) {
        await finishCommit();
        return;
      }
      await persist({
        ...item,
        state: state.phase === "rejected" ? "rejected" : "uncertain",
        lastErrorCode: state.errorCode ?? null,
      });
      emit();
    } catch (error) {
      if (!valid()) return;
      const failure =
        error instanceof MemoirApiError
          ? error
          : new MemoirApiError(
              "LOCAL_OR_NETWORK_FAILURE",
              0,
              "reconcile",
              false,
            );
      state = reduceTurn(state, { type: "error", context, error: failure });
      if (state.committed) {
        await finishCommit();
        return;
      }
      const delay =
        failure.status === 409
          ? 1000
          : retryDelay(failure, Math.min(Math.max(item.attempts - 1, 0), 3), {
              idempotent: true,
              random: this.options.random,
            });
      const status =
        failure.recovery === "authenticate"
          ? "paused"
          : failure.recovery === "correct" || failure.recovery === "stop"
            ? "rejected"
            : "uncertain";
      await persist({
        ...item,
        state: status,
        lastErrorCode: failure.code,
        nextAttemptAt: delay === null ? null : this.now() + delay,
      });
      emit();
    } finally {
      // A dispatched acknowledgment is bounded local I/O, not continued generation.
      // If disposal happened, its validity checks prevent callback or deletion.
      await commitWork;
    }
  }
}
