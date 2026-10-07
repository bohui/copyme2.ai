/** Tokens and transfer capabilities belong here, never in the content vault. */
export interface SecureStoreDriver {
  getItem(key: string): Promise<string | null>;
  setItem(key: string, value: string): Promise<void>;
  removeItem(key: string): Promise<void>;
}
interface Manifest {
  generation: string;
  chunks: number;
}
export interface ChunkedStorageOptions {
  namespace: string;
  randomId(): string;
  chunkBytes?: number;
}
const MAX_CHUNKS = 4096;
const safe = /^[A-Za-z0-9_.-]+$/;
function manifest(value: unknown): Manifest {
  const item = value as Partial<Manifest> | null;
  if (
    !item ||
    typeof item.generation !== "string" ||
    !safe.test(item.generation) ||
    !Number.isInteger(item.chunks) ||
    !item.chunks ||
    item.chunks < 1 ||
    item.chunks > MAX_CHUNKS
  )
    throw new Error("Invalid secure storage manifest");
  return item as Manifest;
}
function split(value: string, limit: number): string[] {
  const result: string[] = [];
  let chunk = "";
  let bytes = 0;
  for (const char of value) {
    const point = char.codePointAt(0)!;
    const size =
      point <= 0x7f ? 1 : point <= 0x7ff ? 2 : point <= 0xffff ? 3 : 4;
    if (bytes + size > limit) {
      result.push(chunk);
      chunk = "";
      bytes = 0;
    }
    chunk += char;
    bytes += size;
  }
  result.push(chunk);
  return result;
}
/** A journal precedes chunks; one small head write commits a generation atomically.
 * Recovery removes uncommitted/new or superseded chunks without exposing partial tokens.
 * Use one adapter per namespace. Every operation serializes per key, including reads.
 */
export function createChunkedSecureStorage(
  driver: SecureStoreDriver,
  options: ChunkedStorageOptions,
): SecureStoreDriver {
  if (!safe.test(options.namespace))
    throw new Error("Invalid secure namespace");
  const chunkBytes = options.chunkBytes ?? 1500;
  if (chunkBytes < 4 || chunkBytes > 1800)
    throw new Error("Invalid secure chunk size");
  const queues = new Map<string, Promise<unknown>>();
  function serial<T>(
    key: string,
    task: (base: string) => Promise<T>,
  ): Promise<T> {
    if (!safe.test(key) || key.length > 200)
      return Promise.reject(new Error("Invalid secure storage key"));
    const base = `${options.namespace}.${key}`;
    const next = (queues.get(key) ?? Promise.resolve())
      .catch(() => undefined)
      .then(() => task(base));
    queues.set(key, next);
    void next
      .finally(() => {
        if (queues.get(key) === next) queues.delete(key);
      })
      .catch(() => undefined);
    return next;
  }
  async function head(base: string) {
    const raw = await driver.getItem(`${base}.head`);
    return raw === null ? null : manifest(JSON.parse(raw));
  }
  async function removeChunks(base: string, item: Manifest) {
    for (let index = 0; index < item.chunks; index++)
      await driver.removeItem(`${base}.${item.generation}.${index}`);
  }
  async function recover(base: string) {
    const current = await head(base);
    const raw = await driver.getItem(`${base}.journal`);
    if (raw !== null) {
      const entries: unknown = JSON.parse(raw);
      if (!Array.isArray(entries) || entries.length > 2)
        throw new Error("Invalid secure storage journal");
      for (const entry of entries) {
        const item = manifest(entry);
        if (item.generation !== current?.generation)
          await removeChunks(base, item);
      }
      await driver.removeItem(`${base}.journal`);
    }
    return current;
  }
  return {
    getItem: (key) =>
      serial(key, async (base) => {
        const current = await recover(base);
        if (!current) return null;
        const chunks: string[] = [];
        for (let index = 0; index < current.chunks; index++) {
          const chunk = await driver.getItem(
            `${base}.${current.generation}.${index}`,
          );
          if (chunk === null)
            throw new Error(
              "Secure session incomplete; sign in again without replacing local work",
            );
          chunks.push(chunk);
        }
        return chunks.join("");
      }),
    setItem: (key, value) =>
      serial(key, async (base) => {
        const previous = await recover(base);
        const chunks = split(value, chunkBytes);
        if (chunks.length > MAX_CHUNKS)
          throw new Error("Secure session too large");
        const next = manifest({
          generation: options.randomId(),
          chunks: chunks.length,
        });
        if (next.generation === previous?.generation)
          throw new Error("Secure generation must rotate");
        await driver.setItem(
          `${base}.journal`,
          JSON.stringify(previous ? [previous, next] : [next]),
        );
        for (const [index, chunk] of chunks.entries())
          await driver.setItem(`${base}.${next.generation}.${index}`, chunk);
        await driver.setItem(`${base}.head`, JSON.stringify(next));
        if (previous) await removeChunks(base, previous);
        await driver.removeItem(`${base}.journal`);
      }),
    removeItem: (key) =>
      serial(key, async (base) => {
        const current = await recover(base);
        if (current) {
          await driver.setItem(`${base}.journal`, JSON.stringify([current]));
          // Removing the head is the logout commit point. Cleanup remains retryable.
          await driver.removeItem(`${base}.head`);
          await removeChunks(base, current);
        }
        await driver.removeItem(`${base}.journal`);
      }),
  };
}
export async function createNativeSecureDriver(): Promise<SecureStoreDriver> {
  const store = await import("expo-secure-store");
  if (!(await store.isAvailableAsync()))
    throw new Error("Native secure storage unavailable");
  const options = { keychainAccessible: store.WHEN_UNLOCKED_THIS_DEVICE_ONLY };
  return {
    getItem: (key) => store.getItemAsync(key, options),
    setItem: (key, value) => store.setItemAsync(key, value, options),
    removeItem: (key) => store.deleteItemAsync(key, options),
  };
}
export async function createNativeSessionStorage(environment: string) {
  const [driver, crypto] = await Promise.all([
    createNativeSecureDriver(),
    import("expo-crypto"),
  ]);
  return createChunkedSecureStorage(driver, {
    namespace: `memoir.${environment}.auth`,
    randomId: () => crypto.randomUUID(),
  });
}
