import React from "react";
import { Text } from "react-native";
import { router } from "expo-router";
import { useScopedState } from "../src/resource";
import { useMemoir } from "../src/context";
import { useForegroundRecorder } from "../src/platform/use-recorder";
import { transcribeClip, type TranscriptDraft } from "../src/platform/media";
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
export default function Record() {
  const m = useMemoir();
  const { t } = m;
  const { controller, snapshot, available } = useForegroundRecorder(m.vault);
  const [consent, setConsent] = useScopedState(false);
  const [transcript, setTranscript] = useScopedState<TranscriptDraft | null>(
    null,
  );
  const [text, setText] = useScopedState("");
  const [busy, setBusy] = useScopedState(false);
  const [error, setError] = useScopedState("");
  async function transcribe() {
    if (!snapshot.clip || !m.session || !m.api) return;
    setBusy(true);
    try {
      const result = await transcribeClip(snapshot.clip, {
        ownerId: m.session.user.id,
        consent,
        language: m.locale,
        request: (body) => m.api!.transcribe(body),
      });
      setTranscript(result);
      setText(result.text);
    } catch {
      setError(t("error"));
    } finally {
      setBusy(false);
    }
  }
  async function use() {
    if (!transcript) return;
    await m.vault?.set("transcript:" + m.projectId, { ...transcript, text });
    await m.setDraft(text);
    router.back();
  }
  return (
    <Screen>
      <Heading title={t(transcript ? "voiceReview" : "record")} />
      <Body>{t("recorderNote")}</Body>
      {snapshot.error && <Notice text={t("recordPermission")} />}{" "}
      {error && <Notice text={error} />}{" "}
      {!available && <Body>{t("unavailable")}</Body>}
      {transcript ? (
        <>
          <Field
            label={t("voiceReview")}
            value={text}
            onChangeText={setText}
            multiline
          />
          <Button
            title={t("useTranscript")}
            disabled={!text.trim()}
            onPress={() => void use()}
          />
        </>
      ) : (
        <Card>
          <Text accessibilityLiveRegion="polite" style={styles.h2}>
            {snapshot.status === "recording"
              ? t("record")
              : snapshot.clip
                ? t("review")
                : t("ready")}
          </Text>
          {snapshot.status === "recording" ? (
            <Button
              title={t("stop")}
              icon="stop"
              onPress={() => void controller?.stop()}
            />
          ) : (
            !snapshot.clip && (
              <Button
                title={t("record")}
                icon="mic-outline"
                disabled={!available}
                onPress={() => void controller?.start()}
              />
            )
          )}{" "}
          {snapshot.clip && (
            <>
              <Text style={styles.small}>
                {Math.round(snapshot.clip.durationMs / 1000)} s
              </Text>
              <Button
                title={t("review")}
                secondary
                icon="play-outline"
                onPress={() => void controller?.play()}
              />
              <Check
                label={t("recorderNote")}
                checked={consent}
                onPress={() => setConsent(!consent)}
              />
              <Button
                title={t("transcribe")}
                disabled={!consent}
                loading={busy}
                onPress={() => void transcribe()}
              />
            </>
          )}
        </Card>
      )}
      <Button
        title={t("cancel")}
        secondary
        onPress={() =>
          void (controller ? controller.cancel() : Promise.resolve()).then(() =>
            router.back(),
          )
        }
      />
    </Screen>
  );
}
