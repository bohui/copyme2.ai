import { useEffect, useState } from "react";
import { Platform } from "react-native";
import { createNativeRecorder } from "./native-media";
import type { RecorderController, RecorderSnapshot } from "./media";
import type { Vault } from "./vault";
const initial: RecorderSnapshot = { status: "idle", clip: null, error: null };
export function useForegroundRecorder(vault: Vault | null) {
  const [controller, setController] = useState<RecorderController | null>(null);
  const [snapshot, setSnapshot] = useState<RecorderSnapshot>(initial);
  useEffect(() => {
    let disposed = false;
    let instance: RecorderController | null = null;
    let unsubscribe: (() => void) | undefined;
    setController(null);
    setSnapshot(initial);
    if (!vault || Platform.OS === "web") return;
    void createNativeRecorder(vault)
      .then((value) => {
        instance = value;
        if (disposed) {
          void value.dispose().catch(() => undefined);
          return;
        }
        unsubscribe = value.subscribe(setSnapshot);
        setSnapshot(value.getSnapshot());
        setController(value);
      })
      .catch(() => {
        if (!disposed)
          setSnapshot({
            ...initial,
            status: "error",
            error: "Native recording unavailable. You can type your story.",
          });
      });
    return () => {
      disposed = true;
      unsubscribe?.();
      void instance?.dispose().catch(() => undefined);
    };
  }, [vault]);
  return { controller, snapshot, available: controller !== null };
}
