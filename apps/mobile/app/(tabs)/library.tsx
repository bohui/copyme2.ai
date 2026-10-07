import React from "react";
import { router } from "expo-router";
import { useMemoir } from "../../src/context";
import { Heading, RowLink, Screen } from "../../src/ui";
export default function Library() {
  const { t } = useMemoir();
  return (
    <Screen>
      <Heading title={t("library")} subtitle={t("private")} />
      <RowLink
        title={t("places")}
        body={t("placesBody")}
        icon="location-outline"
        onPress={() => router.push("/places")}
      />
      <RowLink
        title={t("people")}
        body={t("peopleBody")}
        icon="people-outline"
        onPress={() => router.push("/people")}
      />
      <RowLink
        title={t("sources")}
        body={t("exportBody")}
        icon="documents-outline"
        onPress={() => router.push("/source")}
      />
      <RowLink
        title={t("export")}
        body={t("exportBody")}
        icon="download-outline"
        onPress={() => router.push("/export")}
      />
    </Screen>
  );
}
