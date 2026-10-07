import React from "react";
import { Text } from "react-native";
import { useMemoir } from "../src/context";
import {
  useScopedState,
  useResource,
  record,
  records,
  string,
} from "../src/resource";
import {
  Body,
  Button,
  Card,
  Field,
  Heading,
  Notice,
  Screen,
  styles,
} from "../src/ui";
export default function Timeline() {
  const { api, projectId, t } = useMemoir();
  const r = useResource(() => api!.events(projectId), [projectId]);
  const [editing, setEditing] = useScopedState<Record<string, unknown> | null>(
    null,
  );
  const [date, setDate] = useScopedState("");
  const [statement, setStatement] = useScopedState("");
  const [notice, setNotice] = useScopedState("");
  const events = records(r.value?.events);
  async function correct() {
    if (
      !editing ||
      !Number.isSafeInteger(editing.revision) ||
      !date.trim() ||
      !statement.trim()
    )
      return;
    try {
      await api!.correctEvent(projectId, string(editing.id), {
        expected_revision: editing.revision as number,
        patch: { temporal: { expression: date, precision: "approximate" } },
        statement,
      });
      setEditing(null);
      await r.refresh();
    } catch {
      setNotice(t("revisionConflict"));
    }
  }
  return (
    <Screen>
      <Heading title={t("timeline")} subtitle={t("timelineBody")} />
      {r.error && <Notice text={r.error} />}{" "}
      {r.loading && <Body>{t("loading")}</Body>}
      {events.map((event, i) => (
        <Card key={string(event.id, String(i))}>
          <Text style={styles.eyebrow}>
            {string(record(event.temporal).expression ?? event.date_expression)}
          </Text>
          <Text style={styles.h2}>{string(event.title ?? event.summary)}</Text>
          <Body>{string(event.description ?? event.summary)}</Body>
          <Button
            title={t("correction")}
            secondary
            onPress={() => {
              setEditing(event);
              setDate(string(record(event.temporal).expression));
              setStatement("");
            }}
          />
        </Card>
      ))}
      {!r.loading && !events.length && <Body>{t("noEvents")}</Body>}
      {editing && (
        <Card>
          <Heading title={t("correction")} />
          <Field
            label={t("dateExpression")}
            value={date}
            onChangeText={setDate}
            maxLength={500}
          />
          <Field
            label={t("statement")}
            value={statement}
            onChangeText={setStatement}
            multiline
            maxLength={2000}
          />
          {notice && <Notice text={notice} />}
          <Button
            title={t("submitCorrection")}
            disabled={!date.trim() || !statement.trim()}
            onPress={() => void correct()}
          />
          <Button
            title={t("cancel")}
            secondary
            onPress={() => setEditing(null)}
          />
        </Card>
      )}
    </Screen>
  );
}
