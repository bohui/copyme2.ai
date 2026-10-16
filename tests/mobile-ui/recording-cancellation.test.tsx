import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react-native";
import { router } from "expo-router";
import Record from "../../apps/mobile/app/record";
import { createVault } from "../../apps/mobile/src/platform/vault";
import {
  createRecorderController,
  type PrivateClip,
  type RecorderPort,
} from "../../apps/mobile/src/platform/media";
import { useForegroundRecorder } from "../../apps/mobile/src/platform/use-recorder";
import type { MemoirApi } from "@memoir/api-client";
import { context, inject, ownerId, deferred } from "./support/fixtures";
const clipId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const backendId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const clip: PrivateClip = {
  id: clipId,
  ownerId,
  mimeType: "audio/mp4",
  filename: "recording.m4a",
  durationMs: 1000,
  byteLength: 3,
  base64: "YWJj",
};
const descriptor = {
  id: backendId,
  content_type: "audio/mp4",
  codec: "aac",
  byte_size: 3,
  duration_seconds: 1,
  content_sha256: "a".repeat(64),
  storage_status: "ready",
  transcription_status: "succeeded",
  lifecycle: "draft",
  created_at: "2026-10-16",
  backend_saved: true,
  content_url: `/api/v1/memoir/story/recordings/${backendId}/content`,
};
async function harness(initial: PrivateClip | null) {
  const vault = await createVault(ownerId, "fixture");
  if (initial) await vault.saveMedia(clip.id, clip);
  const start = jest.fn(async () => {});
  const port: RecorderPort = {
    requestPermission: async () => true,
    start,
    pause: async () => {},
    resume: async () => {},
    stop: async () => ({ uri: "file:///synthetic", durationMs: 1000 }),
    seal: async () => {
      await vault.saveMedia(clip.id, clip);
      return clip;
    },
    removeTemporary: async () => {},
    discard: async (value) => vault.deleteMedia(value.id),
    play: async () => {},
    stopPlayback: async () => {},
    release: async () => {},
  };
  const controller = createRecorderController(ownerId, port, initial);
  jest.mocked(useForegroundRecorder).mockImplementation(() => {
    const [snapshot, setSnapshot] = React.useState(controller.getSnapshot());
    React.useEffect(() => controller.subscribe(setSnapshot), []);
    return { controller, snapshot, available: true };
  });
  return { vault, controller, start };
}
it("accept, reenter, cancel and record again clears the local clip while preserving the accepted original", async () => {
  const h = await harness(null);
  let lifecycle = "draft";
  const discardRecording = jest.fn(async () => {
    throw { status: 409 };
  });
  const cancelRecordingUpload = jest.fn(async () => ({
    cancelled: true,
    recording_id: backendId,
    already_attached: lifecycle === "attached",
  }));
  const api = {
    transcribe: jest.fn(async () => ({
      text: "Spoken words",
      source: {},
      recording: { ...descriptor, lifecycle },
    })),
    recording: jest.fn(async () => ({
      recording: { ...descriptor, lifecycle },
    })),
    discardRecording,
    cancelRecordingUpload,
  } as unknown as MemoirApi;
  const m = inject(context({ vault: h.vault, api }));
  const first = render(<Record />);
  fireEvent.press(screen.getByRole("button", { name: m.t("record") }));
  await waitFor(() => expect(h.start).toHaveBeenCalledTimes(1));
  fireEvent.press(screen.getByRole("button", { name: m.t("stop") }));
  await waitFor(() => expect(screen.getByRole("checkbox")).toBeOnTheScreen());
  fireEvent.press(screen.getByRole("checkbox"));
  fireEvent.press(screen.getByRole("button", { name: m.t("transcribe") }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: m.t("useTranscript") }),
    ).toBeOnTheScreen(),
  );
  fireEvent.press(screen.getByRole("button", { name: m.t("useTranscript") }));
  await waitFor(() => expect(m.setDraft).toHaveBeenCalledWith("Spoken words"));
  lifecycle = "attached";
  first.unmount();
  render(<Record />);
  fireEvent.press(screen.getByRole("button", { name: m.t("cancel") }));
  await waitFor(() => expect(h.controller.getSnapshot().clip).toBeNull());
  await waitFor(() => expect(router.back).toHaveBeenCalledTimes(2));
  expect(lifecycle).toBe("attached");
  fireEvent.press(screen.getByRole("button", { name: m.t("record") }));
  await waitFor(() => expect(h.start).toHaveBeenCalledTimes(2));
  expect(await h.vault.get("media." + clipId)).toBeNull();
});
it("retains a durable cancellation key and clears the local recorder while backend cancellation is delayed", async () => {
  const h = await harness(clip);
  const held = deferred<unknown>();
  await h.vault.set("backend-recording:" + clipId, backendId);
  const api = {
    cancelRecordingUpload: jest.fn(() => held.promise),
    discardRecording: jest.fn(() => held.promise),
  } as unknown as MemoirApi;
  const m = inject(context({ vault: h.vault, api }));
  render(<Record />);
  try {
    fireEvent.press(screen.getByRole("button", { name: m.t("cancel") }));
    await waitFor(() => expect(h.controller.getSnapshot().clip).toBeNull());
    const queued = await h.vault.get<{ uploadKey: string }[]>(
      "recording-cancellations",
    );
    expect(queued?.map((value) => value.uploadKey)).toEqual([clipId]);
    fireEvent.press(screen.getByRole("button", { name: m.t("record") }));
    await waitFor(() => expect(h.start).toHaveBeenCalledTimes(1));
  } finally {
    await act(async () =>
      held.resolve({
        cancelled: true,
        recording_id: backendId,
        cleanup_status: "complete",
      }),
    );
  }
});
