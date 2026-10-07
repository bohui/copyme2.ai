import React from "react";
import { Image, Text } from "react-native";
import { useMemoir } from "../src/context";
import { useResource, record, records, string } from "../src/resource";
import { Body, Card, Heading, Notice, Screen, styles } from "../src/ui";
export default function People() {
  const { api, projectId, t } = useMemoir();
  const r = useResource(() => api!.familyContext(projectId), [projectId]);
  const people = records(record(r.value?.family_context).people);
  return (
    <Screen>
      <Heading title={t("people")} subtitle={t("peopleBody")} />
      {r.error && <Notice text={r.error} />}{" "}
      {r.loading && <Body>{t("loading")}</Body>}
      {r.value?.family_features_enabled === false && (
        <Notice text={t("familyGate")} />
      )}{" "}
      {people.map((person, i) => (
        <Card key={string(person.id, String(i))}>
          {string(person.photo_url).startsWith("https://") && (
            <Image
              source={{ uri: string(person.photo_url) }}
              style={{ width: 88, height: 88, borderRadius: 44 }}
              accessibilityLabel={string(person.name)}
            />
          )}
          <Text style={styles.h2}>{string(person.name)}</Text>
          <Text style={styles.small}>{string(person.relationship)}</Text>
          <Body>{string(person.description ?? person.summary)}</Body>
        </Card>
      ))}
      {!r.loading && !people.length && <Body>{t("noPeople")}</Body>}
    </Screen>
  );
}
