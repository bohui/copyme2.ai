import type { FetchTransport, FetchResponse } from "@memoir/api-client";
import type {
  AuthPort,
  MobileSession,
} from "../../../apps/mobile/src/auth/client";
import type { StoryState } from "@memoir/contracts";
import type { Vault } from "../../../apps/mobile/src/platform/vault";

const baseUrl = "https://memoir.example/api/v1/memoir";
export const publicAuth = {
  url: "https://auth.example.invalid",
  publishableKey: "sb_publishable_synthetic_integration_fixture",
};
export function sessionFor(owner: string, anonymous = false): MobileSession {
  return {
    access_token: `synthetic-${owner}`,
    refresh_token: `synthetic-refresh-${owner}`,
    user: { id: owner, is_anonymous: anonymous },
  };
}
export function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
export function jsonResponse(value: unknown): FetchResponse {
  return {
    ok: true,
    status: 200,
    headers: { "Content-Type": "application/json" },
    text: async () => JSON.stringify(value),
  };
}
export function projectsResponse(owner: string) {
  return jsonResponse({
    schema_version: 1,
    items: [
      {
        project_id: `project-${owner}`,
        source_sequence: "0",
        event_sequence: "0",
        policy_epoch: "1",
      },
    ],
    next_after_project_id: null,
  });
}
export function storyResponse(owner: string) {
  const state: StoryState = {
    user_id: owner,
    is_anonymous: false,
    rounds_required: 5,
    rounds_completed: 0,
    free_chapter_claimed: false,
    free_chapter_id: null,
    payment_status: "unpaid",
    payment_plan: null,
    book_count: 0,
    payment_features: [],
    family_features_enabled: false,
    free_chapter_available: false,
    next_action: "continue",
  };
  return jsonResponse(state);
}
export const mockRuntime = {
  session: sessionFor("owner-a") as MobileSession | null,
  secure: new Map<string, string>(),
  vaults: new Map<string, Vault>(),
  routes: new Map<string, FetchTransport>(),
};
const sessionResult = () => ({
  data: { session: mockRuntime.session },
  error: null,
});
export const authPort: jest.Mocked<AuthPort> = {
  getSession: jest.fn(async () => sessionResult()),
  signInAnonymously: jest.fn(async () => {
    mockRuntime.session = sessionFor("owner-a", true);
    return sessionResult();
  }),
  signInWithPassword: jest.fn(
    async (_input: Parameters<AuthPort["signInWithPassword"]>[0]) => {
      mockRuntime.session = sessionFor("owner-b");
      return sessionResult();
    },
  ),
  signUp: jest.fn(async (_input: Parameters<AuthPort["signUp"]>[0]) => {
    mockRuntime.session = sessionFor("owner-b");
    return sessionResult();
  }),
  updateUser: jest.fn(async (_input: Parameters<AuthPort["updateUser"]>[0]) => {
    if (!mockRuntime.session) throw new Error("Missing fixture session");
    mockRuntime.session = {
      ...mockRuntime.session,
      user: { ...mockRuntime.session.user, is_anonymous: false },
    };
    return { data: { user: mockRuntime.session.user }, error: null };
  }),
  signInWithOAuth: jest.fn(
    async (_input: Parameters<AuthPort["signInWithOAuth"]>[0]) => ({
      data: { url: "https://auth.example.invalid/authorize" },
      error: null,
    }),
  ),
  linkIdentity: jest.fn(
    async (_input: Parameters<AuthPort["linkIdentity"]>[0]) => ({
      data: { url: "https://auth.example.invalid/authorize" },
      error: null,
    }),
  ),
  exchangeCodeForSession: jest.fn(async (_code: string) => sessionResult()),
  refreshSession: jest.fn(async () => sessionResult()),
  signOut: jest.fn(async () => {
    mockRuntime.session = null;
    return { error: null };
  }),
};
export const mockCreateSupabase = jest.fn(
  (_url: string, _key: string, _options: unknown) => ({ auth: authPort }),
);
export const mockCleanupMedia = jest.fn(async () => undefined);
export const mockTransport: jest.MockedFunction<FetchTransport> = jest.fn(
  async (url, init) => {
    const path = new URL(url).pathname.replace("/api/v1/memoir", "");
    const override = mockRuntime.routes.get(path);
    if (override) return override(url, init);
    const owner =
      init.headers.Authorization?.replace("Bearer synthetic-", "") ?? "owner-a";
    if (path === "/agent/config")
      return jsonResponse({
        enabled: true,
        auth_mode: "supabase",
        supabase_url: publicAuth.url,
        supabase_publishable_key: publicAuth.publishableKey,
      });
    if (path === "/user/projects") return projectsResponse(owner);
    if (path.endsWith("/history"))
      return jsonResponse({
        schema_version: 1,
        policy_epoch: "1",
        project_id: path.split("/").at(-2),
        items: [],
        next_cursor: null,
      });
    if (path === "/story/state") return storyResponse(owner);
    if (path === "/user/profile") return jsonResponse({});
    if (path === "/user/conversation-transfer")
      return jsonResponse({ expires_in: 3600 });
    throw new Error(
      `Unexpected synthetic transport request: ${init.method} ${path}`,
    );
  },
);

jest.mock("expo/virtual/env", () => ({
  env: {
    EXPO_PUBLIC_MEMOIR_API_URL: "https://memoir.example/api/v1/memoir",
    EXPO_PUBLIC_MEMOIR_FIXTURE: "0",
    EXPO_PUBLIC_SUPABASE_URL: "https://auth.example.invalid",
    EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY:
      "sb_publishable_synthetic_integration_fixture",
  },
}));
jest.mock("expo/fetch", () => ({
  fetch: (...args: Parameters<FetchTransport>) => mockTransport(...args),
}));
jest.mock("@supabase/supabase-js", () => ({
  createClient: (...args: Parameters<typeof mockCreateSupabase>) =>
    mockCreateSupabase(...args),
}));
jest.mock("expo-web-browser", () => ({
  openAuthSessionAsync: async () => ({ type: "cancel" }),
}));
jest.mock("expo-crypto", () => {
  let sequence = 0;
  let entropySequence = 0;
  return {
    CryptoDigestAlgorithm: { SHA256: "sha256" },
    digestStringAsync: async (_algorithm: string, value: string) => {
      const { createHash } =
        jest.requireActual<typeof import("node:crypto")>("node:crypto");
      return createHash("sha256").update(value).digest("hex");
    },
    randomUUID: () =>
      `11111111-1111-4111-8111-${String(++sequence).padStart(12, "0")}`,
    getRandomBytes: (length: number) =>
      new Uint8Array(length).fill(++entropySequence),
  };
});
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: "fixture-device-only",
  isAvailableAsync: async () => true,
  getItemAsync: async (key: string) => mockRuntime.secure.get(key) ?? null,
  setItemAsync: async (key: string, value: string) => {
    mockRuntime.secure.set(key, value);
  },
  deleteItemAsync: async (key: string) => {
    mockRuntime.secure.delete(key);
  },
}));
jest.mock("expo-linking", () => ({
  addEventListener: () => ({ remove() {} }),
  getInitialURL: async () => null,
}));
jest.mock("expo-localization", () => ({
  getLocales: () => [{ languageCode: "en" }],
}));
jest.mock("../../../apps/mobile/src/platform/native-media", () => ({
  clearNativeMediaTemporaryFiles: () => mockCleanupMedia(),
}));
jest.mock("../../../apps/mobile/src/platform/vault", () => {
  const actual = jest.requireActual<
    typeof import("../../../apps/mobile/src/platform/vault")
  >("../../../apps/mobile/src/platform/vault");
  return {
    ...actual,
    createVault: async (owner: string) => {
      const existing = mockRuntime.vaults.get(owner);
      if (existing) return existing;
      const vault = await actual.createVault(owner, "fixture");
      mockRuntime.vaults.set(owner, vault);
      return vault;
    },
  };
});

export async function seedVault(owner = "owner-a") {
  const actual = jest.requireActual<
    typeof import("../../../apps/mobile/src/platform/vault")
  >("../../../apps/mobile/src/platform/vault");
  const vault = await actual.createVault(owner, "fixture");
  mockRuntime.vaults.set(owner, vault);
  return vault;
}
export function requestCount(path: string) {
  return mockTransport.mock.calls.filter(([url]) => url === baseUrl + path)
    .length;
}

beforeEach(() => {
  mockRuntime.session = sessionFor("owner-a");
  mockRuntime.secure.clear();
  mockRuntime.vaults.clear();
  mockRuntime.routes.clear();
  authPort.signOut.mockImplementation(async () => {
    mockRuntime.session = null;
    return { error: null };
  });
  mockCleanupMedia.mockResolvedValue(undefined);
  jest
    .spyOn(globalThis, "fetch")
    .mockRejectedValue(
      new Error("Live networking is forbidden in provider integration tests"),
    );
});

export {
  mockRuntime as runtime,
  mockTransport as transport,
  mockCreateSupabase as createSupabase,
  mockCleanupMedia as cleanupMedia,
};
