import React, { useRef } from "react";
import { Text, View } from "react-native";
import { router } from "expo-router";
import { useMemoir } from "../src/context";
import {
  useResource,
  useScopedState,
  record,
  records,
  string,
} from "../src/resource";
import { draftSections } from "../src/draft-view";
import { Body, Button, Card, Heading, Notice, Screen, styles } from "../src/ui";
export default function Draft() {
  const { api, projectId, locale, t } = useMemoir();
  const [edition, setEdition] = useScopedState<"en-AU" | "zh-CN" | null>(null);
  const language = edition || locale;
  const r = useResource(
    () => api!.privateDraft(projectId, language),
    [projectId, language],
  );
  const [notice, setNotice] = useScopedState("");
  const [busy, setBusy] = useScopedState(false);
  const busyRef = useRef(false);
  const current = useRef(r.value);
  current.current = r.value;
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
          language,
        }),
      );
    } catch {
      setNotice(t("error"));
    } finally {
      setBusy(false);
    }
  }
  async function more() {
    const saved = r.value;
    if (!saved?.snapshot_id || !saved.next_cursor || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setNotice("");
    try {
      const page = await api!.privateDraftPage(projectId, saved.snapshot_id, {
        cursor: saved.next_cursor,
      });
      if (current.current !== saved || page.snapshot_id !== saved.snapshot_id)
        return;
      r.setValue({
        ...saved,
        loaded_records: [...records(saved.loaded_records), ...page.records],
        next_cursor: page.next_cursor,
        page_complete: page.complete,
      });
    } catch {
      setNotice(t("savedPageChanged"));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
  const later = records(draft?.loaded_records);
  const proposals = [record(draft?.first_record), ...later].map((item) =>
    record(item.proposed_preview),
  );
  if (draft?.proposed_preview && !draft.first_record)
    proposals.unshift(draft.proposed_preview);
  return (
    <Screen>
      <Heading title={t("draft")} eyebrow={t("readOnly")} />
      <Text style={styles.small}>{t("draftEditionLanguage")}</Text>
      <View style={styles.row}>
        <Button
          title="English"
          secondary
          disabled={language === "en-AU" || busy}
          onPress={() => setEdition("en-AU")}
        />
        <Button
          title="简体中文"
          secondary
          disabled={language === "zh-CN" || busy}
          onPress={() => setEdition("zh-CN")}
        />
      </View>
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
      {later.map((item, index) =>
        record(item.preview).text ? (
          <Card key={string(item.id, String(index))}>
            <Heading title={string(record(item.preview).title)} />
            <Text selectable style={styles.body}>
              {string(record(item.preview).text)}
            </Text>
            {records(item.source_refs).map((ref, j) => (
              <Button
                key={j}
                secondary
                title={`${t("source")} ${j + 1}`}
                onPress={() =>
                  router.push({
                    pathname: "/source",
                    params: {
                      id: string(ref.source_id),
                      version: String(ref.version),
                    },
                  })
                }
              />
            ))}
          </Card>
        ) : null,
      )}
      {draft?.approval_required && <Notice text={t("draftProposalReadOnly")} />}
      {draft?.original_withheld && <Notice text={t("draftOriginalWithheld")} />}
      {proposals
        .filter((part) => typeof part.text === "string")
        .map((part, i) => (
          <Card key={`proposal-${i}`}>
            <Text style={styles.eyebrow}>{t("draftProposalReadOnly")}</Text>
            <Heading title={string(part.title)} />
            <Text selectable style={styles.body}>
              {string(part.text)}
            </Text>
          </Card>
        ))}
      {draft?.page_complete === false && (
        <Notice text={t("draftPagesPartial")} />
      )}
      {draft?.next_cursor && (
        <Button
          title={t("loadMoreDraft")}
          loading={busy}
          onPress={() => void more()}
        />
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
