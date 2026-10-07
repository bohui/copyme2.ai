import React, { useEffect } from "react";
import { Text } from "react-native";
import { useMemoir } from "../src/context";
import { shareSourceExport } from "../src/platform/export-file";
import { useScopedState, useResource } from "../src/resource";
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
  const r = useResource(() => api!.collection(projectId), [projectId]);
  const [selected, setSelected] = useScopedState<string[]>([]);
  const [notice, setNotice] = useScopedState("");
  const [taskId, setTaskId] = useScopedState<string | null>(null);
  const [result, setResult] = useScopedState<unknown>(null);
  useEffect(() => {
    setResult(null);
    setTaskId(null);
    setSelected([]);
    setNotice("");
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
    try {
      const task = await api!.collectionTask(projectId, {
        kind: "BuildSourceExport",
        memory_ids: selected,
        title: "Memoir sources",
      });
      setTaskId(task.id);
      await vault?.set("source-export:" + projectId, task.id);
      setNotice(t("pending"));
    } catch {
      setNotice(t("error"));
    }
  }
  async function check() {
    if (!taskId) return;
    try {
      const task = await api!.task(taskId);
      setNotice(task.status);
      if (task.status === "SUCCEEDED") setResult(task.result);
    } catch {
      setNotice(t("error"));
    }
  }
  return (
    <Screen>
      <Heading title={t("export")} subtitle={t("exportBody")} />
      <Body muted>{t("accountWide")}</Body>
      {r.error && <Notice text={r.error} />}{" "}
      {r.value?.sources?.map((source) => (
        <Check
          key={source.id}
          label={source.content}
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
        disabled={!selected.length}
        onPress={() => void prepare()}
      />
      {notice && <Notice text={notice} />}{" "}
      {taskId && (
        <Button title={t("refresh")} secondary onPress={() => void check()} />
      )}{" "}
      {result !== null && (
        <>
          <Button
            title={t("download")}
            onPress={() =>
              void shareSourceExport(result).catch(() =>
                setNotice(t("unavailable")),
              )
            }
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
