import React, { useEffect, useRef } from "react";
import { Text } from "react-native";
import { useMemoir } from "../src/context";
import { shareSourceExport } from "../src/platform/export-file";
import { useScopedState } from "../src/resource";
import { useCollectionPages } from "../src/collection-pages";
import {
  Body,
  Button,
  Card,
  Check,
  Heading,
  Notice,
  Screen,
  styles,
} from "../src/ui";
export default function Export() {
  const { api, projectId, t, vault, session } = useMemoir();
  const r = useCollectionPages();
  const [selected, setSelected] = useScopedState<string[]>([]);
  const [notice, setNotice] = useScopedState("");
  const [taskId, setTaskId] = useScopedState<string | null>(null);
  const [result, setResult] = useScopedState<unknown>(null);
  const [busy, setBusy] = useScopedState(false);
  const [retryable, setRetryable] = useScopedState(false);
  const retrying = useRef(false);
  const downloading = useRef(false);
  const request = useRef<AbortController | null>(null);
  const ownerScope = JSON.stringify([session?.user.id, projectId]);
  const currentOwner = useRef(ownerScope);
  currentOwner.current = ownerScope;
  useEffect(
    () => () => {
      request.current?.abort();
    },
    [session?.user.id, projectId],
  );
  useEffect(() => {
    setResult(null);
    setTaskId(null);
    setSelected([]);
    setNotice("");
    setRetryable(false);
  }, [session?.user.id, projectId]);
  useEffect(() => {
    let alive = true;
    void vault?.get<string>("source-export:" + projectId).then((id) => {
      if (alive && id) setTaskId(id);
    });
    return () => {
      alive = false;
    };
  }, [vault, projectId]);
  async function prepare() {
    if (busy) return;
    setBusy(true);
    try {
      const task = await api!.collectionTask(projectId, {
        kind: "BuildSourceExport",
        memory_ids: selected,
        title: "Memoir sources",
      });
      setRetryable(false);
      setTaskId(task.id);
      await vault?.set("source-export:" + projectId, task.id);
      setNotice(t("pending"));
    } catch {
      setNotice(t("error"));
    } finally {
      setBusy(false);
    }
  }
  async function check() {
    if (!taskId) return;
    try {
      const task = await api!.task(taskId);
      if (currentOwner.current !== ownerScope) return;
      setNotice(task.status);
      setRetryable(
        task.status === "FAILED" && task.error === "BOUNDED_JOB_RETRY",
      );
      if (task.status !== "SUCCEEDED") setResult(null);
      if (task.status === "SUCCEEDED") {
        setResult(task.result);
        if (task.complete === false) setNotice(t("exportPartial"));
      }
    } catch {
      setNotice(t("error"));
    }
  }
  async function retry() {
    if (!taskId || !retryable || retrying.current) return;
    retrying.current = true;
    setBusy(true);
    try {
      const task = await api!.retryTask(taskId);
      if (currentOwner.current !== ownerScope) return;
      setRetryable(false);
      setNotice(task.status);
    } catch {
      if (currentOwner.current === ownerScope) setNotice(t("error"));
    } finally {
      retrying.current = false;
      if (currentOwner.current === ownerScope) setBusy(false);
    }
  }
  async function download() {
    if (!taskId || downloading.current) return;
    downloading.current = true;
    setBusy(true);
    const controller = new AbortController();
    request.current = controller;
    try {
      const complete = await api!.completeTaskResult(taskId, {
        signal: controller.signal,
      });
      if (controller.signal.aborted || currentOwner.current !== ownerScope)
        return;
      setResult(complete);
      await shareSourceExport(complete);
    } catch {
      if (!controller.signal.aborted) setNotice(t("unavailable"));
    } finally {
      downloading.current = false;
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return (
    <Screen>
      <Heading title={t("export")} subtitle={t("exportBody")} />
      <Body muted>{t("accountWide")}</Body>
      {r.error && <Notice text={r.error} />}{" "}
      <Body muted>{t("collectionSelectionLimit")}</Body>
      {r.value?.complete === false && (
        <Body muted>{t("collectionPartial")}</Body>
      )}
      {r.pageError && <Notice text={r.pageError} />}
      {r.value?.next_cursor && (
        <Button
          title={t("collectionMoreSources")}
          loading={r.loadingMore}
          onPress={() => void r.loadMore()}
        />
      )}
      {r.value?.sources?.map((source) => (
        <Check
          key={source.id}
          label={source.content.slice(0, 180)}
          checked={selected.includes(source.id)}
          onPress={() =>
            setSelected((current) =>
              current.includes(source.id)
                ? current.filter((id) => id !== source.id)
                : [...current, source.id],
            )
          }
        />
      ))}
      <Button
        title={t("export")}
        disabled={!selected.length || selected.length > 1000}
        loading={busy}
        onPress={() => void prepare()}
      />
      {notice && <Notice text={notice} />}{" "}
      {taskId && (
        <Button title={t("refresh")} secondary onPress={() => void check()} />
      )}{" "}
      {retryable && (
        <Button
          title={t("retry")}
          loading={busy}
          onPress={() => void retry()}
        />
      )}
      {result !== null && (
        <>
          <Button
            title={t("download")}
            loading={busy}
            onPress={() => void download()}
          />
          <Card>
            <Text selectable style={styles.body}>
              {JSON.stringify(result, null, 2)}
            </Text>
          </Card>
        </>
      )}
    </Screen>
  );
}
