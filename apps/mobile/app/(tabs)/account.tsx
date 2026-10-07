import React, { useEffect, useState } from "react";
import { Text } from "react-native";
import { router } from "expo-router";
import { useScopedState } from "../../src/resource";
import { useMemoir } from "../../src/context";
import {
  Button,
  Card,
  Heading,
  Notice,
  RowLink,
  Screen,
  styles,
} from "../../src/ui";
export default function Account() {
  const m = useMemoir();
  const { t } = m;
  const [notice, setNotice] = useState("");
  const [pendingTransfer, setPendingTransfer] = useScopedState(false);
  useEffect(() => {
    if (!m.session || m.session.user.is_anonymous || !m.auth) return;
    let alive = true;
    void m.auth
      ?.getPendingTransfer()
      .then((pending) => {
        if (alive)
          setPendingTransfer(!!pending?.destination && !pending.expired);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [m.auth, m.session?.user.id]);
  return (
    <Screen>
      <Heading
        title={t("account")}
        subtitle={m.session?.user.email ?? t("guest")}
      />
      {m.session?.user.is_anonymous && (
        <Card>
          <Text style={styles.body}>{t("guestNotice")}</Text>
          <Button title={t("signIn")} onPress={() => router.push("/sign-in")} />
        </Card>
      )}
      {pendingTransfer && (
        <Card>
          <Text style={styles.body}>{t("transferNotice")}</Text>
          <Button
            title={t("transfer")}
            onPress={() => router.push("/sign-in")}
          />
        </Card>
      )}
      <RowLink
        title={t("profile")}
        icon="person-outline"
        onPress={() => router.push("/profile")}
      />
      <Card>
        <Text style={styles.h3}>{t("language")}</Text>
        <Button
          title={t("english")}
          secondary={m.locale !== "en-AU"}
          onPress={() => void m.setLocale("en-AU")}
        />
        <Button
          title={t("chinese")}
          secondary={m.locale !== "zh-CN"}
          onPress={() => void m.setLocale("zh-CN")}
        />
      </Card>
      <RowLink
        title={t("privacy")}
        icon="shield-checkmark-outline"
        onPress={() => router.push("/privacy")}
      />
      <RowLink
        title={t("commerce")}
        icon="card-outline"
        onPress={() => setNotice(t("commerceGate"))}
      />
      <RowLink
        title={t("notifications")}
        icon="notifications-outline"
        onPress={() => setNotice(t("notificationsGate"))}
      />
      {notice && <Notice text={notice} />}
      <Button
        title={t(m.logoutNeedsRetry ? "retry" : "signOut")}
        secondary
        disabled={
          (!m.session && !m.logoutNeedsRetry) || m.fixture || m.identityBusy
        }
        onPress={() =>
          void m
            .signOut()
            .catch((failure: unknown) =>
              setNotice(
                failure instanceof Error ? failure.message : t("logoutRetry"),
              ),
            )
        }
      />
      {m.fixture && <Text style={styles.small}>{t("fixtureBody")}</Text>}
    </Screen>
  );
}
