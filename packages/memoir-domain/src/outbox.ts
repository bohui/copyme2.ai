import { TurnInputSchema, type TurnInput } from "@memoir/contracts";
export type PayloadHash = (canonicalPayload: string) => Promise<string>;
export interface OutboxScope {
  ownerId: string;
  projectId: string;
  environment: string;
}
export interface TurnOutboxItem {
  schemaVersion: 1;
  operationId: string;
  ownerId: string;
  projectId: string;
  kind: "turn";
  command: TurnInput;
  payloadJson: string;
  payloadHash: string;
  baseRevision: string | null;
  dependencies: string[];
  state:
    "queued" | "sending" | "uncertain" | "paused" | "committed" | "rejected";
  attempts: number;
  createdAt: number;
  nextAttemptAt: number | null;
  lastErrorCode: string | null;
}
/** Implement using an encrypted native database/file adapter. All methods are
 * owner/environment scoped; no bearer/refresh token is part of the interface.
 * put must durably commit before the first network transmission is admitted.
 */
export interface SecureOutboxStore {
  list(scope: OutboxScope): Promise<TurnOutboxItem[]>;
  put(scope: OutboxScope, item: TurnOutboxItem): Promise<void>;
  remove(scope: OutboxScope, operationId: string): Promise<void>;
  clearOwner(ownerId: string, environment: string): Promise<void>;
}
export function canonicalTurnPayload(command: TurnInput): string {
  const parsed = TurnInputSchema.parse(command);
  return JSON.stringify(
    Object.fromEntries(
      Object.keys(parsed)
        .sort()
        .filter((key) => parsed[key as keyof TurnInput] !== undefined)
        .map((key) => [key, parsed[key as keyof TurnInput]]),
    ),
  );
}
export async function createTurnOutboxItem(options: {
  ownerId: string;
  projectId: string;
  command: TurnInput;
  hash: PayloadHash;
  now?: number;
  baseRevision?: string | null;
  dependencies?: string[];
}): Promise<TurnOutboxItem> {
  const command = TurnInputSchema.parse(options.command);
  if (
    !options.ownerId ||
    command.project_id !== options.projectId ||
    !command.client_turn_id
  )
    throw new Error(
      "Outbox requires an owner, matching project and stable client turn UUID",
    );
  const payloadJson = canonicalTurnPayload(command),
    payloadHash = await options.hash(payloadJson);
  if (!/^[a-f0-9]{64}$/i.test(payloadHash))
    throw new Error("Outbox requires a SHA-256 payload hash");
  return {
    schemaVersion: 1,
    operationId: command.client_turn_id,
    ownerId: options.ownerId,
    projectId: options.projectId,
    kind: "turn",
    command: Object.freeze(command),
    payloadJson,
    payloadHash: payloadHash.toLowerCase(),
    baseRevision: options.baseRevision ?? null,
    dependencies: [...(options.dependencies ?? [])],
    state: "queued",
    attempts: 0,
    createdAt: options.now ?? Date.now(),
    nextAttemptAt: null,
    lastErrorCode: null,
  };
}
export async function assertReplayPayload(
  item: TurnOutboxItem,
  command: TurnInput,
  hash: PayloadHash,
): Promise<void> {
  const canonical = canonicalTurnPayload(command);
  if (
    item.operationId !== command.client_turn_id ||
    item.projectId !== command.project_id ||
    canonical !== item.payloadJson ||
    canonicalTurnPayload(item.command) !== item.payloadJson ||
    (await hash(canonical)).toLowerCase() !== item.payloadHash
  )
    throw new Error(
      "Retry payload changed; preserve the original command or create a new logical turn",
    );
}
export function assertOutboxScope(
  scope: OutboxScope,
  item: TurnOutboxItem,
): void {
  if (scope.ownerId !== item.ownerId || scope.projectId !== item.projectId)
    throw new Error("Outbox account/project scope mismatch");
}
export function canReplayOutbox(
  item: TurnOutboxItem,
  scope: OutboxScope,
  committedDependencies: ReadonlySet<string>,
  now: number,
): boolean {
  return (
    item.ownerId === scope.ownerId &&
    item.projectId === scope.projectId &&
    item.state === "queued" &&
    item.dependencies.every((id) => committedDependencies.has(id)) &&
    (item.nextAttemptAt === null || item.nextAttemptAt <= now)
  );
}
