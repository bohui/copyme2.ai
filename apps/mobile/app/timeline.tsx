import React, { useRef } from "react";
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
  const [busy, setBusy] = useScopedState(false);
  const busyRef = useRef(false);
  const current = useRef(r.value);
  current.current = r.value;
  async function more(
    event?: Record<string, unknown>,
    kind?: "evidence" | "details",
  ) {
    const saved = r.value;
    if (!saved || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    setNotice("");
    try {
      if (event && kind) {
        const id = string(event.id);
        const page =
          kind === "evidence"
            ? await api!.eventEvidencePage(projectId, id, {
                cursor: string(event.evidence_next_cursor) || undefined,
              })
            : await api!.eventDetailsPage(projectId, id, {
                cursor: string(event.details_next_cursor) || undefined,
              });
        if (current.current !== saved) return;
        const details = kind === "details";
        const updated = {
          ...event,
          [details ? "detail_records" : "source_refs"]: [
            ...records(event[details ? "detail_records" : "source_refs"]),
            ...records(page[details ? "details" : "source_refs"]),
          ],
          [details ? "details_complete" : "evidence_complete"]: page.complete,
          [details ? "details_next_cursor" : "evidence_next_cursor"]:
            page.next_cursor,
        };
        r.setValue({
          ...saved,
          events: saved.events.map((item) => (item.id === id ? updated : item)),
        });
      } else if (saved.next_cursor) {
        const page = await api!.eventsPage(projectId, {
          cursor: saved.next_cursor,
        });
        if (current.current !== saved) return;
        r.setValue({ ...page, events: [...saved.events, ...page.events] });
      }
    } catch {
      setNotice(t("savedPageChanged"));
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }
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
          {!!event.uncertainty && <Body>{string(event.uncertainty)}</Body>}
          {event.assertion === "inferred" && <Body>{t("eventInferred")}</Body>}
          {event.status === "unresolved" && <Body>{t("eventUnresolved")}</Body>}
          {event.timing_conflict === true && (
            <Body>{t("eventConflictingDates")}</Body>
          )}
          {records(event.source_refs).map((ref, j) => (
            <Text selectable key={`ref-${j}`} style={styles.small}>
              {string(ref.quote)}
            </Text>
          ))}
          {!!event.evidence_next_cursor && (
            <Button
              title={t("loadMoreEvidence")}
              secondary
              loading={busy}
              onPress={() => void more(event, "evidence")}
            />
          )}
          {records(event.detail_records).map((detail, j) => (
            <Body key={`detail-${j}`}>
              {t("eventRecordedContext")}:{" "}
              {typeof detail.value === "string"
                ? detail.value
                : string(
                    record(detail.value).expression ??
                      record(detail.value).event_id,
                  )}
            </Body>
          ))}
          {event.details_complete === false && (
            <Button
              title={t("loadMoreEventContext")}
              secondary
              loading={busy}
              onPress={() => void more(event, "details")}
            />
          )}
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
      {notice && (
        <Notice
          text={notice}
          onRetry={() => void r.refresh()}
          retryLabel={t("refresh")}
        />
      )}
      {r.value?.complete === false && (
        <Notice text={t("timelinePagesPartial")} />
      )}
      {r.value?.next_cursor && (
        <Button
          title={t("loadMoreEvents")}
          loading={busy}
          onPress={() => void more()}
        />
      )}
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
