import { useCallback, useEffect, useRef, useState } from "react";
import { AppState, Platform } from "react-native";
import { useFocusEffect } from "expo-router";
import type { MemoirApi } from "@memoir/api-client";
import { createReplyPlayer } from "./reply-player";
export function useReplyAudio(
  api: MemoirApi | null,
  owner: string | undefined,
) {
  const player = useRef<ReturnType<typeof createReplyPlayer> | null>(null);
  const uiEpoch = useRef(0);
  const [active, setActive] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const stop = useCallback(async () => {
    const id = ++uiEpoch.current;
    await player.current?.stop();
    if (id !== uiEpoch.current) return;
    setActive(null);
    setBusy(false);
  }, []);
  useFocusEffect(
    useCallback(
      () => () => {
        void stop();
      },
      [stop],
    ),
  );
  useEffect(() => {
    let disposed = false;
    let playbackEpoch = 0;
    ++uiEpoch.current;
    setActive(null);
    setBusy(false);
    setFailed(false);
    player.current = null;
    if (!api || !owner || Platform.OS === "web") return;
    let nativePlayer: { pause(): void; remove(): void } | null = null;
    let temporary: { exists: boolean; delete(): void } | null = null;
    void Promise.all([
      import("expo-audio"),
      import("expo-file-system"),
      import("expo-crypto"),
    ])
      .then(([audio, files, crypto]) => {
        if (disposed) return;
        const clear = async () => {
          playbackEpoch++;
          nativePlayer?.pause();
          nativePlayer?.remove();
          nativePlayer = null;
          if (temporary?.exists) temporary.delete();
          temporary = null;
        };
        player.current = createReplyPlayer({
          generate: (text, language) => api.questionAudio({ text, language }),
          play: async (reply, isCurrent) => {
            const id = ++playbackEpoch;
            const valid = () =>
              !disposed &&
              id === playbackEpoch &&
              isCurrent() &&
              AppState.currentState !== "background" &&
              AppState.currentState !== "inactive";
            if (!valid()) return;
            await audio.setAudioModeAsync({
              allowsRecording: false,
              shouldPlayInBackground: false,
              playsInSilentMode: true,
            });
            if (!valid()) return;
            const file = new files.File(
              files.Paths.cache,
              `memoir-playback-${crypto.randomUUID()}.${reply.mime_type === "audio/wav" ? "wav" : reply.mime_type === "audio/mp4" ? "m4a" : "mp3"}`,
            );
            temporary = file;
            if (!valid()) {
              await clear();
              return;
            }
            file.write(reply.audio_base64, { encoding: "base64" });
            if (!valid()) {
              await clear();
              return;
            }
            nativePlayer = audio.createAudioPlayer(file.uri);
            if (!valid()) {
              await clear();
              return;
            }
            (nativePlayer as ReturnType<typeof audio.createAudioPlayer>).play();
          },
          stop: clear,
        });
      })
      .catch(() => {
        if (!disposed) setFailed(true);
      });
    const listener = AppState.addEventListener("change", (state) => {
      if (state !== "active") void stop();
    });
    return () => {
      disposed = true;
      playbackEpoch++;
      uiEpoch.current++;
      listener.remove();
      void player.current?.stop();
      player.current = null;
    };
  }, [api, owner, stop]);
  async function play(id: string, text: string, locale: string) {
    if (!player.current) {
      setFailed(true);
      return;
    }
    if (active === id) {
      await stop();
      return;
    }
    const invocation = ++uiEpoch.current;
    const target = player.current;
    setActive(id);
    setBusy(true);
    setFailed(false);
    try {
      await target.play(text, locale);
    } catch {
      if (invocation === uiEpoch.current) {
        setFailed(true);
        setActive(null);
      }
    } finally {
      if (invocation === uiEpoch.current) setBusy(false);
    }
  }
  return { play, stop, active, busy, failed };
}
