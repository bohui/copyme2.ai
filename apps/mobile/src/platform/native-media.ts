import {
  assertBoundedClip,
  createRecorderController,
  listSavedClips,
  MAX_CLIP_BYTES,
  MAX_CLIP_DURATION_MS,
  type PrivateClip,
  type RecorderController,
} from "./media";
import type { Vault } from "./vault";
/** Foreground-only bounded recorder. Hardware writes a temporary app-private file;
 * stop encrypts the immutable original in SQLCipher before removing that file.
 */
export async function createNativeRecorder(
  vault: Vault,
): Promise<RecorderController> {
  const [audio, files, crypto, native] = await Promise.all([
    import("expo-audio"),
    import("expo-file-system"),
    import("expo-crypto"),
    import("react-native"),
  ]);
  if (native.Platform.OS === "web")
    throw new Error("Private recording requires the native development build");
  const recovered = await listSavedClips(vault);
  const recorder = new audio.AudioModule.AudioRecorder({
    ...audio.RecordingPresets.HIGH_QUALITY,
    numberOfChannels: 1,
    sampleRate: 22050,
    bitRate: 64_000,
    directory: "cache",
  });
  let player: ReturnType<typeof audio.createAudioPlayer> | null = null;
  let playbackFile: InstanceType<typeof files.File> | null = null;
  let recordingUri: string | null = null;
  let started = false;
  let durationMs = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let playbackEpoch = 0;
  let disposed = false;
  let disposal: Promise<void> | undefined;
  const stopPlayback = async () => {
    playbackEpoch++;
    player?.pause();
    player?.remove();
    player = null;
    if (playbackFile?.exists) playbackFile.delete();
    playbackFile = null;
  };
  const ensureForeground = () => {
    if (native.AppState.currentState !== "active")
      throw new Error("Recording pauses when Memoir leaves the foreground");
  };
  const controller = createRecorderController(
    vault.owner,
    {
      requestPermission: async () =>
        (await audio.requestRecordingPermissionsAsync()).granted,
      start: async () => {
        ensureForeground();
        if (files.Paths.availableDiskSpace < 5 * MAX_CLIP_BYTES)
          throw new Error(
            "Not enough free device storage. Free some space or type your story.",
          );
        await audio.setAudioModeAsync({
          allowsRecording: true,
          playsInSilentMode: true,
          shouldPlayInBackground: false,
          allowsBackgroundRecording: false,
          interruptionMode: "doNotMix",
        });
        await recorder.prepareToRecordAsync();
        ensureForeground();
        recordingUri = recorder.uri;
        started = true;
        durationMs = 0;
        recorder.record({ forDuration: MAX_CLIP_DURATION_MS / 1000 });
        timer = setTimeout(() => {
          void controller.stop();
        }, MAX_CLIP_DURATION_MS);
      },
      pause: async () => {
        recorder.pause();
      },
      resume: async () => {
        ensureForeground();
        recorder.record({
          forDuration: Math.max(
            1,
            MAX_CLIP_DURATION_MS / 1000 - recorder.currentTime,
          ),
        });
      },
      stop: async () => {
        if (timer) {
          clearTimeout(timer);
          timer = undefined;
        }
        if (started) {
          durationMs = Math.round(recorder.currentTime * 1000);
          await recorder.stop();
          started = false;
          recordingUri = recorder.uri ?? recordingUri;
        }
        return recordingUri ? { uri: recordingUri, durationMs } : null;
      },
      seal: async (uri, duration) => {
        const file = new files.File(uri);
        if (!file.exists || file.size <= 0 || file.size > MAX_CLIP_BYTES)
          throw new Error(
            "Recording exceeds the 1 MiB compatibility limit or is unavailable",
          );
        const clip: PrivateClip = {
          id: crypto.randomUUID(),
          ownerId: vault.owner,
          mimeType: "audio/mp4",
          filename: "recording.m4a",
          durationMs: duration,
          byteLength: file.size,
          base64: await file.base64(),
        };
        assertBoundedClip(clip);
        await vault.saveMedia(clip.id, clip);
        return clip;
      },
      removeTemporary: async (uri) => {
        const path = uri ?? recordingUri;
        if (path) {
          const file = new files.File(path);
          if (file.exists) file.delete();
        }
        recordingUri = null;
      },
      discard: (clip) => vault.deleteMedia(clip.id),
      play: async (clip) => {
        if (clip.ownerId !== vault.owner)
          throw new Error("Recording owner changed");
        const id = playbackEpoch + 1;
        await stopPlayback();
        const valid = () =>
          !disposed &&
          id === playbackEpoch &&
          native.AppState.currentState === "active";
        if (!valid()) return;
        await audio.setAudioModeAsync({
          allowsRecording: false,
          shouldPlayInBackground: false,
          playsInSilentMode: true,
        });
        if (!valid()) return;
        playbackFile = new files.File(
          files.Paths.cache,
          `memoir-playback-${crypto.randomUUID()}.m4a`,
        );
        if (!valid()) {
          await stopPlayback();
          return;
        }
        playbackFile.write(clip.base64, { encoding: "base64" });
        if (!valid()) {
          await stopPlayback();
          return;
        }
        player = audio.createAudioPlayer(playbackFile.uri);
        if (!valid()) {
          await stopPlayback();
          return;
        }
        player.play();
      },
      stopPlayback,
      release: async () => {
        listener.remove();
        recorder.release();
      },
    },
    recovered[0] ?? null,
  );
  const listener = native.AppState.addEventListener("change", (state) => {
    if (state !== "active") {
      void controller.stopPlayback();
      if (["recording", "paused"].includes(controller.getSnapshot().status))
        void controller.stop();
    }
  });
  return {
    ...controller,
    dispose: () => {
      disposed = true;
      // Invalidate immediately; controller disposal itself queues behind play.
      disposal ??= Promise.all([stopPlayback(), controller.dispose()]).then(
        () => undefined,
      );
      return disposal;
    },
  };
}
export interface PrivatePhoto {
  id: string;
  ownerId: string;
  mimeType: string;
  byteLength: number;
  base64: string;
}
/** Explicit action only. System photo picker grants scoped access; no blanket permission request. */
export async function pickPrivatePhoto(
  vault: Vault,
): Promise<PrivatePhoto | null> {
  const [picker, files, crypto] = await Promise.all([
    import("expo-image-picker"),
    import("expo-file-system"),
    import("expo-crypto"),
  ]);
  const result = await picker.launchImageLibraryAsync({
    mediaTypes: ["images"],
    allowsMultipleSelection: false,
    exif: false,
    quality: 0.7,
  });
  if (result.canceled || !result.assets[0]) return null;
  const asset = result.assets[0];
  const file = new files.File(asset.uri);
  if (!file.exists || file.size <= 0 || file.size > MAX_CLIP_BYTES)
    throw new Error(
      "Choose a photo under 1 MiB for this private-device preview",
    );
  const mimeType = asset.mimeType ?? "";
  if (
    ![
      "image/jpeg",
      "image/png",
      "image/heic",
      "image/heif",
      "image/webp",
    ].includes(mimeType)
  )
    throw new Error("Unsupported photo type");
  const photo: PrivatePhoto = {
    id: crypto.randomUUID(),
    ownerId: vault.owner,
    mimeType,
    byteLength: file.size,
    base64: await file.base64(),
  };
  await vault.saveMedia(photo.id, photo);
  // Only an unequivocal app-cache copy may be removed, never a library original.
  if (asset.uri.startsWith(`${files.Paths.cache.uri.replace(/\/$/, "")}/`))
    file.delete();
  return photo;
}

/** Invoke after stopping the recorder on logout. Names match the installed SDK57
 * recorder implementations, and only app-private cache files are considered.
 */
export async function clearNativeMediaTemporaryFiles(): Promise<void> {
  const { File, Directory, Paths } = await import("expo-file-system");
  for (const directory of [
    Paths.cache,
    new Directory(Paths.cache, "ExpoAudio"),
  ]) {
    if (!directory.exists) continue;
    for (const entry of directory.list()) {
      if (
        entry instanceof File &&
        /^(recording-[A-Za-z0-9-]+|memoir-playback-[A-Za-z0-9-]+)\.(?:m4a|mp3|wav)$/.test(
          entry.name,
        )
      )
        entry.delete();
    }
  }
}
