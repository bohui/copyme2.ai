import { useEffect, useRef, useState } from "react";
import { MemoirApiError } from "@memoir/api-client";
import { useMemoir } from "./context";
/** Every async read is fenced by both owner and route dependencies. */
export function useResource<T>(read: () => Promise<T>, keys: unknown[] = []) {
  const { session, t } = useMemoir();
  const [value, setValue] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generation = useRef(0);
  const reader = useRef(read);
  reader.current = read;
  const key = JSON.stringify([session?.user.id, ...keys]);
  const [valueKey, setValueKey] = useState(key);
  const currentKey = useRef(key);
  currentKey.current = key;
  async function refresh() {
    if (currentKey.current !== key) return null;
    const epoch = ++generation.current;
    if (!session) {
      setError(t("signIn"));
      return null;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await reader.current();
      if (epoch !== generation.current) return null;
      setValueKey(key);
      setValue(result);
      return result;
    } catch (failure) {
      if (epoch === generation.current)
        setError(
          t(
            failure instanceof MemoirApiError && failure.status === 403
              ? "familyGate"
              : failure instanceof MemoirApiError && failure.status === 409
                ? "revisionConflict"
                : "error",
          ),
        );
      return null;
    } finally {
      if (epoch === generation.current) setLoading(false);
    }
  }
  useEffect(() => {
    setValue(null);
    void refresh();
    return () => {
      generation.current++;
    };
  }, [key]);
  return {
    value: valueKey === key ? value : null,
    loading,
    error,
    refresh,
    setValue: (next: T | null) => {
      setValueKey(key);
      setValue(next);
    },
  };
}
export function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
export function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(record) : [];
}
export function string(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

/** Local form/media state is also account/project scoped. A late callback from
 * a previous owner cannot populate a screen belonging to the next identity. */
export function useScopedState<T>(
  initial: T,
): [T, (next: T | ((previous: T) => T)) => void] {
  const { session, projectId } = useMemoir();
  const key = JSON.stringify([session?.user.id, projectId]);
  const current = useRef(key);
  current.current = key;
  const [stored, setStored] = useState({ key, value: initial });
  const update = (next: T | ((previous: T) => T)) => {
    if (current.current !== key) return;
    setStored((previous) => ({
      key,
      value:
        typeof next === "function"
          ? (next as (previous: T) => T)(
              previous.key === key ? previous.value : initial,
            )
          : next,
    }));
  };
  return [stored.key === key ? stored.value : initial, update];
}
