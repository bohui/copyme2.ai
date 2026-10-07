import type {
  TurnEvent,
  TurnReceipt,
  RecallStatus,
  ProgressStep,
} from "@memoir/contracts";
import { compareDecimalSequences } from "./values";
export interface TurnContext {
  ownerId: string;
  projectId: string;
  clientTurnId: string;
  generation: number;
}
export type TurnPhase =
  | "draft"
  | "queued"
  | "admitted"
  | "receiving"
  | "conversation_committed"
  | "complete"
  | "uncertain"
  | "rejected"
  | "paused"
  | "cancelled";
export interface TurnState {
  context: TurnContext;
  phase: TurnPhase;
  reply: string;
  replyComplete: boolean;
  committed: boolean;
  enrichment: "idle" | "pending" | "complete" | "failed";
  serverTurnId?: string;
  savedMemoryId?: string;
  recallStatus?: RecallStatus | null;
  workspace: Record<string, unknown>;
  placePreview?: Record<string, unknown>;
  workspaceSequence?: string;
  progress: ProgressStep[];
  errorCode?: string;
  sourceAccepted: boolean;
  contentUnavailable: boolean;
  replayBlocked: boolean;
  sourceStatus?: string | null;
}
export interface TurnFailure {
  code: string;
  recovery?: string;
}
export type TurnAction =
  | { type: "event"; context: TurnContext; event: TurnEvent }
  | { type: "queued" | "eof" | "cancel"; context: TurnContext }
  | { type: "error"; context: TurnContext; error: TurnFailure }
  | { type: "reconciled"; context: TurnContext; receipt: TurnReceipt };
export function sameTurnContext(a: TurnContext, b: TurnContext): boolean {
  return (
    a.ownerId === b.ownerId &&
    a.projectId === b.projectId &&
    a.clientTurnId === b.clientTurnId &&
    a.generation === b.generation
  );
}
export function initialTurnState(context: TurnContext): TurnState {
  return {
    context: { ...context },
    phase: "draft",
    reply: "",
    replyComplete: false,
    committed: false,
    enrichment: "idle",
    workspace: {},
    progress: [],
    sourceAccepted: false,
    contentUnavailable: false,
    replayBlocked: false,
  };
}
function finishUncertain(state: TurnState, errorCode?: string): TurnState {
  if (state.replayBlocked) return state;
  if (state.committed)
    return {
      ...state,
      phase:
        state.enrichment === "complete" || state.enrichment === "failed"
          ? "complete"
          : "conversation_committed",
      ...(errorCode ? { errorCode } : {}),
    };
  return { ...state, phase: "uncertain", ...(errorCode ? { errorCode } : {}) };
}
/** Pure reducer. A displayed answer is provisional until an authoritative commit.
 * Every network callback carries the immutable local scope captured at admission.
 * A stream runtime turn_id differs from a receipt's durable server_turn_id.
 */
export function reduceTurn(state: TurnState, action: TurnAction): TurnState {
  if (!sameTurnContext(state.context, action.context)) return state;
  if (action.type === "queued")
    return state.committed || state.replayBlocked
      ? state
      : { ...state, phase: "queued", errorCode: undefined };
  if (action.type === "eof") return finishUncertain(state);
  if (action.type === "cancel")
    return state.committed
      ? state
      : {
          ...state,
          phase:
            state.phase === "draft" || state.phase === "queued"
              ? "cancelled"
              : "uncertain",
          errorCode: "REQUEST_CANCELLED",
        };
  if (action.type === "error") {
    if (state.committed)
      return {
        ...state,
        enrichment: "failed",
        phase: "complete",
        errorCode: action.error.code,
      };
    return {
      ...state,
      phase:
        action.error.recovery === "authenticate"
          ? "paused"
          : action.error.recovery === "correct" ||
              action.error.recovery === "stop"
            ? "rejected"
            : "uncertain",
      errorCode: action.error.code,
    };
  }
  if (action.type === "reconciled") {
    const receipt = action.receipt;
    if (
      receipt.project_id !== state.context.projectId ||
      receipt.client_turn_id !== state.context.clientTurnId
    )
      return state;
    const sourceChanged =
      receipt.source_status === "withdrawn" ||
      (receipt.source_version !== null &&
        compareDecimalSequences(receipt.source_version, "1") > 0);
    if (sourceChanged)
      return {
        ...state,
        phase: receipt.conversation_saved
          ? "conversation_committed"
          : "rejected",
        reply: receipt.reply ?? "",
        replyComplete: true,
        committed: receipt.conversation_saved,
        sourceAccepted: !!receipt.source_id,
        contentUnavailable: receipt.reply === null,
        replayBlocked: true,
        sourceStatus: receipt.source_status,
        savedMemoryId: receipt.server_turn_id ?? undefined,
        recallStatus: receipt.recall_status,
        workspace: {},
        placePreview: undefined,
        errorCode:
          receipt.source_status === "withdrawn"
            ? "SOURCE_WITHDRAWN"
            : "SOURCE_CHANGED",
      };
    if (receipt.state === "conversation_saved" && receipt.conversation_saved)
      return {
        ...state,
        phase: "conversation_committed",
        reply: receipt.reply ?? "",
        replyComplete: true,
        committed: true,
        sourceAccepted: !!receipt.source_id,
        sourceStatus: receipt.source_status,
        contentUnavailable: receipt.reply === null,
        savedMemoryId: receipt.server_turn_id ?? undefined,
        recallStatus: receipt.recall_status,
        enrichment: state.enrichment === "idle" ? "pending" : state.enrichment,
        errorCode: undefined,
      };
    if (state.committed) return state;
    return {
      ...state,
      phase: "uncertain",
      sourceAccepted: receipt.state === "source_accepted",
      sourceStatus: receipt.source_status,
      recallStatus: receipt.recall_status,
    };
  }
  if (action.type !== "event" || state.replayBlocked) return state;
  const event = action.event;
  if (event.type === "unknown") return state;
  const data = (
    "data" in event && event.data && typeof event.data === "object"
      ? event.data
      : undefined
  ) as Record<string, unknown> | undefined;
  const project =
    event.type === "progress" ? event.project_id : data?.project_id;
  const turnId = event.type === "progress" ? event.turn_id : data?.turn_id;
  if (
    project !== undefined &&
    project !== null &&
    project !== state.context.projectId
  )
    return state;
  if (
    typeof turnId === "string" &&
    state.serverTurnId &&
    turnId !== state.serverTurnId
  )
    return state;
  const next =
    typeof turnId === "string" && !state.serverTurnId
      ? { ...state, serverTurnId: turnId }
      : state;
  switch (event.type) {
    case "started":
      return next.committed ? next : { ...next, phase: "admitted" };
    case "heartbeat":
      return next;
    case "text_delta":
      return next.replyComplete || next.committed
        ? next
        : { ...next, phase: "receiving", reply: next.reply + event.text };
    case "progress":
      return {
        ...next,
        progress: [
          ...next.progress.filter((step) => step.id !== event.data.id),
          event.data,
        ],
      };
    case "reply_complete":
      return { ...next, reply: event.data.reply, replyComplete: true };
    case "conversation_saved":
      return {
        ...next,
        phase: "conversation_committed",
        reply: event.data.reply,
        replyComplete: true,
        committed: true,
        sourceAccepted: true,
        enrichment: next.enrichment === "idle" ? "pending" : next.enrichment,
        recallStatus: event.data.recall_status ?? next.recallStatus,
        errorCode: undefined,
      };
    case "place_preview":
      return { ...next, placePreview: event.data };
    case "workspace_error":
      return {
        ...next,
        enrichment: "failed",
        ...(next.committed ? { phase: "complete" as const } : {}),
      };
    case "workspace_update": {
      // Same sequence can carry several different fields. Lower sequences are stale.
      const sequence = event.data.source_sequence;
      if (
        sequence &&
        next.workspaceSequence &&
        compareDecimalSequences(sequence, next.workspaceSequence) < 0
      )
        return next;
      return {
        ...next,
        workspace: { ...next.workspace, ...event.data },
        workspaceSequence: sequence ?? next.workspaceSequence,
        enrichment:
          event.data.workspace_status === "ready"
            ? "complete"
            : next.enrichment === "failed"
              ? "failed"
              : "pending",
        ...(event.data.workspace_status === "ready" && next.committed
          ? { phase: "complete" as const }
          : {}),
      };
    }
    case "result": {
      const result = event.data;
      // Live successful results carry a saved reply + durable memory. Cached replay
      // has conversation_saved:true. A quota result has reply:null and isn't saved.
      const memory = Array.isArray(result.memory)
        ? result.memory[0]
        : result.memory;
      const durableMemory =
        !!memory &&
        typeof memory === "object" &&
        "id" in memory &&
        typeof memory.id === "string";
      const saved =
        result.conversation_saved === true ||
        (typeof result.reply === "string" && durableMemory);
      const committed = next.committed || saved;
      return {
        ...next,
        reply: result.reply ?? next.reply,
        replyComplete: next.replyComplete || result.reply !== null,
        committed,
        sourceAccepted:
          next.sourceAccepted || !!result.accepted_source_id || saved,
        phase: committed
          ? "complete"
          : result.recall_status?.payment_required
            ? "rejected"
            : "uncertain",
        enrichment:
          next.enrichment === "failed"
            ? "failed"
            : committed
              ? "complete"
              : next.enrichment,
        recallStatus: result.recall_status ?? next.recallStatus,
        workspace: { ...next.workspace, ...result },
        errorCode: result.recall_status?.payment_required
          ? "PAYMENT_REQUIRED"
          : next.errorCode,
      };
    }
    case "error":
      return next.committed
        ? {
            ...next,
            enrichment: "failed",
            phase: "complete",
            errorCode: event.code ?? "STREAM_INTERRUPTED",
          }
        : finishUncertain(next, event.code ?? "STREAM_INTERRUPTED");
  }
}
