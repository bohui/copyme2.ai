import type { Vault } from "./vault";
export const MAX_CLIP_BYTES = 1024 * 1024;
export const MAX_CLIP_DURATION_MS = 60_000;
export interface PrivateClip {
  readonly id: string;
  readonly ownerId: string;
  readonly mimeType: string;
  readonly filename: string;
  readonly durationMs: number;
  readonly byteLength: number;
  readonly base64: string;
}
export interface RecorderSnapshot {
  status: "idle" | "recording" | "paused" | "saved" | "error";
  clip: PrivateClip | null;
  error: string | null;
}
export interface RecorderPort {
  requestPermission(): Promise<boolean>;
  start(): Promise<void>;
  pause(): Promise<void>;
  resume(): Promise<void>;
  stop(): Promise<{ uri: string; durationMs: number } | null>;
  seal(uri: string, durationMs: number): Promise<PrivateClip>;
  removeTemporary(uri?: string): Promise<void>;
  discard(clip: PrivateClip): Promise<void>;
  play(clip: PrivateClip): Promise<void>;
  stopPlayback(): Promise<void>;
  release(): Promise<void>;
}
export function assertBoundedClip(clip: PrivateClip) {
  if (
    !["audio/mp4", "audio/m4a", "audio/aac"].includes(clip.mimeType) ||
    !clip.filename.endsWith(".m4a")
  )
    throw new Error("Unsupported audio container");
  if (
    !Number.isFinite(clip.byteLength) ||
    clip.byteLength <= 0 ||
    clip.byteLength > MAX_CLIP_BYTES ||
    !Number.isFinite(clip.durationMs) ||
    clip.durationMs <= 0 ||
    clip.durationMs > MAX_CLIP_DURATION_MS + 1000
  )
    throw new Error("Recording exceeds compatibility limit");
  if (
    !/^[A-Za-z0-9+/]*={0,2}$/.test(clip.base64) ||
    clip.base64.length !== 4 * Math.ceil(clip.byteLength / 3)
  )
    throw new Error("Invalid bounded recording");
}
export async function listSavedClips(vault: Vault): Promise<PrivateClip[]> {
  const index = (await vault.get<string[]>("media.index")) ?? [];
  if (
    !Array.isArray(index) ||
    !index.every((id) => typeof id === "string") ||
    index.length > 20
  )
    throw new Error("Invalid media recovery index");
  const clips: PrivateClip[] = [];
  for (const id of index) {
    const value = await vault.get<PrivateClip>(`media.${id}`);
    if (!value) throw new Error("Saved media is incomplete");
    if (value.ownerId !== vault.owner || value.id !== id)
      throw new Error("Saved media owner mismatch");
    if (value.mimeType.startsWith("audio/")) {
      assertBoundedClip(value);
      clips.push(value);
    }
  }
  return clips;
}
export function createRecorderController(
  ownerId: string,
  port: RecorderPort,
  initialClip: PrivateClip | null = null,
) {
  if (initialClip) {
    assertBoundedClip(initialClip);
    if (initialClip.ownerId !== ownerId)
      throw new Error("Saved recording owner mismatch");
  }
  let snapshot: RecorderSnapshot = {
    status: initialClip ? "saved" : "idle",
    clip: initialClip,
    error: null,
  };
  let generation = 0;
  let disposed = false;
  let cancellationGeneration = 0;
  let disposal: Promise<void> | undefined;
  let queue: Promise<unknown> = Promise.resolve();
  const listeners = new Set<(state: RecorderSnapshot) => void>();
  const publish = (next: RecorderSnapshot) => {
    snapshot = next;
    for (const listener of listeners) listener(next);
  };
  const run = <T>(task: () => Promise<T>) => {
    const result = queue.catch(() => undefined).then(task);
    queue = result;
    return result;
  };
  const failure = (error: unknown) =>
    publish({
      ...snapshot,
      status: "error",
      error:
        error instanceof Error
          ? error.message
          : "Recording unavailable. You can type your story.",
    });
  async function cancelWork() {
    await port.stopPlayback();
    const stopped = await port.stop();
    await port.removeTemporary(stopped?.uri);
    if (snapshot.clip) await port.discard(snapshot.clip);
    publish({ status: "idle", clip: null, error: null });
  }
  return {
    getSnapshot: () => snapshot,
    subscribe: (listener: (state: RecorderSnapshot) => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    start: () => {
      const expected = generation;
      return run(async () => {
        if (disposed || expected !== generation) return;
        try {
          if (snapshot.status === "recording" || snapshot.status === "paused")
            return;
          if (snapshot.clip)
            throw new Error(
              "Keep or discard the current clip before recording again",
            );
          if (!(await port.requestPermission()))
            throw new Error(
              "Microphone permission denied. You can type your story.",
            );
          if (disposed || expected !== generation) return;
          await port.start();
          if (disposed || expected !== generation) {
            await cancelWork();
            return;
          }
          publish({ status: "recording", clip: null, error: null });
        } catch (error) {
          failure(error);
        }
      });
    },
    pause: () =>
      run(async () => {
        if (!disposed && snapshot.status === "recording") {
          await port.pause();
          publish({ ...snapshot, status: "paused" });
        }
      }),
    resume: () =>
      run(async () => {
        if (!disposed && snapshot.status === "paused") {
          await port.resume();
          publish({ ...snapshot, status: "recording" });
        }
      }),
    stop: () => {
      const expected = generation;
      const expectedCancellation = cancellationGeneration;
      return run(async () => {
        if (disposed || expected !== generation) return null;
        if (snapshot.status === "saved") return snapshot.clip;
        try {
          const recording = await port.stop();
          if (!recording) return null;
          const clip = await port.seal(recording.uri, recording.durationMs);
          assertBoundedClip(clip);
          if (clip.ownerId !== ownerId)
            throw new Error("Recording owner changed");
          await port.removeTemporary(recording.uri);
          if (expectedCancellation !== cancellationGeneration) {
            await port.discard(clip);
            return null;
          }
          publish({ status: "saved", clip, error: null });
          return clip;
        } catch (error) {
          failure(error);
          return null;
        }
      });
    },
    cancel: () => {
      generation++;
      cancellationGeneration++;
      return run(cancelWork);
    },
    play: () =>
      run(async () => {
        if (!disposed && snapshot.clip) await port.play(snapshot.clip);
      }),
    stopPlayback: () => port.stopPlayback(),
    dispose: () => {
      disposed = true;
      generation++;
      disposal ??= run(async () => {
        let recording: { uri: string; durationMs: number } | null = null;
        const errors: unknown[] = [];
        try {
          await port.stopPlayback();
        } catch (error) {
          errors.push(error);
        }
        try {
          recording = await port.stop();
          // Leaving the route is not an explicit discard. Seal active work while
          // its owner vault remains available; revoked vaults reject this write.
          if (
            recording &&
            !snapshot.clip &&
            ["recording", "paused", "error"].includes(snapshot.status)
          ) {
            const clip = await port.seal(recording.uri, recording.durationMs);
            assertBoundedClip(clip);
            if (clip.ownerId !== ownerId)
              throw new Error("Recording owner changed");
            publish({ status: "saved", clip, error: null });
          }
        } catch (error) {
          errors.push(error);
        }
        try {
          await port.removeTemporary(recording?.uri);
        } catch (error) {
          errors.push(error);
        }
        try {
          await port.release();
        } catch (error) {
          errors.push(error);
        }
        listeners.clear();
        if (errors.length) throw errors[0];
      });
      return disposal;
    },
  };
}
export type RecorderController = ReturnType<typeof createRecorderController>;
export interface TranscriptDraft {
  text: string;
  originalText: string;
  clipId: string;
  revision: number;
  verified: false;
  source: Record<string, unknown>;
}
/** Compatibility spike only: no resumable offsets or background guarantees. */
export async function transcribeClip(
  clip: PrivateClip,
  options: {
    ownerId: string;
    consent: boolean;
    language?: string;
    request(body: {
      audio_base64: string;
      filename: string;
      mime_type: string;
      language?: string;
    }): Promise<{ text: string; source?: Record<string, unknown> }>;
  },
): Promise<TranscriptDraft> {
  if (clip.ownerId !== options.ownerId)
    throw new Error("Recording owner mismatch");
  if (!options.consent)
    throw new Error("AI-processing consent is required before transcription");
  assertBoundedClip(clip);
  const result = await options.request({
    audio_base64: clip.base64,
    filename: clip.filename,
    mime_type: clip.mimeType,
    language: options.language,
  });
  if (typeof result.text !== "string" || !result.text.trim())
    throw new Error(
      "No transcript received; keep the recording and type a correction",
    );
  return {
    text: result.text,
    originalText: result.text,
    clipId: clip.id,
    revision: 0,
    verified: false,
    source: result.source ?? {},
  };
}
export function editTranscript(
  draft: TranscriptDraft,
  text: string,
): TranscriptDraft {
  return { ...draft, text, revision: draft.revision + 1, verified: false };
}
