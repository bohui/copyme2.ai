import assert from "node:assert/strict";
import test from "node:test";
import { DatabaseSync } from "node:sqlite";
import {
  createVault,
  openEncryptedVault,
  type SqlDatabase,
} from "../../apps/mobile/src/platform/vault";
function database(cipher: boolean) {
  const db = new DatabaseSync(":memory:");
  const statements: string[] = [];
  const driver: SqlDatabase = {
    execAsync: async (sql) => {
      statements.push(sql);
      db.exec(sql);
    },
    runAsync: async (sql, ...values) => db.prepare(sql).run(...values),
    getFirstAsync: async <T>(
      sql: string,
      ...values: (string | number | null)[]
    ) =>
      sql === "PRAGMA cipher_version"
        ? ((cipher ? { cipher_version: "4.6.1" } : null) as T | null)
        : ((db.prepare(sql).get(...values) ?? null) as T | null),
    getAllAsync: async <T>(
      sql: string,
      ...values: (string | number | null)[]
    ) => db.prepare(sql).all(...values) as T[],
    withExclusiveTransactionAsync: async (task) => {
      db.exec("BEGIN");
      try {
        await task(driver);
        db.exec("COMMIT");
      } catch (e) {
        db.exec("ROLLBACK");
        throw e;
      }
    },
    closeAsync: async () => db.close(),
  };
  return { driver, statements };
}
test("native vault refuses ordinary SQLite before creating content schema", async () => {
  const f = database(false);
  await assert.rejects(
    openEncryptedVault("alice", f.driver, "a".repeat(64)),
    /SQLCipher/,
  );
  assert.ok(!f.statements.some((s) => s.includes("CREATE TABLE")));
});
test("vault isolates namespaces, keeps transactional outbox and rejects token persistence", async () => {
  const a = await createVault("alice", "fixture");
  const b = await createVault("bob", "fixture");
  await a.set("draft", { text: "私の物語" });
  assert.equal(await b.get("draft"), null);
  await a.putOutbox("turn1", { owner_id: "alice", state: "queued" });
  assert.equal((await a.listOutbox()).length, 1);
  await assert.rejects(
    a.set("session", { access_token: "secret" }),
    /credential/i,
  );
  await assert.rejects(a.putOutbox("turn2", { owner_id: "bob" }), /owner/i);
  await a.clear();
  await assert.rejects(a.get("draft"), /closed/i);
  assert.equal(await b.get("draft"), null);
});
test("SQLCipher adapter parameterizes data and revokes old handles on logout", async () => {
  const f = database(true);
  const vault = await openEncryptedVault("alice", f.driver, "b".repeat(64));
  await vault.set("draft';DROP TABLE vault;--", { text: "private" });
  assert.deepEqual(await vault.get("draft';DROP TABLE vault;--"), {
    text: "private",
  });
  await vault.cacheSet("history", [1, 2]);
  assert.deepEqual(await vault.cacheGet("history"), [1, 2]);
  await vault.putOutbox("op", { owner_id: "alice" });
  assert.deepEqual(await vault.listOutbox(), [
    { id: "op", value: { owner_id: "alice" } },
  ]);
  await vault.clear();
  await assert.rejects(vault.set("late", "write"), /closed/i);
});
test("web refuses private persistence unless fixture mode explicitly selected", async () => {
  await assert.rejects(createVault("alice", "web"), /fixture/i);
});
test("logout fences operations queued before clear and prevents stale resurrection", async () => {
  const vault = await createVault("alice", "fixture");
  const pending = vault.set("draft", "late");
  const cleanup = vault.clear();
  await assert.rejects(pending, /closed/i);
  await cleanup;
  await assert.rejects(
    vault.putOutbox("late", { owner_id: "alice" }),
    /closed/i,
  );
});
test("media original and recovery manifest commit atomically, including rollback", async () => {
  const f = database(true);
  const vault = await openEncryptedVault("alice", f.driver, "c".repeat(64));
  await f.driver.execAsync(
    "CREATE TRIGGER fail_manifest BEFORE INSERT ON vault WHEN NEW.key='media.index' BEGIN SELECT RAISE(ABORT,'simulated disk full'); END",
  );
  await assert.rejects(
    vault.saveMedia("clip", { ownerId: "alice", id: "clip" }),
    /disk full/,
  );
  assert.equal(await vault.get("media.clip"), null);
  assert.equal(await vault.get("media.index"), null);
  await f.driver.execAsync("DROP TRIGGER fail_manifest");
  await vault.saveMedia("clip", { ownerId: "alice", id: "clip" });
  assert.deepEqual(await vault.get("media.index"), ["clip"]);
  await assert.rejects(
    vault.saveMedia("clip", { ownerId: "alice", id: "clip", changed: true }),
    /immutable/,
  );
  await vault.deleteMedia("clip");
  assert.equal(await vault.get("media.clip"), null);
  assert.deepEqual(await vault.get("media.index"), []);
});
test("outbox rejects portable-domain camelCase owner mismatches too", async () => {
  const vault = await createVault("alice", "fixture");
  await assert.rejects(
    vault.putOutbox("foreign", { ownerId: "bob" }),
    /owner/i,
  );
});

test("vault clear retries every failed cleanup stage without reviving its handle", async () => {
  for (const failureStage of ["delete", "checkpoint", "close", "destroy"]) {
    const f = database(true);
    let fail = true;
    const calls: string[] = [];
    const originalRun = f.driver.runAsync;
    const originalExec = f.driver.execAsync;
    const originalClose = f.driver.closeAsync;
    f.driver.runAsync = async (sql, ...values) => {
      if (sql === "DELETE FROM vault WHERE owner=?") {
        calls.push("delete");
        if (failureStage === "delete" && fail) {
          fail = false;
          throw new Error("injected delete");
        }
      }
      return originalRun(sql, ...values);
    };
    f.driver.execAsync = async (sql) => {
      if (sql === "PRAGMA wal_checkpoint(TRUNCATE)") {
        calls.push("checkpoint");
        if (failureStage === "checkpoint" && fail) {
          fail = false;
          throw new Error("injected checkpoint");
        }
      }
      return originalExec(sql);
    };
    f.driver.closeAsync = async () => {
      calls.push("close");
      if (failureStage === "close" && fail) {
        fail = false;
        throw new Error("injected close");
      }
      return originalClose();
    };
    const vault = await openEncryptedVault(
      "alice",
      f.driver,
      "a".repeat(64),
      async () => {
        calls.push("destroy");
        if (failureStage === "destroy" && fail) {
          fail = false;
          throw new Error("injected destroy");
        }
      },
    );
    await vault.set("draft", "private");
    await assert.rejects(vault.clear(), /injected/);
    await assert.rejects(vault.get("draft"), /closed/);
    await vault.clear();
    await vault.clear();
    assert.equal(
      calls.filter((x) => x === failureStage).length,
      2,
      `${failureStage} must retry`,
    );
    for (const stage of ["delete", "checkpoint", "close", "destroy"].filter(
      (x) => x !== failureStage,
    ))
      assert.equal(
        calls.filter((x) => x === stage).length,
        1,
        `${stage} must not replay after success`,
      );
  }
});

test("vault key and file destruction retry separately after database closure", async () => {
  for (const stage of ["key", "files"]) {
    const f = database(true);
    const calls: string[] = [];
    let fail = true;
    const vault = await openEncryptedVault("alice", f.driver, "b".repeat(64), {
      removeKey: async () => {
        calls.push("key");
        if (stage === "key" && fail) {
          fail = false;
          throw new Error("key unavailable");
        }
      },
      deleteDatabase: async () => {
        calls.push("files");
        if (stage === "files" && fail) {
          fail = false;
          throw new Error("file unavailable");
        }
      },
    });
    await vault.set("draft", "private");
    await assert.rejects(vault.clear(), /unavailable/);
    await assert.rejects(vault.set("late", "data"), /closed/);
    await vault.clear();
    await vault.clear();
    assert.equal(calls.filter((x) => x === stage).length, 2);
    assert.equal(calls.filter((x) => x !== stage).length, 1);
  }
});
test("close can be followed by native cryptographic clear and concurrent retries serialize", async () => {
  const f = database(true);
  let removed = 0;
  let deleted = 0;
  const vault = await openEncryptedVault("alice", f.driver, "b".repeat(64), {
    removeKey: async () => {
      removed++;
    },
    deleteDatabase: async () => {
      deleted++;
    },
  });
  await vault.set("draft", "private");
  await vault.close();
  await Promise.all([vault.clear(), vault.clear(), vault.close()]);
  assert.equal(removed, 1);
  assert.equal(deleted, 1);
  await assert.rejects(vault.get("draft"), /closed/);
});
test("uncertain native close outcome can be confirmed and cleared on retry", async () => {
  const f = database(true);
  const close = f.driver.closeAsync;
  let closed = false;
  let destroyed = 0;
  f.driver.closeAsync = async () => {
    if (closed) throw new Error("Access to closed resource");
    await close();
    closed = true;
    throw new Error("uncertain native close response");
  };
  const vault = await openEncryptedVault(
    "alice",
    f.driver,
    "c".repeat(64),
    async () => {
      destroyed++;
    },
  );
  await assert.rejects(vault.clear(), /uncertain/);
  await vault.clear();
  assert.equal(destroyed, 1);
});

test("listComposers discovers nonempty drafts across projects and preserves exact text", async () => {
  const vault = await createVault("alice", "fixture");
  await vault.set("composer:project-two", " 第二个项目草稿 ");
  await vault.set("composer:project-one", "First project draft");
  await vault.set("composer:blank", " \n\t ");
  await vault.set("composer:empty", "");
  await vault.set("composer:structured", { text: "Not a composer string" });
  await vault.set("composer:null", null);
  await vault.set("composer:", "No project ID");
  await vault.set("unrelated", "Not a composer");
  assert.deepEqual(await vault.listComposers(), [
    { projectId: "project-one", text: "First project draft" },
    { projectId: "project-two", text: " 第二个项目草稿 " },
  ]);
  await vault.close();
  await assert.rejects(vault.listComposers(), /closed/);
});

test("listComposers filters owner and prefix in SQL before materializing unrelated media", async () => {
  const f = database(true);
  const vault = await openEncryptedVault("alice", f.driver, "d".repeat(64));
  await vault.set("composer:project';--", "Private Alice draft");
  await f.driver.runAsync(
    "INSERT INTO vault(owner,bucket,key,value) VALUES(?,?,?,?)",
    "bob",
    "draft",
    "composer:foreign",
    JSON.stringify("Other owner text"),
  );
  // Invalid unrelated JSON would throw if enumeration fetched/decoded all rows.
  await f.driver.runAsync(
    "INSERT INTO vault(owner,bucket,key,value) VALUES(?,?,?,?)",
    "alice",
    "draft",
    "media.large",
    "not JSON",
  );
  await f.driver.runAsync(
    "INSERT INTO vault(owner,bucket,key,value) VALUES(?,?,?,?)",
    "bob",
    "draft",
    "media.foreign",
    "not JSON",
  );
  await f.driver.runAsync(
    "INSERT INTO vault(owner,bucket,key,value) VALUES(?,?,?,?)",
    "alice",
    "cache",
    "composer:cached",
    JSON.stringify("Not a draft"),
  );
  const original = f.driver.getAllAsync;
  let rowsRead = 0;
  let bindings: (string | number | null)[] = [];
  f.driver.getAllAsync = async <T>(
    sql: string,
    ...values: (string | number | null)[]
  ) => {
    bindings = values;
    const result = await original<T>(sql, ...values);
    rowsRead += result.length;
    return result;
  };
  assert.deepEqual(await vault.listComposers(), [
    { projectId: "project';--", text: "Private Alice draft" },
  ]);
  assert.equal(rowsRead, 1);
  assert.ok(bindings.includes("alice"));
  assert.ok(bindings.includes("composer:"));
  await vault.clear();
  await assert.rejects(vault.listComposers(), /closed/);
});

test("listComposers remains scoped to a separate fixture owner and environment", async () => {
  const alice = await createVault("alice", {
    platform: "fixture",
    namespace: "staging",
  });
  const bob = await createVault("bob", {
    platform: "fixture",
    namespace: "staging",
  });
  const production = await createVault("alice", {
    platform: "fixture",
    namespace: "production",
  });
  await alice.set("composer:project", "Staging Alice text");
  assert.deepEqual(await bob.listComposers(), []);
  assert.deepEqual(await production.listComposers(), []);
});
