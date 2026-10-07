import React, { useEffect } from "react";
import { Text, View } from "react-native";
import {
  LIFE_STAGES,
  type PeriodCoverage,
  CollectionUpdateSchema,
} from "@memoir/contracts";
import type { MessageKey } from "@memoir/i18n";
import { useMemoir } from "../src/context";
import { useScopedState, useResource } from "../src/resource";
import {
  Body,
  Button,
  Card,
  Check,
  Field,
  Heading,
  Notice,
  Screen,
  styles,
} from "../src/ui";
export default function Collection() {
  const { api, projectId, locale, t } = useMemoir();
  const r = useResource(() => api!.collection(projectId), [projectId]);
  const [periods, setPeriods] = useScopedState<Record<string, PeriodCoverage>>(
    {},
  );
  const [revision, setRevision] = useScopedState(0);
  const [confirmed, setConfirmed] = useScopedState(false);
  const [busy, setBusy] = useScopedState(false);
  const [notice, setNotice] = useScopedState("");
  const [dirty, setDirty] = useScopedState(false);
  useEffect(() => {
    if (r.value && !dirty) {
      setPeriods(r.value.periods);
      setRevision(r.value.revision);
    }
  }, [r.value, dirty]);
  function update(stage: string, patch: Partial<PeriodCoverage>) {
    setDirty(true);
    setPeriods((current) => ({
      ...current,
      [stage]: {
        status: "skipped",
        memory_ids: [],
        note: "",
        ...current[stage],
        ...patch,
      },
    }));
    setConfirmed(false);
  }
  async function save() {
    const checked = CollectionUpdateSchema.safeParse({
      expected_revision: revision,
      periods,
      confirm_ready: confirmed,
    });
    if (!checked.success) {
      setNotice(t("confirmReady"));
      return;
    }
    setBusy(true);
    try {
      const result = await api!.updateCollection(projectId, checked.data);
      setRevision(result.revision);
      setDirty(false);
      r.setValue({ ...result, sources: r.value?.sources });
      setNotice(t("saved"));
    } catch {
      setNotice(t("revisionConflict"));
    } finally {
      setBusy(false);
    }
  }
  async function organise() {
    setBusy(true);
    try {
      const task = await api!.organiseCollection(projectId, {
        expected_revision: revision,
        language: locale,
      });
      setNotice(`${t("pending")}: ${task.id}`);
    } catch {
      setNotice(t("commerceGate"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Screen>
      <Heading title={t("collection")} subtitle={t("collectionBody")} />
      <Text style={styles.small}>{t("accountWide")}</Text>
      {r.error && <Notice text={r.error} />}{" "}
      {notice && <Notice text={notice} />}{" "}
      {LIFE_STAGES.map((stage) => {
        const period = periods[stage];
        const key = stage === "childhood" ? "childhoodStage" : stage;
        return (
          <Card key={stage}>
            <Text accessibilityRole="header" style={styles.h2}>
              {t(key as MessageKey)}
            </Text>
            {(["recorded", "skipped", "not_applicable"] as const).map(
              (status) => (
                <Check
                  key={status}
                  label={t(
                    status === "not_applicable" ? "notApplicable" : status,
                  )}
                  checked={period?.status === status}
                  onPress={() => update(stage, { status })}
                />
              ),
            )}
            {period?.status === "recorded" ? (
              <View>
                <Text style={styles.label}>{t("chooseSources")}</Text>
                {r.value?.sources?.map((source) => (
                  <Check
                    key={source.id}
                    label={source.content}
                    checked={period.memory_ids.includes(source.id)}
                    onPress={() =>
                      update(stage, {
                        memory_ids: period.memory_ids.includes(source.id)
                          ? period.memory_ids.filter((id) => id !== source.id)
                          : [...period.memory_ids, source.id],
                      })
                    }
                  />
                ))}
              </View>
            ) : (
              period && (
                <Field
                  label={t("reason")}
                  value={period.note}
                  onChangeText={(note) => update(stage, { note })}
                  multiline
                />
              )
            )}
          </Card>
        );
      })}
      <Check
        label={t("confirmReady")}
        checked={confirmed}
        onPress={() => setConfirmed(!confirmed)}
      />
      <Button
        title={t("saveReview")}
        disabled={!r.value}
        loading={busy}
        onPress={() => void save()}
      />
      {r.value?.ready && !dirty && (
        <Button
          title={t("organise")}
          secondary
          loading={busy}
          onPress={() => void organise()}
        />
      )}
      <Button
        title={t("refresh")}
        secondary
        onPress={() => {
          setDirty(false);
          setConfirmed(false);
          void r.refresh();
        }}
      />
      <Body muted>{t("readOnly")}</Body>
    </Screen>
  );
}
