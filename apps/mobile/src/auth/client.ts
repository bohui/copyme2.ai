import {
  createNativeSessionStorage,
  type SecureStoreDriver,
} from "../platform/secure-storage";
export interface MobileUser {
  id: string;
  email?: string;
  is_anonymous?: boolean;
}
export interface MobileSession {
  access_token: string;
  refresh_token: string;
  expires_at?: number;
  user: MobileUser;
}
type Result<T> = { data: T; error: { message: string } | null };
type SessionResult = Result<{ session: MobileSession | null }>;
export type OAuthProvider = "google" | "apple" | "facebook";
type OAuthInput = {
  provider: OAuthProvider;
  options: { redirectTo: string; skipBrowserRedirect: boolean };
};
/** Structural seam keeps unit tests offline and avoids importing native modules. */
export interface AuthPort {
  getSession(): Promise<SessionResult>;
  signInAnonymously(): Promise<SessionResult>;
  signInWithPassword(input: {
    email: string;
    password: string;
  }): Promise<SessionResult>;
  signUp(input: { email: string; password: string }): Promise<SessionResult>;
  updateUser(input: {
    email: string;
    password: string;
  }): Promise<Result<{ user: MobileUser | null }>>;
  signInWithOAuth(input: OAuthInput): Promise<Result<{ url: string | null }>>;
  linkIdentity(input: OAuthInput): Promise<Result<{ url: string | null }>>;
  exchangeCodeForSession(code: string): Promise<SessionResult>;
  refreshSession(): Promise<SessionResult>;
  signOut(input?: {
    scope: "local";
  }): Promise<{ error: { message: string } | null }>;
}
export interface TransferAdapter {
  /** Quiesce/reconcile writes and register the same capability before resolving. */
  prepare(input: {
    guestId: string;
    accessToken: string;
    token: string;
  }): Promise<{ expiresAt: number }>;
  /** Idempotent server attach followed by authoritative history reconciliation. */
  attach(input: {
    token: string;
    accessToken: string;
    guestWins: boolean;
  }): Promise<unknown>;
}
export interface AuthServiceOptions {
  auth: AuthPort;
  storage: SecureStoreDriver;
  environment: string;
  redirectUrl: string;
  randomHex(): string;
  now?: () => number;
  openAuthSession(
    url: string,
    redirectUrl: string,
  ): Promise<{ type: string; url?: string }>;
  transfer?: TransferAdapter;
  onIdentityChange?(
    previousOwner: string | null,
    nextOwner: string | null,
  ): Promise<void>;
  onLogout?(owner: string | null): Promise<void>;
  onOperationStateChange?(busy: boolean): void;
}
interface TransferRecovery {
  environment: string;
  guestId: string;
  guestSession: MobileSession;
  token: string;
  expiresAt: number;
  prepared: boolean;
}
interface OAuthFlow {
  nonce: string;
  expiresAt: number;
  environment: string;
}
function checked<T>(result: Result<T>): T {
  if (result.error) throw new Error(result.error.message);
  return result.data;
}
export function createAuthService(options: AuthServiceOptions) {
  const now = options.now ?? Date.now;
  const redirect = new URL(options.redirectUrl);
  if (
    !["memoir:", "https:"].includes(redirect.protocol) ||
    redirect.username ||
    redirect.password ||
    redirect.search ||
    redirect.hash
  )
    throw new Error("Invalid authentication redirect");
  if (!/^[A-Za-z0-9_.-]{1,80}$/.test(options.environment))
    throw new Error("Invalid authentication environment");
  const listeners = new Set<(session: MobileSession | null) => void>();
  let current: MobileSession | null = null;
  let epoch = 0;
  let loggedOut = false;
  let cleanupBlocked = false;
  let queue: Promise<unknown> = Promise.resolve();
  const notify = () => {
    for (const listener of listeners) listener(current);
  };
  async function adopt(session: MobileSession | null, expectedEpoch = epoch) {
    if (expectedEpoch !== epoch || loggedOut)
      throw new Error("Authentication operation cancelled");
    const previous = current?.user.id ?? null;
    const next = session?.user.id ?? null;
    if (previous !== next) {
      // Revoke UI access before awaiting cache/media cleanup.
      current = null;
      notify();
      await options.onIdentityChange?.(previous, next);
      if (expectedEpoch !== epoch || loggedOut)
        throw new Error("Authentication operation cancelled");
    }
    current = session;
    notify();
    return session;
  }
  function mutate<T>(
    task: (expectedEpoch: number) => Promise<T>,
    locksIdentity = true,
  ): Promise<T> {
    const expected = epoch;
    const result = queue
      .catch(() => undefined)
      .then(async () => {
        if (expected !== epoch)
          throw new Error("Authentication operation cancelled");
        if (cleanupBlocked)
          throw new Error(
            "Finish local logout cleanup before signing into another account",
          );
        if (locksIdentity) options.onOperationStateChange?.(true);
        try {
          return await task(expected);
        } finally {
          if (locksIdentity) options.onOperationStateChange?.(false);
        }
      });
    queue = result;
    return result;
  }
  async function getSession() {
    if (loggedOut) return null;
    const expected = epoch;
    const session = checked(await options.auth.getSession()).session;
    if (expected !== epoch || loggedOut) return null;
    return adopt(session, expected);
  }
  async function recovery(): Promise<TransferRecovery | null> {
    const raw = await options.storage.getItem("transfer");
    if (!raw) return null;
    const item = JSON.parse(raw) as TransferRecovery;
    if (
      item.environment !== options.environment ||
      !item.guestId ||
      item.guestSession?.user.id !== item.guestId ||
      !item.guestSession.user.is_anonymous ||
      !/^[a-f0-9]{64}$/.test(item.token)
    )
      throw new Error("Invalid guest transfer recovery");
    return item;
  }
  async function prepareTransfer(session: MobileSession) {
    if (!session.user.is_anonymous) return;
    if (!options.transfer)
      throw new Error(
        "Guest transfer is unavailable. Link this guest account or keep your guest work before signing into another account.",
      );
    let pending = await recovery();
    if (pending && pending.guestId !== session.user.id)
      throw new Error("Another guest transfer needs review");
    if (!pending) {
      const token = options.randomHex();
      if (!/^[a-f0-9]{64}$/.test(token))
        throw new Error("Invalid secure random capability");
      pending = {
        environment: options.environment,
        guestId: session.user.id,
        guestSession: session,
        token,
        expiresAt: 0,
        prepared: false,
      };
      // Save before the network call: a lost preparation response must reuse this capability.
      await options.storage.setItem("transfer", JSON.stringify(pending));
    }
    if (pending.prepared) {
      if (pending.expiresAt <= now())
        throw new Error(
          "Guest transfer expired. Keep this guest session and prepare a new transfer explicitly.",
        );
    }
    // A cancelled sign-in may leave a prepared capability while the guest keeps
    // writing. Recheck local work and refresh the snapshot with the SAME token.
    // Never call preparation after switching to the destination identity.
    const prepared = await options.transfer.prepare({
      guestId: pending.guestId,
      accessToken: session.access_token,
      token: pending.token,
    });
    if (!Number.isFinite(prepared.expiresAt) || prepared.expiresAt <= now())
      throw new Error("Guest transfer expiry unavailable");
    await options.storage.setItem(
      "transfer",
      JSON.stringify({
        ...pending,
        guestSession: session,
        prepared: true,
        expiresAt: prepared.expiresAt,
      }),
    );
  }
  async function callback(url: string, expected: number) {
    if (url.length > 4096 || /[\u0000-\u0020\\]/.test(url))
      throw new Error("Invalid authentication callback");
    const incoming = new URL(url);
    if (
      incoming.protocol !== redirect.protocol ||
      incoming.host !== redirect.host ||
      incoming.pathname !== redirect.pathname ||
      incoming.username ||
      incoming.password ||
      incoming.hash
    )
      throw new Error("Invalid authentication callback");
    const raw = await options.storage.getItem("oauth-flow");
    const flow = raw ? (JSON.parse(raw) as OAuthFlow) : null;
    if (
      !flow ||
      flow.environment !== options.environment ||
      flow.expiresAt <= now() ||
      incoming.searchParams.get("flow") !== flow.nonce
    )
      throw new Error("Unexpected or expired authentication callback");
    if (incoming.searchParams.get("error")) {
      await options.storage.removeItem("oauth-flow");
      throw new Error("Authentication provider declined sign-in");
    }
    const code = incoming.searchParams.get("code");
    if (
      !code ||
      incoming.searchParams.getAll("code").length !== 1 ||
      incoming.searchParams.getAll("flow").length !== 1
    )
      throw new Error("Invalid authentication callback code");
    // One-time consumption, including failed exchanges. Restart login after an uncertain exchange.
    await options.storage.removeItem("oauth-flow");
    return adopt(
      checked(await options.auth.exchangeCodeForSession(code)).session,
      expected,
    );
  }
  async function oauth(
    provider: OAuthProvider,
    link: boolean,
    expected: number,
  ) {
    const session = await getSession();
    if (link && !session?.user.is_anonymous)
      throw new Error("Guest identity required for account linking");
    if (!link && session) await prepareTransfer(session);
    const nonce = options.randomHex();
    if (!/^[a-f0-9]{64}$/.test(nonce))
      throw new Error("Invalid authentication nonce");
    const callbackUrl = new URL(redirect);
    callbackUrl.searchParams.set("flow", nonce);
    await options.storage.setItem(
      "oauth-flow",
      JSON.stringify({
        nonce,
        expiresAt: now() + 10 * 60 * 1000,
        environment: options.environment,
      }),
    );
    const input: OAuthInput = {
      provider,
      options: {
        redirectTo: callbackUrl.toString(),
        skipBrowserRedirect: true,
      },
    };
    const { url } = checked(
      await (link
        ? options.auth.linkIdentity(input)
        : options.auth.signInWithOAuth(input)),
    );
    if (!url || new URL(url).protocol !== "https:")
      throw new Error("Secure authentication URL unavailable");
    const response = await options.openAuthSession(url, callbackUrl.toString());
    if (expected !== epoch)
      throw new Error("Authentication operation cancelled");
    if (response.type !== "success" || !response.url) {
      await options.storage.removeItem("oauth-flow");
      return "cancelled" as const;
    }
    await callback(response.url, expected);
    return "signed-in" as const;
  }
  return {
    getSession,
    getAccessToken: async () => (await getSession())?.access_token ?? null,
    subscribe: (listener: (session: MobileSession | null) => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    signInAnonymously: () =>
      mutate(async (expected) => {
        loggedOut = false;
        return adopt(
          checked(await options.auth.signInAnonymously()).session,
          expected,
        );
      }),
    signInWithPassword: (email: string, password: string) =>
      mutate(async (expected) => {
        loggedOut = false;
        const before = await getSession();
        if (before) await prepareTransfer(before);
        return adopt(
          checked(await options.auth.signInWithPassword({ email, password }))
            .session,
          expected,
        );
      }),
    /** Signup upgrades a guest in place. Existing-account sign-in uses the transfer flow. */
    signUp: (email: string, password: string) =>
      mutate(async (expected) => {
        loggedOut = false;
        const before = await getSession();
        if (before?.user.is_anonymous) {
          checked(await options.auth.updateUser({ email, password }));
          return getSession();
        }
        return adopt(
          checked(await options.auth.signUp({ email, password })).session,
          expected,
        );
      }),
    signInWithOAuth: (provider: OAuthProvider) =>
      mutate(async (expected) => {
        loggedOut = false;
        return oauth(provider, false, expected);
      }),
    linkWithOAuth: (provider: OAuthProvider) =>
      mutate((expected) => oauth(provider, true, expected)),
    handleCallback: (url: string) =>
      mutate((expected) => callback(url, expected)),
    refreshSession: () =>
      mutate(async (expected) => {
        if (loggedOut) return null;
        return adopt(
          checked(await options.auth.refreshSession()).session,
          expected,
        );
      }, false),
    getPendingTransfer: async () => {
      const pending = await recovery();
      if (!pending) return null;
      return {
        guestId: pending.guestId,
        expiresAt: pending.expiresAt,
        prepared: pending.prepared,
        expired: pending.prepared && pending.expiresAt <= now(),
        destination: current?.user.is_anonymous
          ? null
          : (current?.user ?? null),
      };
    },
    confirmTransfer: (guestWins = false) =>
      mutate(async () => {
        const pending = await recovery();
        const session = await getSession();
        if (!pending?.prepared || pending.expiresAt <= now())
          throw new Error("Guest transfer unavailable or expired");
        if (
          !session ||
          session.user.is_anonymous ||
          session.user.id === pending.guestId
        )
          throw new Error(
            "Sign into the intended permanent account before attaching",
          );
        if (!options.transfer) throw new Error("Guest transfer unavailable");
        const result = await options.transfer.attach({
          token: pending.token,
          accessToken: session.access_token,
          guestWins,
        });
        // An uncertain result keeps this exact capability for an idempotent retry.
        await options.storage.removeItem("transfer");
        return result;
      }),
    signOut: async () => {
      const owner = current?.user.id ?? null;
      epoch++;
      loggedOut = true;
      current = null;
      notify();
      const task = queue
        .catch(() => undefined)
        .then(async () => {
          const errors: unknown[] = [];
          try {
            const result = await options.auth.signOut({ scope: "local" });
            if (result.error) errors.push(new Error(result.error.message));
          } catch (error) {
            errors.push(error);
          }
          try {
            await options.onLogout?.(owner);
          } catch (error) {
            errors.push(error);
          }
          for (const key of [
            "session",
            "session-code-verifier",
            "oauth-flow",
            "transfer",
          ]) {
            try {
              await options.storage.removeItem(key);
            } catch (error) {
              errors.push(error);
            }
          }
          cleanupBlocked = errors.length > 0;
          if (cleanupBlocked)
            throw new Error(
              "Signed out in this process, but local cleanup could not finish. Retry logout before switching accounts.",
            );
        });
      queue = task;
      return task;
    },
  };
}
export type MobileAuthClient = ReturnType<typeof createAuthService>;
export interface AuthClientConfig {
  supabaseUrl: string;
  publishableKey: string;
  environment: string;
  redirectUrl?: string;
  transfer?: TransferAdapter;
  onIdentityChange?: AuthServiceOptions["onIdentityChange"];
  onLogout?: AuthServiceOptions["onLogout"];
  onOperationStateChange?: AuthServiceOptions["onOperationStateChange"];
}
export async function createAuthClient(
  config: AuthClientConfig,
): Promise<MobileAuthClient> {
  const endpoint = new URL(config.supabaseUrl);
  if (
    endpoint.protocol !== "https:" ||
    endpoint.username ||
    endpoint.password ||
    !config.publishableKey
  )
    throw new Error(
      "A configured HTTPS Supabase project and publishable key are required",
    );
  const [supabase, browser, crypto, storage] = await Promise.all([
    import("@supabase/supabase-js"),
    import("expo-web-browser"),
    import("expo-crypto"),
    createNativeSessionStorage(config.environment),
  ]);
  const client = supabase.createClient(
    config.supabaseUrl,
    config.publishableKey,
    {
      auth: {
        storage,
        storageKey: "session",
        flowType: "pkce",
        detectSessionInUrl: false,
        persistSession: true,
        autoRefreshToken: false,
      },
    },
  );
  return createAuthService({
    auth: client.auth as unknown as AuthPort,
    storage,
    environment: config.environment,
    redirectUrl: config.redirectUrl ?? "memoir://auth/callback",
    randomHex: () =>
      [...crypto.getRandomBytes(32)]
        .map((byte) => byte.toString(16).padStart(2, "0"))
        .join(""),
    openAuthSession: (url, redirectUrl) =>
      browser.openAuthSessionAsync(url, redirectUrl),
    transfer: config.transfer,
    onIdentityChange: config.onIdentityChange,
    onLogout: config.onLogout,
    onOperationStateChange: config.onOperationStateChange,
  });
}
