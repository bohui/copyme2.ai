import React from "react";
import { Text } from "react-native";
import { router } from "expo-router";
import { useScopedState } from "../src/resource";
import { useMemoir } from "../src/context";
import { useForegroundRecorder } from "../src/platform/use-recorder";
import {
  queueRecordingCancellation,
  retryRecordingCancellations,
} from "../src/platform/recording-cancellations";
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
  const [backendRecordingId, setBackendRecordingId] = useScopedState<
    string | null
  >(null);
  const scope = `${m.session?.user.id}:${m.projectId}`;
  const attemptRef = React.useRef({
    scope,
    cancelled: false,
    started: false,
    controller: new AbortController(),
  });
  if (attemptRef.current.scope !== scope)
    attemptRef.current = {
      scope,
      cancelled: false,
      started: false,
      controller: new AbortController(),
    };
  async function discardUploaded(
    clipId: string | undefined,
    knownId?: string | null,
  ) {
    if (clipId && m.vault && m.api) {
      await queueRecordingCancellation(m.vault, clipId, knownId);
      await retryRecordingCancellations(m.vault, m.api);
    } else if (knownId) {
      try {
        await m.api?.discardRecording(knownId);
      } catch (failure) {
        if ((failure as { status?: number }).status !== 409) throw failure;
      }
    }
  }
  React.useEffect(() => {
    if (m.vault && m.api)
      void retryRecordingCancellations(m.vault, m.api).catch(() =>
        setError(t("error")),
      );
  }, [m.vault, m.api]);
  async function beginCapture() {
    attemptRef.current = {
      scope,
      cancelled: false,
      started: false,
      controller: new AbortController(),
    };
    setError("");
    await controller?.start();
  }
  async function cancel() {
    const attempt = attemptRef.current;
    attempt.cancelled = true;
    attempt.controller.abort();
    const clip = snapshot.clip;
    const recordingId =
      backendRecordingId ??
      (clip
        ? await m.vault?.get<string>("backend-recording:" + clip.id)
        : null);
    const reconcile = Boolean(
      clip && (recordingId || attempt.started) && m.vault && m.api,
    );
    // A failed network discard must never prevent releasing the recorder. Save
    // only its opaque retry identity before deleting any local recording bytes.
    if (reconcile)
      await queueRecordingCancellation(m.vault!, clip!.id, recordingId);
    try {
      await controller?.cancel();
    } finally {
      if (clip) await m.vault?.delete("backend-recording:" + clip.id);
      setTranscript(null);
      setBackendRecordingId(null);
      setText("");
      setBusy(false);
      router.back();
    }
    if (reconcile) await retryRecordingCancellations(m.vault!, m.api!);
  }

  async function transcribe() {
    if (!snapshot.clip || !m.session || !m.api) return;
    const vault = m.vault;
    const clip = snapshot.clip;
    const attempt = attemptRef.current;
    attempt.started = true;
    setBusy(true);
    try {
      const priorId =
        backendRecordingId ??
        (await vault?.get<string>("backend-recording:" + clip.id));
      const prior = priorId ? await m.api.recording(priorId) : null;
      if (attempt !== attemptRef.current || attempt.cancelled) return;
      const result = await transcribeClip(clip, {
        ownerId: m.session.user.id,
        consent,
        projectId: m.projectId,
        recordingId: prior?.recording.backend_saved
          ? prior.recording.id
          : undefined,
        language: m.locale,
        request: (body) => {
          if (attempt !== attemptRef.current || attempt.cancelled)
            throw new Error("Recording cancelled");
          return m.api!.transcribe(body, { signal: attempt.controller.signal });
        },
      });
      if (attempt !== attemptRef.current) return;
      if (attempt.cancelled) {
        await discardUploaded(clip.id, result.recordingId);
        return;
      }
      if (vault !== m.vault || vault?.owner !== result.ownerId) return;
      await vault?.set(
        "backend-recording:" + snapshot.clip.id,
        result.recordingId,
      );
      setBackendRecordingId(result.recordingId);
      setTranscript(result);
      setText(result.text);
    } catch (failure) {
      if (attempt !== attemptRef.current) return;
      const saved = failure as { recordingId?: string; backendSaved?: boolean };
      if (attempt.cancelled) {
        await discardUploaded(clip.id, saved.recordingId);
        return;
      }
      if (saved.recordingId) {
        await vault?.set(
          "backend-recording:" + snapshot.clip.id,
          saved.recordingId,
        );
        setBackendRecordingId(saved.recordingId);
      }
      const code = (failure as { code?: string }).code;
      setError(
        t(
          code === "ORIGINAL_RECORDINGS_DISABLED"
            ? "recordingRetentionDisabled"
            : code === "RECORDING_AUTHORITY_REQUIRED"
              ? "recordingAuthorityRequired"
              : code === "RECORDING_PRESERVATION_FAILED"
                ? "recordingNotSavedRetry"
                : saved.backendSaved
                  ? "recordingSavedRetry"
                  : "error",
        ),
      );
    } finally {
      setBusy(false);
    }
  }
  async function use() {
    if (!transcript || attemptRef.current.cancelled) return;
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
          <Notice text={t("originalRecordingSaved")} />
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
                onPress={() =>
                  void beginCapture().catch(() => setError(t("error")))
                }
              />
            )
          )}{" "}
          {snapshot.clip && (
            <>
              <Text style={styles.small}>{t("localRecordingOnly")}</Text>
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
        onPress={() => void cancel().catch(() => setError(t("error")))}
      />
    </Screen>
  );
}
