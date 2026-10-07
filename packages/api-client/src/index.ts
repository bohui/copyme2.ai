import { z } from "zod";
import * as C from "@memoir/contracts";
import { NdjsonDecoder, parseWireJson } from "./ndjson";
import {
  MemoirApiError,
  mapApiError,
  headerValue,
  type HeaderValues,
} from "./errors";
export * from "./ndjson";
export * from "./errors";

/** Inject expo/fetch and a fresh-token supplier. No global fetch or storage. */
export interface FetchResponse {
  ok: boolean;
  status: number;
  headers: HeaderValues;
  text(): Promise<string>;
  body?: {
    getReader(): {
      read(): Promise<{ done: boolean; value?: Uint8Array }>;
      cancel?(): Promise<unknown>;
      releaseLock?(): void;
    };
  } | null;
}
export interface FetchOptions {
  method: string;
  headers: Record<string, string>;
  body?: string;
  signal?: AbortSignal;
}
export type FetchTransport = (
  url: string,
  init: FetchOptions,
) => Promise<FetchResponse>;
export interface ApiClientOptions {
  baseUrl: string;
  fetch: FetchTransport;
  getToken: () => Promise<string | null | undefined>;
  allowInsecureDevelopment?: boolean;
}
export interface RequestOptions {
  signal?: AbortSignal;
  requestId?: string;
}
export interface StreamOptions extends RequestOptions {
  onEvent: (event: C.TurnEvent) => void;
}
export interface StreamOutcome {
  terminal: "result" | "error" | "eof";
  result?: C.TurnResult;
}

export function createMemoirApi(options: ApiClientOptions) {
  const base = new URL(options.baseUrl);
  if (
    base.username ||
    base.password ||
    base.search ||
    base.hash ||
    !["http:", "https:"].includes(base.protocol)
  )
    throw new Error("Invalid API base URL");
  if (base.protocol !== "https:" && !options.allowInsecureDevelopment)
    throw new Error("HTTPS is required for the API");
  const baseUrl = base.toString().replace(/\/$/, "");
  const encoded = (value: string) => encodeURIComponent(value);
  const query = (values: Record<string, string | number | undefined>) => {
    const parts = Object.entries(values)
      .filter(([, value]) => value !== undefined)
      .map(([key, value]) => `${encoded(key)}=${encoded(String(value))}`);
    return parts.length ? `?${parts.join("&")}` : "";
  };
  async function response(
    path: string,
    method: string,
    body: unknown,
    request: RequestOptions = {},
    stream = false,
    authenticated = true,
  ) {
    const headers: Record<string, string> = {
      Accept: stream ? "application/x-ndjson" : "application/json",
    };
    if (authenticated) {
      const token = await options.getToken();
      if (!token) throw mapApiError(401, {});
      headers.Authorization = `Bearer ${token}`;
    }
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (request.requestId) {
      if (!/^[A-Za-z0-9._:-]{1,128}$/.test(request.requestId))
        throw new Error("Invalid request ID");
      headers["X-Request-ID"] = request.requestId;
    }
    let result: FetchResponse;
    try {
      result = await options.fetch(baseUrl + path, {
        method,
        headers,
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        ...(request.signal ? { signal: request.signal } : {}),
      });
    } catch {
      if (request.signal?.aborted)
        throw new MemoirApiError("REQUEST_CANCELLED", 0, "reconcile", false);
      throw mapApiError(0, {});
    }
    if (!result.ok) {
      let errorBody: unknown;
      try {
        errorBody = parseWireJson(await boundedText(result));
      } catch {
        errorBody = {};
      }
      throw mapApiError(result.status, errorBody, result.headers);
    }
    return result;
  }
  async function boundedText(response: FetchResponse): Promise<string> {
    const declared = Number(
      headerValue(response.headers, "Content-Length") ?? 0,
    );
    if (declared > 8 * 1024 * 1024)
      throw new MemoirApiError("RESPONSE_TOO_LARGE", 0, "stop", false);
    const text = await response.text();
    if (text.length > 8 * 1024 * 1024)
      throw new MemoirApiError("RESPONSE_TOO_LARGE", 0, "stop", false);
    return text;
  }
  async function json<T>(
    path: string,
    schema: z.ZodType<T>,
    method = "GET",
    body?: unknown,
    request?: RequestOptions,
    authenticated = true,
  ): Promise<T> {
    const res = await response(
      path,
      method,
      body,
      request,
      false,
      authenticated,
    );
    try {
      return schema.parse(parseWireJson(await boundedText(res)));
    } catch (error) {
      if (error instanceof MemoirApiError) throw error;
      throw new MemoirApiError(
        "INVALID_RESPONSE",
        res.status,
        "stop",
        false,
        headerValue(res.headers, "X-Request-ID"),
      );
    }
  }
  async function stream(
    path: string,
    payload: unknown,
    request: StreamOptions,
  ): Promise<StreamOutcome> {
    const res = await response(path, "POST", payload, request, true);
    const contentType = headerValue(res.headers, "Content-Type") ?? "";
    if (
      contentType.includes("application/json") &&
      !contentType.includes("ndjson")
    ) {
      let data: C.TurnResult;
      try {
        data = C.TurnResultSchema.parse(parseWireJson(await boundedText(res)));
      } catch {
        throw new MemoirApiError("INVALID_RESPONSE", res.status, "stop", false);
      }
      request.onEvent({ type: "result", data });
      return { terminal: "result", result: data };
    }
    if (!contentType.includes("application/x-ndjson") || !res.body)
      throw new MemoirApiError(
        "STREAM_UNAVAILABLE",
        res.status,
        "reconcile",
        false,
      );
    const reader = res.body.getReader();
    const decoder = new NdjsonDecoder();
    let outcome: StreamOutcome = { terminal: "eof" };
    const emit = (events: C.TurnEvent[]) => {
      for (const event of events) {
        if (outcome.terminal !== "eof") break;
        request.onEvent(event);
        if (event.type === "result")
          outcome = { terminal: "result", result: event.data };
        else if (event.type === "error") outcome = { terminal: "error" };
      }
    };
    try {
      while (outcome.terminal === "eof") {
        const chunk = await reader.read();
        if (chunk.done) {
          emit(decoder.finish());
          break;
        }
        if (chunk.value) emit(decoder.push(chunk.value));
      }
      return outcome;
    } catch (error) {
      if (error instanceof MemoirApiError) throw error;
      throw new MemoirApiError(
        request.signal?.aborted ? "REQUEST_CANCELLED" : "STREAM_INTERRUPTED",
        0,
        "reconcile",
        false,
      );
    } finally {
      try {
        await reader.cancel?.();
      } catch {
        /* Closing an already interrupted stream is best-effort. */
      }
      reader.releaseLock?.();
    }
  }
  return {
    config: (request?: RequestOptions) =>
      json(
        "/agent/config",
        C.AgentConfigSchema,
        "GET",
        undefined,
        request,
        false,
      ),
    profile: (request?: RequestOptions) =>
      json(
        "/agent/profile",
        C.ProfileSettingsSchema,
        "GET",
        undefined,
        request,
      ),
    updateProfile: (input: C.ProfileSettingsInput, request?: RequestOptions) =>
      json(
        "/agent/profile",
        C.ProfileSettingsSchema,
        "PATCH",
        C.ProfileSettingsInputSchema.parse(input),
        request,
      ),
    workspaceProfile: (request?: RequestOptions) =>
      json("/user/profile", C.RecordSchema, "GET", undefined, request),
    conversations: (request?: RequestOptions) =>
      json(
        "/user/conversations",
        C.ConversationsSchema,
        "GET",
        undefined,
        request,
      ),
    projects: (
      params: { limit?: number; afterProjectId?: string } = {},
      request?: RequestOptions,
    ) =>
      json(
        "/user/projects" +
          query({
            limit: params.limit,
            after_project_id: params.afterProjectId,
          }),
        C.ProjectsSchema,
        "GET",
        undefined,
        request,
      ),
    history: (
      projectId: string,
      params: { limit?: number; cursor?: string } = {},
      request?: RequestOptions,
    ) =>
      json(
        `/user/projects/${encoded(C.ProjectIdSchema.parse(projectId))}/history` +
          query({ limit: params.limit, cursor: params.cursor }),
        C.HistorySchema,
        "GET",
        undefined,
        request,
      ),
    sourceDetail: (
      projectId: string,
      sourceId: string,
      expectedVersion?: string,
      request?: RequestOptions,
    ) =>
      json(
        `/user/projects/${encoded(C.ProjectIdSchema.parse(projectId))}/sources/${encoded(z.uuid().parse(sourceId))}` +
          query({
            expected_version:
              expectedVersion === undefined
                ? undefined
                : z
                    .string()
                    .regex(/^[1-9][0-9]{0,18}$/)
                    .parse(expectedVersion),
          }),
        C.NarratorSourceDetailSchema,
        "GET",
        undefined,
        request,
      ),
    turnReceipt: (
      clientTurnId: string,
      projectId: string,
      request?: RequestOptions,
    ) =>
      json(
        `/agent/turns/${encoded(z.uuid().parse(clientTurnId))}` +
          query({ project_id: C.ProjectIdSchema.parse(projectId) }),
        C.TurnReceiptSchema,
        "GET",
        undefined,
        request,
      ),
    turn: (input: C.TurnInput, request?: RequestOptions) =>
      json(
        "/agent/turn",
        C.TurnResultSchema,
        "POST",
        C.TurnInputSchema.parse(input),
        request,
      ),
    greeting: (input: C.GreetingInput, request?: RequestOptions) =>
      json(
        "/agent/greeting",
        C.TurnResultSchema,
        "POST",
        C.GreetingInputSchema.parse(input),
        request,
      ),
    streamTurn: (input: C.TurnInput, request: StreamOptions) =>
      stream("/agent/turn", C.TurnInputSchema.parse(input), request),
    streamGreeting: (input: C.GreetingInput, request: StreamOptions) =>
      stream("/agent/greeting", C.GreetingInputSchema.parse(input), request),
    storyState: (request?: RequestOptions) =>
      json("/story/state", C.StoryStateSchema, "GET", undefined, request),
    readiness: (projectId: string, request?: RequestOptions) =>
      json(
        "/story/readiness" +
          query({ project_id: C.ProjectIdSchema.parse(projectId) }),
        C.ReadinessSchema,
        "GET",
        undefined,
        request,
      ),
    privateDraft: (
      projectId: string,
      language?: C.Locale,
      request?: RequestOptions,
    ) =>
      json(
        "/story/private-draft" +
          query({ project_id: C.ProjectIdSchema.parse(projectId), language }),
        C.PrivateDraftSchema,
        "GET",
        undefined,
        request,
      ),
    retryPrivateDraft: (
      input: z.infer<typeof C.PreviewInputSchema>,
      request?: RequestOptions,
    ) =>
      json(
        "/story/private-draft/retry",
        C.PrivateDraftSchema,
        "POST",
        C.PreviewInputSchema.parse(input),
        request,
      ),
    collection: (projectId: string, request?: RequestOptions) =>
      json(
        `/agent/collection/${encoded(C.ProjectIdSchema.parse(projectId))}`,
        C.CollectionSchema,
        "GET",
        undefined,
        request,
      ),
    updateCollection: (
      projectId: string,
      input: C.CollectionUpdate,
      request?: RequestOptions,
    ) =>
      json(
        `/agent/collection/${encoded(C.ProjectIdSchema.parse(projectId))}`,
        C.CollectionSchema,
        "PUT",
        C.CollectionUpdateSchema.parse(input),
        request,
      ),
    organiseCollection: (
      projectId: string,
      input: z.infer<typeof C.OrganiseInputSchema>,
      request?: RequestOptions,
    ) =>
      json(
        `/agent/collection/${encoded(C.ProjectIdSchema.parse(projectId))}/organise`,
        C.TaskSchema,
        "POST",
        C.OrganiseInputSchema.parse(input),
        request,
      ),
    collectionTask: (
      projectId: string,
      input: z.infer<typeof C.CollectionTaskInputSchema>,
      request?: RequestOptions,
    ) =>
      json(
        `/agent/collection/${encoded(C.ProjectIdSchema.parse(projectId))}/tasks`,
        C.TaskSchema,
        "POST",
        C.CollectionTaskInputSchema.parse(input),
        request,
      ),
    task: (taskId: string, request?: RequestOptions) =>
      json(
        `/agent/tasks/${encoded(taskId)}`,
        C.TaskSchema,
        "GET",
        undefined,
        request,
      ),
    transcribe: (input: C.TranscriptionInput, request?: RequestOptions) =>
      json(
        "/story/transcriptions",
        C.TranscriptionSchema,
        "POST",
        C.TranscriptionInputSchema.parse(input),
        request,
      ),
    questionAudio: (
      input: z.infer<typeof C.SpeechInputSchema>,
      request?: RequestOptions,
    ) =>
      json(
        "/story/question-audio",
        C.SpeechSchema,
        "POST",
        C.SpeechInputSchema.parse(input),
        request,
      ),
    prepareTransfer: (input: C.TransferInput, request?: RequestOptions) =>
      json(
        "/user/conversation-transfer",
        C.RecordSchema,
        "POST",
        C.TransferInputSchema.parse(input),
        request,
      ),
    attachTransfer: (
      input: z.infer<typeof C.TransferAttachInputSchema>,
      request?: RequestOptions,
    ) =>
      json(
        "/user/conversation-transfer/attach",
        C.RecordSchema,
        "POST",
        C.TransferAttachInputSchema.parse(input),
        request,
      ),
    placePhotos: (
      projectId: string,
      params: {
        place: string;
        period: string;
        latitude?: number;
        longitude?: number;
        cursor?: string;
        refresh?: boolean;
      },
      request?: RequestOptions,
    ) =>
      json(
        `/agent/places/${encoded(C.ProjectIdSchema.parse(projectId))}/photos` +
          query({ ...params, refresh: params.refresh ? "true" : undefined }),
        C.PhotoPageSchema,
        "GET",
        undefined,
        request,
      ),
    placeJourney: (request?: RequestOptions) =>
      json(
        "/agent/place-journey",
        z.object({ place_journey: C.RecordSchema.nullable() }).passthrough(),
        "GET",
        undefined,
        request,
      ),
    familyContext: (projectId: string, request?: RequestOptions) =>
      json(
        "/agent/family-context" +
          query({ project_id: C.ProjectIdSchema.parse(projectId) }),
        C.RecordSchema,
        "GET",
        undefined,
        request,
      ),
    events: (projectId: string, request?: RequestOptions) =>
      json(
        "/story/events" +
          query({ project_id: C.ProjectIdSchema.parse(projectId) }),
        C.RecordSchema,
        "GET",
        undefined,
        request,
      ),
    correctEvent: (
      projectId: string,
      eventId: string,
      input: z.infer<typeof C.EventCorrectionSchema>,
      request?: RequestOptions,
    ) =>
      json(
        `/story/events/${encoded(C.ProjectIdSchema.parse(projectId))}/${encoded(eventId)}`,
        C.RecordSchema,
        "PATCH",
        C.EventCorrectionSchema.parse(input),
        request,
      ),
  };
}
export type MemoirApi = ReturnType<typeof createMemoirApi>;
