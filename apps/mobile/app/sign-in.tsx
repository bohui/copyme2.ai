import React, { useEffect, useState } from "react";
import { router } from "expo-router";
import { useMemoir } from "../src/context";
import { Body, Button, Card, Field, Heading, Notice, Screen } from "../src/ui";
export default function SignIn() {
  const { auth, session, t, refresh } = useMemoir();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [transfer, setTransfer] = useState(false);
  useEffect(() => {
    if (!session || session.user.is_anonymous || !auth) return;
    let alive = true;
    void auth
      ?.getPendingTransfer()
      .then((pending) => {
        if (alive) setTransfer(!!pending?.destination && !pending.expired);
      })
      .catch(() => {
        if (alive) setNotice(t("error"));
      });
    return () => {
      alive = false;
    };
  }, [auth, session?.user.id]);
  async function signIn(link = false) {
    setBusy(true);
    setNotice("");
    try {
      if (link) await auth!.signUp(email.trim(), password);
      else await auth!.signInWithPassword(email.trim(), password);
      setPassword("");
      const pending = await auth!.getPendingTransfer();
      if (pending?.destination) setTransfer(true);
      else {
        await refresh();
        router.back();
      }
    } catch (failure) {
      setNotice(
        t(
          failure instanceof Error && failure.message === "LOCAL_WORK_PENDING"
            ? "finishLocalWork"
            : "error",
        ),
      );
    } finally {
      setBusy(false);
    }
  }
  async function confirmTransfer() {
    setBusy(true);
    try {
      await auth!.confirmTransfer();
      await refresh();
      router.back();
    } catch (failure) {
      setNotice(
        t(
          failure instanceof Error && failure.message === "LOCAL_WORK_PENDING"
            ? "finishLocalWork"
            : "error",
        ),
      );
    } finally {
      setBusy(false);
    }
  }
  async function oauth(provider: "apple" | "google") {
    setBusy(true);
    try {
      const outcome = await auth!.signInWithOAuth(provider);
      if (outcome === "cancelled") return;
      const pending = await auth!.getPendingTransfer();
      if (pending?.destination) setTransfer(true);
      else {
        await refresh();
        router.back();
      }
    } catch (failure) {
      setNotice(
        t(
          failure instanceof Error && failure.message === "LOCAL_WORK_PENDING"
            ? "finishLocalWork"
            : "error",
        ),
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <Screen>
      <Heading title={t("signIn")} subtitle={t("guestNotice")} />
      {notice && <Notice text={notice} />}{" "}
      {transfer ? (
        <Card>
          <Body>{t("transferNotice")}</Body>
          <Body>{session?.user.email ?? ""}</Body>
          <Button
            title={t("transfer")}
            loading={busy}
            onPress={() => void confirmTransfer()}
          />
        </Card>
      ) : (
        <>
          <Field
            label={t("email")}
            value={email}
            onChangeText={setEmail}
            keyboardType="email-address"
            textContentType="emailAddress"
            autoCapitalize="none"
            autoComplete="email"
          />
          <Field
            label={t("password")}
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            textContentType="password"
            autoComplete="password"
          />
          <Button
            title={t("signIn")}
            disabled={!auth || !email.trim() || !password}
            loading={busy}
            onPress={() => void signIn()}
          />
          <Button
            title={t("createAccount")}
            secondary
            disabled={!auth || !email.trim() || !password}
            loading={busy}
            onPress={() => void signIn(true)}
          />
          <Button
            title="Apple"
            secondary
            disabled={!auth || busy}
            onPress={() => void oauth("apple")}
          />
          <Button
            title="Google"
            secondary
            disabled={!auth || busy}
            onPress={() => void oauth("google")}
          />
        </>
      )}
      <Button
        title={t("cancel")}
        secondary
        disabled={busy}
        onPress={() => router.back()}
      />
    </Screen>
  );
}
