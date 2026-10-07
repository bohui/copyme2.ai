import {
  initialTurnState,
  type TurnState,
  type TurnOutboxItem,
} from "@memoir/memoir-domain";
import { translate, type Locale } from "@memoir/i18n";
import { useMemoir } from "../../../apps/mobile/src/context";

export type ScreenContext = ReturnType<typeof useMemoir>;
export const ownerId = "fictional-owner";
export const projectId = "fictional-story";
export const operationId = "11111111-1111-4111-8111-111111111111";
export const guest = {
  access_token: "synthetic-test-only",
  refresh_token: "synthetic-test-only",
  user: { id: ownerId, is_anonymous: true },
};

export function context(overrides: Partial<ScreenContext> = {}): ScreenContext {
  const locale = overrides.locale ?? "en-AU";
  return {
    locale,
    t: (key) => translate(locale, key),
    fixture: false,
    configured: true,
    loading: false,
    identityBusy: false,
    logoutNeedsRetry: false,
    error: null,
    api: null,
    auth: null,
    session: guest,
    vault: {
      owner: ownerId,
      get: async () => null,
      set: async () => undefined,
      delete: async () => undefined,
      cacheGet: async () => null,
      cacheSet: async () => undefined,
      cacheDelete: async () => undefined,
      listOutbox: async () => [],
      listComposers: async () => [],
      putOutbox: async () => undefined,
      deleteOutbox: async () => undefined,
      saveMedia: async () => undefined,
      deleteMedia: async () => undefined,
      clear: async () => undefined,
      close: async () => undefined,
    },
    projectId,
    projects: [],
    localProjectIds: [],
    messages: [],
    draft: "",
    active: null,
    pending: [],
    storyState: null,
    historyCursor: null,
    setLocale: jest.fn(async (_locale: Locale) => undefined),
    setDraft: jest.fn(async (_text: string) => undefined),
    begin: jest.fn(async () => undefined),
    refresh: jest.fn(async () => undefined),
    selectProject: jest.fn(async (_id: string) => undefined),
    newProject: jest.fn(async () => undefined),
    send: jest.fn(async () => undefined),
    retry: jest.fn(async (_item: TurnOutboxItem) => undefined),
    discard: jest.fn(async (_item: TurnOutboxItem) => undefined),
    loadEarlier: jest.fn(async () => undefined),
    signOut: jest.fn(async () => undefined),
    ...overrides,
  };
}

export function inject(value: ScreenContext) {
  jest.mocked(useMemoir).mockReturnValue(value);
  return value;
}

export function activeTurn(
  overrides: Partial<TurnState> = {},
): NonNullable<ScreenContext["active"]> {
  const command = {
    project_id: projectId,
    client_turn_id: operationId,
    text: "A fictional childhood memory.",
  };
  return {
    state: {
      ...initialTurnState({
        ownerId,
        projectId,
        clientTurnId: operationId,
        generation: 1,
      }),
      ...overrides,
    },
    item: {
      schemaVersion: 1,
      operationId,
      ownerId,
      projectId,
      kind: "turn",
      command,
      payloadJson: JSON.stringify(command),
      payloadHash: "a".repeat(64),
      baseRevision: null,
      dependencies: [],
      state: "uncertain",
      attempts: 1,
      createdAt: 1,
      nextAttemptAt: null,
      lastErrorCode: null,
    },
  };
}

export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
