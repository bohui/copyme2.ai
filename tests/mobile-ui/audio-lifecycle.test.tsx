import React from "react";
import { act, render } from "@testing-library/react-native";
import { AppState, type AppStateStatus } from "react-native";
import type { MemoirApi } from "@memoir/api-client";
import { createVault } from "../../apps/mobile/src/platform/vault";
import type { PrivateClip } from "../../apps/mobile/src/platform/media";

// Use the real implementation even though ordinary screen tests mock this hook.
const { useReplyAudio } = jest.requireActual<
  typeof import("../../apps/mobile/src/platform/use-reply-audio")
>("../../apps/mobile/src/platform/use-reply-audio");
const { createNativeRecorder } = jest.requireActual<
  typeof import("../../apps/mobile/src/platform/native-media")
>("../../apps/mobile/src/platform/native-media");
let mockModeResolvers: (() => void)[] = [];
const mockPlay = jest.fn();
const mockWrite = jest.fn();
const mockDelete = jest.fn();
const mockPause = jest.fn();
const mockRemove = jest.fn();
const mockRelease = jest.fn();
jest.mock("expo-router", () => ({
  useFocusEffect: (callback: () => void) =>
    jest
      .requireActual<typeof import("react")>("react")
      .useEffect(callback, [callback]),
}));
jest.mock("expo-audio", () => ({
  setAudioModeAsync: () =>
    new Promise<void>((resolve) => {
      mockModeResolvers.push(resolve);
    }),
  createAudioPlayer: () => ({
    play: mockPlay,
    pause: mockPause,
    remove: mockRemove,
  }),
  AudioModule: {
    AudioRecorder: class {
      uri = null;
      currentTime = 0;
      stop = async () => {};
      release = mockRelease;
    },
  },
  RecordingPresets: { HIGH_QUALITY: {} },
}));
jest.mock("expo-crypto", () => ({ randomUUID: () => "fixture" }));
jest.mock("expo-file-system", () => ({
  Paths: { cache: "file:///cache", availableDiskSpace: 100000000 },
  File: class {
    exists = true;
    uri = "file:///cache/fixture";
    write = mockWrite;
    delete() {
      this.exists = false;
      mockDelete();
    }
  },
}));
const api = {
  questionAudio: async () => ({
    audio_base64: "AA==",
    mime_type: "audio/mpeg",
  }),
} as unknown as MemoirApi;
let hook: ReturnType<typeof useReplyAudio>;
const stateListeners = new Set<(state: AppStateStatus) => void>();
function Probe({ owner = "owner-a" }: { owner?: string }) {
  hook = useReplyAudio(api, owner);
  return null;
}
const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));
beforeEach(() => {
  mockModeResolvers = [];
  stateListeners.clear();
  AppState.currentState = "active";
  jest
    .spyOn(AppState, "addEventListener")
    .mockImplementation((_event, listener) => {
      stateListeners.add(listener);
      return {
        remove: () => {
          stateListeners.delete(listener);
        },
      };
    });
});
for (const interruption of [
  "stop",
  "background",
  "unmount",
  "owner-change",
] as const) {
  it(`reply playback does not write plaintext or play after ${interruption} during native mode setup`, async () => {
    const rendered = render(<Probe />);
    await act(tick);
    let pending!: Promise<void>;
    await act(async () => {
      pending = hook.play("reply", "Private fictional reply", "en-AU");
      await tick();
    });
    expect(mockModeResolvers).toHaveLength(1);
    if (interruption === "stop")
      await act(async () => {
        await hook.stop();
      });
    else if (interruption === "background")
      await act(async () => {
        AppState.currentState = "background";
        for (const listener of stateListeners) listener("background");
        await tick();
      });
    else if (interruption === "unmount") rendered.unmount();
    else rendered.rerender(<Probe owner="owner-b" />);
    await act(async () => {
      mockModeResolvers[0]!();
      await pending;
    });
    expect(mockWrite).not.toHaveBeenCalled();
    expect(mockPlay).not.toHaveBeenCalled();
  });
}
it("completed deliberate reply playback is cleaned on stop", async () => {
  render(<Probe />);
  await act(tick);
  let pending!: Promise<void>;
  await act(async () => {
    pending = hook.play("reply", "Fictional reply", "en-AU");
    await tick();
  });
  await act(async () => {
    mockModeResolvers[0]!();
    await pending;
  });
  expect(mockPlay).toHaveBeenCalledTimes(1);
  expect(mockWrite).toHaveBeenCalledTimes(1);
  await act(async () => {
    await hook.stop();
  });
  expect(mockDelete).toHaveBeenCalledTimes(1);
  expect(mockPause).toHaveBeenCalledTimes(1);
  expect(mockRemove).toHaveBeenCalledTimes(1);
});
for (const interruption of ["stop", "background", "dispose"] as const) {
  it(`recorded-clip playback is fenced after ${interruption} during native mode setup`, async () => {
    const vault = await createVault("owner-a", "fixture");
    const clip: PrivateClip = {
      id: "clip",
      ownerId: "owner-a",
      mimeType: "audio/mp4",
      filename: "recording.m4a",
      durationMs: 1000,
      byteLength: 1,
      base64: "AA==",
    };
    await vault.saveMedia(clip.id, clip);
    const controller = await createNativeRecorder(vault);
    const pending = controller.play();
    await tick();
    expect(mockModeResolvers).toHaveLength(1);
    let cleanup: Promise<void> | undefined;
    if (interruption === "stop") await controller.stopPlayback();
    else if (interruption === "background") {
      AppState.currentState = "background";
      for (const listener of stateListeners) listener("background");
    } else cleanup = controller.dispose();
    mockModeResolvers[0]!();
    await pending;
    await cleanup;
    expect(mockWrite).not.toHaveBeenCalled();
    expect(mockPlay).not.toHaveBeenCalled();
    if (!cleanup) await controller.dispose();
  });
}
