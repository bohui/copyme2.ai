import assert from "node:assert/strict";
import test from "node:test";
import {
  createAuthService,
  type AuthPort,
  type MobileSession,
} from "../../apps/mobile/src/auth/client";
const guest: MobileSession = {
  access_token: "guest-access",
  refresh_token: "guest-refresh",
  user: { id: "guest", is_anonymous: true },
};
const owner: MobileSession = {
  access_token: "owner-access",
  refresh_token: "owner-refresh",
  user: { id: "owner", email: "reader@example.test", is_anonymous: false },
};
function setup() {
  let current: MobileSession | null = guest;
  const values = new Map<string, string>();
  const calls: string[] = [];
  let failPrepare = false;
  const ok = () => ({ data: { session: current }, error: null });
  const auth: AuthPort = {
    getSession: async () => ok(),
    signInAnonymously: async () => ok(),
    signInWithPassword: async () => {
      calls.push("signin");
      current = owner;
      return ok();
    },
    signUp: async () => ok(),
    updateUser: async () => ({ data: { user: guest.user }, error: null }),
    signInWithOAuth: async (input) => ({
      data: {
        url: `https://auth.example.test/authorize?redirect_to=${encodeURIComponent(input.options.redirectTo)}`,
      },
      error: null,
    }),
    linkIdentity: async (input) => ({
      data: {
        url: `https://auth.example.test/authorize?redirect_to=${encodeURIComponent(input.options.redirectTo)}`,
      },
      error: null,
    }),
    exchangeCodeForSession: async () => {
      calls.push("exchange");
      current = owner;
      return ok();
    },
    signOut: async () => {
      current = null;
      calls.push("logout");
      return { error: null };
    },
    refreshSession: async () => ok(),
  };
  const service = createAuthService({
    auth,
    storage: {
      getItem: async (k) => values.get(k) ?? null,
      setItem: async (k, v) => {
        values.set(k, v);
      },
      removeItem: async (k) => {
        values.delete(k);
      },
    },
    environment: "test",
    redirectUrl: "memoir://auth/callback",
    randomHex: () => "a".repeat(64),
    now: () => 1000,
    openAuthSession: async () => ({ type: "cancel" }),
    transfer: {
      prepare: async () => {
        calls.push("prepare");
        if (failPrepare) throw new Error("offline");
        return { expiresAt: 10000 };
      },
      attach: async () => {
        calls.push("attach");
        return { attached: true };
      },
    },
    onIdentityChange: async (a, b) => {
      calls.push(`owner:${a}:${b}`);
    },
    onLogout: async () => {
      calls.push("cleanup");
    },
  });
  return {
    service,
    calls,
    values,
    failPrepare: () => {
      failPrepare = true;
    },
  };
}
test("existing login prepares guest transfer before replacement and requires explicit attach", async () => {
  const f = setup();
  await f.service.signInWithPassword("a@example.test", "password");
  assert.ok(f.calls.indexOf("prepare") < f.calls.indexOf("signin"));
  assert.equal(f.calls.includes("attach"), false);
  assert.equal((await f.service.getPendingTransfer())?.guestId, "guest");
  await f.service.confirmTransfer();
  assert.equal(f.calls.includes("attach"), true);
  assert.equal(await f.service.getPendingTransfer(), null);
});
test("failed transfer preparation leaves guest authenticated and never calls existing login", async () => {
  const f = setup();
  f.failPrepare();
  await assert.rejects(
    f.service.signInWithPassword("a@example.test", "password"),
    /offline/,
  );
  assert.equal(f.calls.includes("signin"), false);
  assert.equal((await f.service.getSession())?.user.id, "guest");
});
test("cancelled OAuth preserves recoverable guest, wrong callback host and unsolicited code rejected", async () => {
  const f = setup();
  assert.equal(await f.service.signInWithOAuth("google"), "cancelled");
  assert.equal((await f.service.getSession())?.user.id, "guest");
  await assert.rejects(
    f.service.handleCallback("evil://auth/callback?code=abc&flow=aaa"),
    /callback/i,
  );
  await assert.rejects(
    f.service.handleCallback("memoir://auth/callback?code=abc&flow=aaa"),
    /callback/i,
  );
});
test("logout invokes local owner cleanup and clears capability and session slots", async () => {
  const f = setup();
  await f.service.signInWithPassword("a@example.test", "password");
  await f.service.signOut();
  assert.equal(await f.service.getSession(), null);
  assert.equal(f.values.size, 0);
  assert.ok(f.calls.includes("cleanup"));
});
test("callback is bound to persisted nonce and consumed once before exchange", async () => {
  const f = setup();
  f.values.set(
    "oauth-flow",
    JSON.stringify({ nonce: "nonce", expiresAt: 10000, environment: "test" }),
  );
  await assert.rejects(
    f.service.handleCallback("memoir://other/callback?code=a&flow=nonce"),
    /callback/,
  );
  assert.equal(f.calls.includes("exchange"), false);
  assert.equal(
    (await f.service.handleCallback("memoir://auth/callback?code=a&flow=nonce"))
      ?.user.id,
    "owner",
  );
  await assert.rejects(
    f.service.handleCallback("memoir://auth/callback?code=a&flow=nonce"),
    /callback/,
  );
  assert.equal(f.calls.filter((c) => c === "exchange").length, 1);
});
test("callback rejects fragments containing bearer credentials", async () => {
  const f = setup();
  f.values.set(
    "oauth-flow",
    JSON.stringify({ nonce: "nonce", expiresAt: 10000, environment: "test" }),
  );
  await assert.rejects(
    f.service.handleCallback(
      "memoir://auth/callback?code=a&flow=nonce#access_token=secret",
    ),
    /callback/,
  );
  assert.equal(f.calls.includes("exchange"), false);
});
