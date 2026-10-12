import React from "react";
import { Text } from "react-native";
import { useLocalSearchParams } from "expo-router";
import { useMemoir } from "../src/context";
import { useResource } from "../src/resource";
import { useCollectionPages } from "../src/collection-pages";
import { Body, Button, Heading, Card, Notice, Screen, styles } from "../src/ui";
export default function Sources() {
  const { api, projectId, t } = useMemoir();
  const { id, version } = useLocalSearchParams<{
    id?: string;
    version?: string;
  }>();
  const pages = useCollectionPages(!id);
  const r = useResource(async () => {
    if (id) {
      const source = await api!.sourceDetail(projectId, id, version);
      return [{ id: source.id, content: source.text, version: source.version }];
    }
    return [];
  }, [projectId, id, version]);
  const sources = id ? (r.value ?? []) : (pages.value?.sources ?? []);
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
      {!id && pages.value?.complete === false && (
        <Body muted>{t("collectionPartial")}</Body>
      )}
      {!id && (pages.error || pages.pageError) && (
        <Notice text={pages.error || pages.pageError} />
      )}
      {!id && pages.value?.next_cursor && (
        <Button
          title={t("collectionMoreSources")}
          loading={pages.loadingMore}
          onPress={() => void pages.loadMore()}
        />
      )}
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
