export type ErrorRecovery =
  "authenticate" | "reconcile" | "retry" | "correct" | "stop";
export type HeaderValues =
  { get(name: string): string | null } | Record<string, string | undefined>;
export function headerValue(
  headers: HeaderValues | undefined,
  name: string,
): string | undefined {
  if (!headers) return undefined;
  if (typeof headers.get === "function") return headers.get(name) ?? undefined;
  const key = Object.keys(headers).find(
    (key) => key.toLowerCase() === name.toLowerCase(),
  );
  return key ? (headers as Record<string, string | undefined>)[key] : undefined;
}
export class MemoirApiError extends Error {
  readonly name = "MemoirApiError";
  constructor(
    public readonly code: string,
    public readonly status: number,
    public readonly recovery: ErrorRecovery,
    public readonly retryable: boolean,
    public readonly requestId?: string,
    public readonly retryAfterMs?: number,
  ) {
    super(code);
  }
}
const defaultCodes: Record<number, string> = {
  0: "NETWORK_ERROR",
  400: "BAD_REQUEST",
  401: "UNAUTHENTICATED",
  403: "FORBIDDEN",
  404: "NOT_FOUND",
  409: "CONFLICT",
  410: "GONE",
  413: "PAYLOAD_TOO_LARGE",
  415: "UNSUPPORTED_MEDIA_TYPE",
  422: "VALIDATION_ERROR",
  429: "RATE_LIMITED",
  503: "PROCESSING_UNAVAILABLE",
};
export function mapApiError(
  status: number,
  body: unknown,
  headers?: HeaderValues,
  now = Date.now(),
): MemoirApiError {
  const raw =
    body && typeof body === "object" && "error" in body
      ? (body as { error: unknown }).error
      : null;
  const error =
    raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const headerCode = headerValue(headers, "X-Error-Code");
  const rawCode = typeof error.code === "string" ? error.code : headerCode;
  const code =
    rawCode && /^[A-Z][A-Z0-9_]{0,100}$/.test(rawCode)
      ? rawCode
      : (defaultCodes[status] ?? "REQUEST_FAILED");
  const suppliedId =
    headerValue(headers, "X-Request-ID") ??
    (typeof error.request_id === "string" ? error.request_id : undefined);
  const requestId =
    suppliedId && /^[A-Za-z0-9._:-]{1,128}$/.test(suppliedId)
      ? suppliedId
      : undefined;
  const retryable =
    (status === 0 || status === 429 || status >= 500) &&
    error.retryable !== false;
  const recovery: ErrorRecovery =
    status === 401
      ? "authenticate"
      : status === 409
        ? "reconcile"
        : status === 422 || status === 400
          ? "correct"
          : retryable
            ? "retry"
            : "stop";
  const retryAfter = headerValue(headers, "Retry-After");
  let retryAfterMs: number | undefined;
  if (retryAfter) {
    const seconds = Number(retryAfter);
    const delay = /^\d+(?:\.\d+)?$/.test(retryAfter)
      ? seconds * 1000
      : Date.parse(retryAfter) - now;
    if (Number.isFinite(delay)) retryAfterMs = Math.max(0, delay);
  }
  // Raw error bodies may contain provider details or source text. Do not retain them.
  return new MemoirApiError(
    code,
    status,
    recovery,
    retryable,
    requestId,
    retryAfterMs,
  );
}
export function retryDelay(
  error: MemoirApiError,
  attempt: number,
  options: { idempotent: boolean; maxAttempts?: number; random?: () => number },
): number | null {
  if (
    !options.idempotent ||
    !error.retryable ||
    error.recovery !== "retry" ||
    !Number.isSafeInteger(attempt) ||
    attempt < 0 ||
    attempt >= (options.maxAttempts ?? 4)
  )
    return null;
  const random = Math.min(1, Math.max(0, (options.random ?? Math.random)()));
  const backoff = Math.min(30000, 1000 * 2 ** attempt) * (0.5 + random * 0.5);
  return Math.max(backoff, error.retryAfterMs ?? 0);
}
