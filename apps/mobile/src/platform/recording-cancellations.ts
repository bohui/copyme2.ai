import type { MemoirApi } from "@memoir/api-client";
import type { Vault } from "./vault";
interface Cancellation {
  uploadKey: string;
  recordingId?: string;
}
const key = "recording-cancellations";
const mutations = new WeakMap<Vault, Promise<unknown>>();
function update(
  vault: Vault,
  change: (pending: Cancellation[]) => Cancellation[],
) {
  const next = (mutations.get(vault) ?? Promise.resolve())
    .catch(() => undefined)
    .then(async () => {
      const pending = (await vault.get<Cancellation[]>(key)) ?? [];
      if (!Array.isArray(pending) || pending.length > 20)
        throw new Error("Invalid recording cancellation queue");
      const result = change(pending);
      if (result.length > 20)
        throw new Error(
          "Recording cancellation queue is full; reconnect before discarding another clip",
        );
      if (result.length) await vault.set(key, result);
      else await vault.delete(key);
      return result;
    });
  mutations.set(vault, next);
  return next;
}
/** Persist the capture identity before clearing its encrypted local bytes. */
export async function queueRecordingCancellation(
  vault: Vault,
  uploadKey: string,
  recordingId?: string | null,
) {
  await update(vault, (pending) =>
    pending.some((item) => item.uploadKey === uploadKey)
      ? pending
      : [...pending, { uploadKey, ...(recordingId ? { recordingId } : {}) }],
  );
}
/** Foreground reconciliation only. Network failure retains the encrypted intent. */
export async function retryRecordingCancellations(
  vault: Vault,
  api: MemoirApi,
) {
  const pending = await update(vault, (values) => values);
  for (const item of pending) {
    await api.cancelRecordingUpload(item.uploadKey);
    await update(vault, (values) =>
      values.filter((value) => value.uploadKey !== item.uploadKey),
    );
  }
}
