import assert from "node:assert/strict";
import test from "node:test";
import {
  createChunkedSecureStorage,
  type SecureStoreDriver,
} from "../../apps/mobile/src/platform/secure-storage";
function fixture() {
  const values = new Map<string, string>();
  let fail: ((key: string, value: string) => boolean) | undefined;
  const driver: SecureStoreDriver = {
    getItem: async (key) => values.get(key) ?? null,
    setItem: async (key, value) => {
      if (fail?.(key, value)) throw new Error("device locked");
      values.set(key, value);
    },
    removeItem: async (key) => {
      values.delete(key);
    },
  };
  let generation = 0;
  return {
    values,
    driver,
    fail: (f: typeof fail) => {
      fail = f;
    },
    storage: createChunkedSecureStorage(driver, {
      namespace: "test",
      randomId: () => `g${++generation}`,
      chunkBytes: 128,
    }),
  };
}
test("secure auth storage round-trips large unicode session, rotating and cleaning old chunks", async () => {
  const f = fixture();
  const value = "token-中文😀".repeat(1000);
  await f.storage.setItem("session", value);
  assert.equal(await f.storage.getItem("session"), value);
  assert.ok([...f.values.values()].every((v) => Buffer.byteLength(v) <= 2048));
  await f.storage.setItem("session", "rotated");
  assert.equal(await f.storage.getItem("session"), "rotated");
  assert.equal(
    [...f.values.keys()].filter((k) => k.includes(".g1.")).length,
    0,
  );
  await f.storage.removeItem("session");
  assert.equal(await f.storage.getItem("session"), null);
  assert.equal(f.values.size, 0);
});
test("failed chunk or manifest write never replaces acknowledged auth session", async () => {
  const f = fixture();
  await f.storage.setItem("session", "old");
  f.fail((k) => k.endsWith(".g2.1"));
  await assert.rejects(
    f.storage.setItem("session", "new".repeat(300)),
    /locked/,
  );
  f.fail(undefined);
  assert.equal(await f.storage.getItem("session"), "old");
  f.fail((k, v) => k.endsWith(".head") && v.includes("g3"));
  await assert.rejects(f.storage.setItem("session", "next"), /locked/);
  f.fail(undefined);
  assert.equal(await f.storage.getItem("session"), "old");
});
test("concurrent session rotations serialize and missing chunks fail closed", async () => {
  const f = fixture();
  await Promise.all([
    f.storage.setItem("session", "a"),
    f.storage.setItem("session", "b"),
  ]);
  assert.equal(await f.storage.getItem("session"), "b");
  f.values.delete("test.session.g2.0");
  await assert.rejects(f.storage.getItem("session"), /incomplete/i);
});
test("interrupted rotation is recovered on a fresh adapter and clear removes all generations", async () => {
  const f = fixture();
  await f.storage.setItem("session", "old");
  f.values.set(
    "test.session.journal",
    JSON.stringify([
      { generation: "g1", chunks: 1 },
      { generation: "g2", chunks: 2 },
    ]),
  );
  f.values.set("test.session.g2.0", "unfinished");
  const restarted = createChunkedSecureStorage(f.driver, {
    namespace: "test",
    randomId: () => "g3",
  });
  assert.equal(await restarted.getItem("session"), "old");
  assert.equal(f.values.has("test.session.g2.0"), false);
  await restarted.removeItem("session");
  assert.equal(f.values.size, 0);
});
test("failed logout cleanup keeps a tombstone so a restarted reader never restores credentials", async () => {
  const f = fixture();
  await f.storage.setItem("session", "private");
  const remove = f.driver.removeItem;
  f.driver.removeItem = async (key) => {
    if (key.endsWith(".g1.0")) throw new Error("cleanup denied");
    await remove(key);
  };
  await assert.rejects(f.storage.removeItem("session"), /cleanup denied/);
  assert.equal(f.values.has("test.session.head"), false);
  f.driver.removeItem = remove;
  const restarted = createChunkedSecureStorage(f.driver, {
    namespace: "test",
    randomId: () => "g9",
  });
  assert.equal(await restarted.getItem("session"), null);
  assert.equal(f.values.size, 0);
});
