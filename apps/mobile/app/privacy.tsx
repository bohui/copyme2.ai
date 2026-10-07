import React from "react";
import { router } from "expo-router";
import { useMemoir } from "../src/context";
import { Body, Card, Heading, RowLink, Screen } from "../src/ui";
export default function Privacy() {
  const { t } = useMemoir();
  return (
    <Screen>
      <Heading title={t("privacy")} />
      <Card>
        <Body>{t("aiNotice")}</Body>
      </Card>
      <RowLink
        title={t("export")}
        body={t("exportBody")}
        icon="download-outline"
        onPress={() => router.push("/export")}
      />
      <Heading title={t("deleteAccount")} />
      <Body>{t("deleteGate")}</Body>
      <Heading title={t("notifications")} />
      <Body>{t("notificationsGate")}</Body>
    </Screen>
  );
}
