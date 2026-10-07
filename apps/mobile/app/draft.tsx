import React, { useState } from "react";
import { Text, View } from "react-native";
import { router } from "expo-router";
import { useMemoir } from "../src/context";
import { useResource, string } from "../src/resource";
import { draftSections } from "../src/draft-view";
import { Body, Button, Card, Heading, Notice, Screen, styles } from "../src/ui";
export default function Draft() {
  const { api, projectId, locale, t } = useMemoir();
  const r = useResource(
    () => api!.privateDraft(projectId, locale),
    [projectId, locale],
  );
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const draft = r.value;
  const sections = draft ? draftSections(draft) : [];
  const sources = Array.isArray(draft?.preview?.source_ids)
    ? draft.preview.source_ids
    : [];
  const failed =
    !!draft?.error ||
    ["failed", "FAILED", "exhausted"].includes(string(draft?.status));
  async function retry() {
    setBusy(true);
    try {
      r.setValue(
        await api!.retryPrivateDraft({
          project_id: projectId,
          language: locale,
        }),
      );
    } catch {
      setNotice(t("error"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Screen>
      <Heading title={t("draft")} eyebrow={t("readOnly")} />
      {(r.error || notice) && (
        <Notice
          text={r.error ?? notice}
          onRetry={() => void r.refresh()}
          retryLabel={t("refresh")}
        />
      )}{" "}
      {r.loading && !draft && <Body>{t("loading")}</Body>}
      {draft?.preview ? (
        <>
          <Text style={styles.eyebrow}>{t("draftSaved")}</Text>
          <Heading title={draft.preview.title} />
          {sections.length ? (
            sections.map((section) => (
              <View key={section.id} style={{ gap: 12 }}>
                {section.title && (
                  <Text accessibilityRole="header" style={styles.h2}>
                    {section.title}
                  </Text>
                )}
                <Text
                  selectable
                  style={[
                    styles.body,
                    { fontFamily: "serif", fontSize: 21, lineHeight: 33 },
                  ]}
                >
                  {section.text}
                </Text>
                {section.references.map((reference, index) => (
                  <Button
                    key={reference.id + index}
                    secondary
                    title={`${t("source")} ${index + 1}`}
                    onPress={() =>
                      router.push({
                        pathname: "/source",
                        params: {
                          id: reference.id,
                          ...(reference.version
                            ? { version: reference.version }
                            : {}),
                        },
                      })
                    }
                  />
                ))}
                {!section.references.length && (
                  <Text style={styles.small}>{t("sourceMissing")}</Text>
                )}
              </View>
            ))
          ) : (
            <>
              {draft.preview.text.split(/\n\s*\n/).map((paragraph, i) => (
                <Text
                  selectable
                  key={i}
                  style={[
                    styles.body,
                    { fontFamily: "serif", fontSize: 21, lineHeight: 33 },
                  ]}
                >
                  {paragraph}
                </Text>
              ))}
              <View style={styles.divider} />
              <Text style={styles.h2}>{t("sources")}</Text>
              {sources.map((id, i) => (
                <Button
                  key={String(id)}
                  secondary
                  title={`${t("source")} ${i + 1}`}
                  onPress={() =>
                    router.push({
                      pathname: "/source",
                      params: { id: String(id) },
                    })
                  }
                />
              ))}
              {!sources.length && <Body muted>{t("sourceMissing")}</Body>}
            </>
          )}
        </>
      ) : (
        !r.loading &&
        !r.error && (
          <Card>
            <Body>{t("draftEmpty")}</Body>
            <Button
              title={t("resume")}
              onPress={() => router.replace("/(tabs)")}
            />
          </Card>
        )
      )}
      {draft?.status === "stale" && <Notice text={t("draftStale")} />}{" "}
      {failed && <Notice text={t("draftError")} />}
      <Button title={t("refresh")} secondary onPress={() => void r.refresh()} />
      {failed && !draft?.updating && (
        <Button
          title={t("retryDraft")}
          loading={busy}
          onPress={() => void retry()}
        />
      )}
    </Screen>
  );
}
