import React from "react";
import { Text } from "react-native";
import { router } from "expo-router";
import { useMemoir } from "../../src/context";
import { Button, Card, Heading, RowLink, Screen, styles } from "../../src/ui";
export default function Story() {
  const { t, session, storyState } = useMemoir();
  return (
    <Screen>
      <Heading title={t("story")} subtitle={t("draftBody")} />
      <Card>
        <Text style={styles.eyebrow}>{t("private")}</Text>
        <Text style={styles.title}>{t("draft")}</Text>
        <Text style={styles.small}>{t("readOnly")}</Text>
        <Button
          title={t("readDraft")}
          icon="book-outline"
          disabled={!session}
          onPress={() => router.push("/draft")}
        />
      </Card>
      <RowLink
        title={t("collection")}
        body={t("collectionBody")}
        icon="leaf-outline"
        onPress={() => router.push("/collection")}
      />
      <RowLink
        title={t("timeline")}
        body={t("timelineBody")}
        icon="time-outline"
        onPress={() => router.push("/timeline")}
      />
      {storyState && (
        <Text style={styles.small}>
          {t("covered")}:{" "}
          {storyState.recall_status?.rounds_completed ??
            storyState.rounds_completed}
        </Text>
      )}
    </Screen>
  );
}
