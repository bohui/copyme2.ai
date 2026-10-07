import React from "react";
import { Text } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useMemoir } from "../src/context";
import { useResource } from "../src/resource";
import { Body, Heading, Card, Notice, Screen, styles } from "../src/ui";
export default function Sources() {
  const { api, projectId, t } = useMemoir();
  const { id, version } = useLocalSearchParams<{
    id?: string;
    version?: string;
  }>();
  const r = useResource(async () => {
    if (id) {
      const source = await api!.sourceDetail(projectId, id, version);
      return [{ id: source.id, content: source.text, version: source.version }];
    }
    return (await api!.collection(projectId)).sources ?? [];
  }, [projectId, id, version]);
  const sources = r.value ?? [];
  return (
    <Screen>
      <Heading
        title={t(id ? "source" : "sources")}
        subtitle={t(id ? "private" : "accountWide")}
      />
      {r.error && (
        <Notice
          text={id ? t("sourceMissing") : r.error}
          onRetry={() => void r.refresh()}
          retryLabel={t("refresh")}
        />
      )}{" "}
      {r.loading && <Body>{t("loading")}</Body>}
      {sources.map((source) => (
        <Card key={source.id}>
          <Text style={styles.eyebrow}>{t("source")}</Text>
          <Text selectable style={styles.body}>
            {source.content}
          </Text>
        </Card>
      ))}
      {!r.loading && !r.error && !sources.length && (
        <Body>{t("sourceMissing")}</Body>
      )}
    </Screen>
  );
}
