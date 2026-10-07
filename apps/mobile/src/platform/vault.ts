import { createNativeSecureDriver } from "./secure-storage";
export type SqlValue = string | number | null;
export interface SqlDatabase {
  execAsync(sql: string): Promise<void>;
  runAsync(sql: string, ...values: SqlValue[]): Promise<unknown>;
  getFirstAsync<T>(sql: string, ...values: SqlValue[]): Promise<T | null>;
  getAllAsync<T>(sql: string, ...values: SqlValue[]): Promise<T[]>;
  withExclusiveTransactionAsync(
    task: (transaction: SqlDatabase) => Promise<void>,
  ): Promise<void>;
  closeAsync(): Promise<void>;
}
export interface Vault {
  readonly owner: string;
  get<T = unknown>(key: string): Promise<T | null>;
  set(key: string, value: unknown): Promise<void>;
  delete(key: string): Promise<void>;
  cacheGet<T = unknown>(key: string): Promise<T | null>;
  cacheSet(key: string, value: unknown): Promise<void>;
  cacheDelete(key: string): Promise<void>;
  listOutbox<T = unknown>(): Promise<{ id: string; value: T }[]>;
  listComposers(): Promise<{ projectId: string; text: string }[]>;
  putOutbox(id: string, value: unknown): Promise<void>;
  deleteOutbox(id: string): Promise<void>;
  saveMedia(id: string, value: unknown): Promise<void>;
  deleteMedia(id: string): Promise<void>;
  /** Revokes this handle immediately, erases local content and native key. */
  clear(): Promise<void>;
  /** Revokes this handle without deleting acknowledged local work. */
  close(): Promise<void>;
}
const MAX_VALUE_BYTES = 2 * 1024 * 1024;
const MAX_OUTBOX = 500;
const forbidden =
  /^(access[_-]?token|refresh[_-]?token|authorization|password|client[_-]?secret|transfer[_-]?token)$/i;
function encode(value: unknown): string {
  const encoded = JSON.stringify(value, (key, item: unknown) => {
    if (forbidden.test(key))
      throw new Error("Credentials must never enter the content vault");
    return item;
  });
  if (
    encoded === undefined ||
    new TextEncoder().encode(encoded).length > MAX_VALUE_BYTES
  )
    throw new Error("Local value exceeds vault limit");
  return encoded;
}
function validateOwner(owner: string) {
  if (!owner || owner.length > 200) throw new Error("Invalid vault owner");
}
function validateKey(key: string) {
  if (!key || key.length > 256) throw new Error("Invalid vault key");
}
function owned(owner: string, value: unknown) {
  if (value && typeof value === "object") {
    if (
      ("owner_id" in value && value.owner_id !== owner) ||
      ("ownerId" in value && value.ownerId !== owner)
    )
      throw new Error("Outbox owner mismatch");
  }
}
interface Backend {
  get(bucket: string, key: string): Promise<string | null>;
  set(bucket: string, key: string, value: string): Promise<void>;
  delete(bucket: string, key: string): Promise<void>;
  list(
    bucket: string,
    prefix?: string,
  ): Promise<{ key: string; value: string }[]>;
  batch(
    changes: { bucket: string; key: string; value: string | null }[],
  ): Promise<void>;
  clear(): Promise<void>;
  close(): Promise<void>;
}
function vaultHandle(owner: string, backend: Backend): Vault {
  let revoked = false;
  let queue: Promise<unknown> = Promise.resolve();
  let disposal: Promise<void> | undefined;
  let closed = false;
  let cleared = false;
  function operation<T>(fn: () => Promise<T>): Promise<T> {
    if (revoked) return Promise.reject(new Error("Vault closed"));
    const result = queue
      .catch(() => undefined)
      .then(async () => {
        if (revoked) throw new Error("Vault closed");
        const value = await fn();
        if (revoked) throw new Error("Vault closed");
        return value;
      });
    queue = result;
    return result;
  }
  const get = <T>(bucket: string, key: string) =>
    operation(async () => {
      validateKey(key);
      const row = await backend.get(bucket, key);
      return row === null ? null : (JSON.parse(row) as T);
    });
  const set = (bucket: string, key: string, value: unknown) =>
    operation(async () => {
      validateKey(key);
      await backend.set(bucket, key, encode(value));
    });
  const remove = (bucket: string, key: string) =>
    operation(async () => {
      validateKey(key);
      await backend.delete(bucket, key);
    });
  function dispose(clear: boolean) {
    revoked = true;
    // Each call joins the prior attempt, but a rejected attempt never poisons
    // future cleanup. Revocation is permanent even while cleanup needs a retry.
    const attempt = (disposal ?? queue)
      .catch(() => undefined)
      .then(async () => {
        if (cleared) return;
        if (clear) {
          await backend.clear();
          cleared = true;
          closed = true;
        } else if (!closed) {
          await backend.close();
          closed = true;
        }
      });
    disposal = attempt;
    return attempt;
  }

  return {
    owner,
    get: (key) => get("draft", key),
    set: (key, value) => set("draft", key, value),
    delete: (key) => remove("draft", key),
    cacheGet: (key) => get("cache", key),
    cacheSet: (key, value) => set("cache", key, value),
    cacheDelete: (key) => remove("cache", key),
    listOutbox: <T>() =>
      operation(async () =>
        (await backend.list("outbox")).map((row) => ({
          id: row.key,
          value: JSON.parse(row.value) as T,
        })),
      ),
    listComposers: () =>
      operation(async () => {
        const prefix = "composer:";
        const rows = await backend.list("draft", prefix);
        const composers: { projectId: string; text: string }[] = [];
        for (const row of rows) {
          // Backend filtering keeps unrelated media out of memory. Recheck the
          // prefix at this boundary and retain exact draft text for recovery.
          if (!row.key.startsWith(prefix)) continue;
          const projectId = row.key.slice(prefix.length);
          const text: unknown = JSON.parse(row.value);
          if (projectId && typeof text === "string" && text.trim())
            composers.push({ projectId, text });
        }
        return composers.sort((a, b) =>
          a.projectId < b.projectId ? -1 : a.projectId > b.projectId ? 1 : 0,
        );
      }),
    putOutbox: (id, value) =>
      operation(async () => {
        validateKey(id);
        owned(owner, value);
        const encoded = encode(value);
        if (
          (await backend.list("outbox")).length >= MAX_OUTBOX &&
          (await backend.get("outbox", id)) === null
        )
          throw new Error("Outbox full; sync or discard an existing item");
        await backend.set("outbox", id, encoded);
      }),
    deleteOutbox: (id) => remove("outbox", id),
    saveMedia: (id, value) =>
      operation(async () => {
        validateKey(id);
        if (
          !value ||
          typeof value !== "object" ||
          !("ownerId" in value) ||
          value.ownerId !== owner
        )
          throw new Error("Media owner mismatch");
        const encoded = encode(value);
        const key = `media.${id}`;
        const original = await backend.get("draft", key);
        if (original !== null && original !== encoded)
          throw new Error("Original media is immutable");
        const index = JSON.parse(
          (await backend.get("draft", "media.index")) ?? "[]",
        ) as string[];
        if (
          !Array.isArray(index) ||
          !index.every((item) => typeof item === "string")
        )
          throw new Error("Invalid media index");
        if (!index.includes(id)) index.push(id);
        if (index.length > 20)
          throw new Error(
            "Local media limit reached; remove a saved recording or photo first",
          );
        await backend.batch([
          { bucket: "draft", key, value: encoded },
          { bucket: "draft", key: "media.index", value: JSON.stringify(index) },
        ]);
      }),
    deleteMedia: (id) =>
      operation(async () => {
        validateKey(id);
        const index = JSON.parse(
          (await backend.get("draft", "media.index")) ?? "[]",
        ) as string[];
        if (
          !Array.isArray(index) ||
          !index.every((item) => typeof item === "string")
        )
          throw new Error("Invalid media index");
        await backend.batch([
          { bucket: "draft", key: `media.${id}`, value: null },
          {
            bucket: "draft",
            key: "media.index",
            value: JSON.stringify(index.filter((item) => item !== id)),
          },
        ]);
      }),
    clear: () => dispose(true),
    close: () => dispose(false),
  };
}
export interface VaultDestruction {
  removeKey(): Promise<void>;
  deleteDatabase(): Promise<void>;
}
export async function openEncryptedVault(
  owner: string,
  database: SqlDatabase,
  key: string,
  destroy?: (() => Promise<void>) | VaultDestruction,
): Promise<Vault> {
  validateOwner(owner);
  if (!/^[a-f0-9]{64}$/.test(key)) throw new Error("Invalid vault key");
  try {
    // Only generated, validated hex is interpolated. All application data uses bindings.
    await database.execAsync(`PRAGMA key = "x'${key}'"`);
    const cipher = await database.getFirstAsync<{ cipher_version?: string }>(
      "PRAGMA cipher_version",
    );
    if (!cipher?.cipher_version)
      throw new Error(
        "SQLCipher unavailable. Use a native development build; Expo Go cannot store private data.",
      );
    // A wrong/missing key must fail here, rather than replace an existing database.
    await database.getFirstAsync("SELECT count(*) FROM sqlite_master");
    await database.execAsync(
      "PRAGMA secure_delete = ON; PRAGMA journal_mode = WAL;",
    );
    await database.withExclusiveTransactionAsync(async (transaction) => {
      await transaction.execAsync(
        "CREATE TABLE IF NOT EXISTS vault (owner TEXT NOT NULL, bucket TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY (owner, bucket, key)); PRAGMA user_version = 1;",
      );
    });
  } catch (error) {
    await database.closeAsync();
    throw error;
  }
  let rowsDeleted = false;
  let checkpointed = false;
  let connectionClosed = false;
  let closeAttempted = false;
  let keyRemoved = false;
  let filesDeleted = false;
  async function closeConnection() {
    if (connectionClosed) return;
    closeAttempted = true;
    try {
      await database.closeAsync();
    } catch (error) {
      // Expo may close the native handle before its promise rejects. A later
      // close reports this exact native error and confirms the desired state.
      if (
        !(error instanceof Error) ||
        !error.message.includes("Access to closed resource")
      )
        throw error;
    }
    connectionClosed = true;
  }
  const backend: Backend = {
    get: async (bucket, key) =>
      (
        await database.getFirstAsync<{ value: string }>(
          "SELECT value FROM vault WHERE owner=? AND bucket=? AND key=?",
          owner,
          bucket,
          key,
        )
      )?.value ?? null,
    set: async (bucket, key, value) =>
      database.withExclusiveTransactionAsync(async (transaction) => {
        await transaction.runAsync(
          "INSERT INTO vault(owner,bucket,key,value) VALUES(?,?,?,?) ON CONFLICT(owner,bucket,key) DO UPDATE SET value=excluded.value",
          owner,
          bucket,
          key,
          value,
        );
      }),
    delete: async (bucket, key) =>
      database.withExclusiveTransactionAsync(async (transaction) => {
        await transaction.runAsync(
          "DELETE FROM vault WHERE owner=? AND bucket=? AND key=?",
          owner,
          bucket,
          key,
        );
      }),
    list: (bucket, prefix) =>
      prefix === undefined
        ? database.getAllAsync(
            "SELECT key,value FROM vault WHERE owner=? AND bucket=? ORDER BY key",
            owner,
            bucket,
          )
        : database.getAllAsync(
            "SELECT key,value FROM vault WHERE owner=? AND bucket=? AND substr(key,1,length(?))=? ORDER BY key",
            owner,
            bucket,
            prefix,
            prefix,
          ),
    batch: (changes) =>
      database.withExclusiveTransactionAsync(async (transaction) => {
        for (const change of changes) {
          if (change.value === null)
            await transaction.runAsync(
              "DELETE FROM vault WHERE owner=? AND bucket=? AND key=?",
              owner,
              change.bucket,
              change.key,
            );
          else
            await transaction.runAsync(
              "INSERT INTO vault(owner,bucket,key,value) VALUES(?,?,?,?) ON CONFLICT(owner,bucket,key) DO UPDATE SET value=excluded.value",
              owner,
              change.bucket,
              change.key,
              change.value,
            );
        }
      }),
    clear: async () => {
      if (closeAttempted && !connectionClosed) await closeConnection();
      if (!connectionClosed) {
        if (!rowsDeleted) {
          await database.withExclusiveTransactionAsync(async (transaction) => {
            await transaction.runAsync(
              "DELETE FROM vault WHERE owner=?",
              owner,
            );
          });
          rowsDeleted = true;
        }
        if (!checkpointed) {
          await database.execAsync("PRAGMA wal_checkpoint(TRUNCATE)");
          checkpointed = true;
        }
        await closeConnection();
      }
      // A previously closed native vault can still be cryptographically erased.
      if (!rowsDeleted && !destroy)
        throw new Error(
          "Closed vault requires its native destruction adapter to clear retained content",
        );
      if (typeof destroy === "function") {
        if (!filesDeleted) {
          await destroy();
          filesDeleted = true;
        }
      } else if (destroy) {
        if (!keyRemoved) {
          await destroy.removeKey();
          keyRemoved = true;
        }
        if (!filesDeleted) {
          await destroy.deleteDatabase();
          filesDeleted = true;
        }
      }
    },
    close: closeConnection,
  };
  return vaultHandle(owner, backend);
}
export type VaultEnvironment =
  | "native"
  | "fixture"
  | "web"
  | { platform: "native" | "fixture" | "web"; namespace: string };
export async function createVault(
  owner: string,
  environment: VaultEnvironment,
): Promise<Vault> {
  validateOwner(owner);
  const platform =
    typeof environment === "string" ? environment : environment.platform;
  const namespace =
    typeof environment === "string" ? "default" : environment.namespace;
  if (!/^[A-Za-z0-9_.-]{1,80}$/.test(namespace))
    throw new Error("Invalid vault environment");
  if (platform === "web")
    throw new Error(
      "Web private persistence is disabled. Use explicit fixture mode for synthetic data.",
    );
  if (platform === "fixture") {
    const buckets = new Map<string, Map<string, string>>();
    const bucket = (name: string) => {
      if (!buckets.has(name)) buckets.set(name, new Map());
      return buckets.get(name)!;
    };
    return vaultHandle(owner, {
      get: async (name, key) => bucket(name).get(key) ?? null,
      set: async (name, key, value) => {
        bucket(name).set(key, value);
      },
      delete: async (name, key) => {
        bucket(name).delete(key);
      },
      list: async (name, prefix) =>
        [...bucket(name)]
          .filter(([key]) => prefix === undefined || key.startsWith(prefix))
          .map(([key, value]) => ({ key, value })),
      batch: async (changes) => {
        for (const change of changes) {
          if (change.value === null) bucket(change.bucket).delete(change.key);
          else bucket(change.bucket).set(change.key, change.value);
        }
      },
      clear: async () => {
        buckets.clear();
      },
      close: async () => {
        buckets.clear();
      },
    });
  }
  const [sqlite, crypto, secure] = await Promise.all([
    import("expo-sqlite"),
    import("expo-crypto"),
    createNativeSecureDriver(),
  ]);
  const digest = await crypto.digestStringAsync(
    crypto.CryptoDigestAlgorithm.SHA256,
    `${namespace}:${owner}`,
  );
  const name = `memoir-${digest}.db`;
  const keyName = `memoir.${namespace}.vault.${digest}`;
  let key = await secure.getItem(keyName);
  if (!key) {
    // Only generate for a missing file. Re-keying existing data would destroy recovery.
    const { File } = await import("expo-file-system");
    if (new File(sqlite.defaultDatabaseDirectory, name).exists)
      throw new Error(
        "Local vault key missing. Local data is locked; restore the account or explicitly discard it.",
      );
    key = [...(await crypto.getRandomBytesAsync(32))]
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("");
    await secure.setItem(keyName, key);
  }
  const db = await sqlite.openDatabaseAsync(name, { useNewConnection: true });
  // Expo's exclusive transaction helper opens another connection, which has no
  // SQLCipher key. Keep this private keyed connection and serialize every caller
  // through vaultHandle, with an explicit transaction on the SAME connection.
  const driver: SqlDatabase = {
    execAsync: (sql) => db.execAsync(sql),
    runAsync: (sql, ...values) => db.runAsync(sql, ...values),
    getFirstAsync: (sql, ...values) => db.getFirstAsync(sql, ...values),
    getAllAsync: (sql, ...values) => db.getAllAsync(sql, ...values),
    closeAsync: () => db.closeAsync(),
    withExclusiveTransactionAsync: async (task) => {
      await db.execAsync("BEGIN IMMEDIATE");
      try {
        await task(driver);
        await db.execAsync("COMMIT");
      } catch (error) {
        await db.execAsync("ROLLBACK");
        throw error;
      }
    },
  };
  return openEncryptedVault(owner, driver, key, {
    removeKey: () => secure.removeItem(keyName),
    deleteDatabase: async () => {
      const { File } = await import("expo-file-system");
      // Repeating a failed/uncertain deletion must tolerate an already-gone file.
      if (new File(sqlite.defaultDatabaseDirectory, name).exists)
        await sqlite.deleteDatabaseAsync(name);
      for (const suffix of ["-wal", "-shm"]) {
        const sidecar = new File(
          sqlite.defaultDatabaseDirectory,
          `${name}${suffix}`,
        );
        if (sidecar.exists) sidecar.delete();
      }
    },
  });
}
