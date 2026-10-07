import assert from "node:assert/strict";
import test from "node:test";
import {
  createRecorderController,
  listSavedClips,
  transcribeClip,
  type PrivateClip,
  type RecorderPort,
} from "../../apps/mobile/src/platform/media";
import { createVault } from "../../apps/mobile/src/platform/vault";
const clip: PrivateClip = {
  id: "clip1",
  ownerId: "owner",
  mimeType: "audio/mp4",
  filename: "recording.m4a",
  durationMs: 1000,
  byteLength: 3,
  base64: "YWJj",
};
function recorder(permission = true) {
  const calls: string[] = [];
  let time = 0;
  const port: RecorderPort = {
    requestPermission: async () => {
      calls.push("permission");
      return permission;
    },
    start: async () => {
      calls.push("start");
    },
    pause: async () => {
      calls.push("pause");
    },
    resume: async () => {},
    stop: async () => ({
      uri: "file:///private/recording.m4a",
      durationMs: 1000,
    }),
    seal: async () => {
      calls.push("seal");
      return clip;
    },
    removeTemporary: async () => {
      calls.push("erase");
    },
    discard: async () => {
      calls.push("discard");
    },
    play: async () => {},
    stopPlayback: async () => {},
    release: async () => {},
  };
  return {
    calls,
    controller: createRecorderController("owner", port),
    clock: () => time++,
  };
}
test("no microphone prompt until start; denial keeps typed fallback and never records", async () => {
  const f = recorder(false);
  assert.deepEqual(f.calls, []);
  await f.controller.start();
  assert.deepEqual(f.calls, ["permission"]);
  assert.equal(f.controller.getSnapshot().status, "error");
});
test("foreground stop seals encrypted original before claiming saved and erases temp file", async () => {
  const f = recorder();
  await f.controller.start();
  const result = await f.controller.stop();
  assert.equal(result?.id, "clip1");
  assert.deepEqual(f.calls, ["permission", "start", "seal", "erase"]);
  assert.equal(f.controller.getSnapshot().status, "saved");
});
test("cancel discards without sealing or uploading, including repeated cancel", async () => {
  const f = recorder();
  await f.controller.start();
  await f.controller.cancel();
  await f.controller.cancel();
  assert.equal(f.calls.includes("seal"), false);
  assert.equal(f.controller.getSnapshot().clip, null);
});
test("transcription requires consent, owner and bounded clip and keeps unverified provenance", async () => {
  let sent = 0;
  const request = async () => {
    sent++;
    return { text: "中文记忆", source: { language: "zh" } };
  };
  await assert.rejects(
    transcribeClip(clip, { ownerId: "other", consent: true, request }),
    /owner/i,
  );
  await assert.rejects(
    transcribeClip(clip, { ownerId: "owner", consent: false, request }),
    /consent/i,
  );
  await assert.rejects(
    transcribeClip(
      { ...clip, byteLength: 9e6 },
      { ownerId: "owner", consent: true, request },
    ),
    /limit/i,
  );
  assert.equal(sent, 0);
  const result = await transcribeClip(clip, {
    ownerId: "owner",
    consent: true,
    request,
  });
  assert.equal(result.verified, false);
  assert.equal(result.clipId, "clip1");
  assert.equal(result.text, "中文记忆");
});

test("sealed originals are discoverable after UI reopen and owner-fenced", async () => {
  const vault = await createVault("owner", "fixture");
  await vault.saveMedia(clip.id, clip);
  assert.deepEqual(await listSavedClips(vault), [clip]);
  const other = await createVault("other", "fixture");
  assert.deepEqual(await listSavedClips(other), []);
  await vault.deleteMedia(clip.id);
  assert.deepEqual(await listSavedClips(vault), []);
});

test("ordinary route disposal seals the active clip before temporary removal", async () => {
  const f = recorder();
  await f.controller.start();
  await f.controller.dispose();
  assert.deepEqual(f.calls, ["permission", "start", "seal", "erase"]);
  assert.equal(f.controller.getSnapshot().clip?.id, clip.id);
});
test("disposal with a revoked vault cannot resurrect media and still releases native resources", async () => {
  const vault = await createVault("owner", "fixture");
  const calls: string[] = [];
  const port: RecorderPort = {
    requestPermission: async () => true,
    start: async () => {},
    pause: async () => {},
    resume: async () => {},
    stop: async () => ({ uri: "private", durationMs: 1000 }),
    seal: async () => {
      calls.push("seal");
      await vault.saveMedia(clip.id, clip);
      return clip;
    },
    removeTemporary: async () => {
      calls.push("erase");
    },
    discard: async () => {},
    play: async () => {},
    stopPlayback: async () => {},
    release: async () => {
      calls.push("release");
    },
  };
  const controller = createRecorderController("owner", port);
  await controller.start();
  await vault.clear();
  await assert.rejects(controller.dispose(), /closed/);
  assert.deepEqual(calls, ["seal", "erase", "release"]);
  assert.equal(controller.getSnapshot().clip, null);
});

test("route disposal preserves a clip already being sealed instead of discarding it as stale", async () => {
  const calls: string[] = [];
  let complete!: (value: PrivateClip) => void;
  let markSealing!: () => void;
  const sealing = new Promise<void>((resolve) => {
    markSealing = resolve;
  });
  const port: RecorderPort = {
    requestPermission: async () => true,
    start: async () => {},
    pause: async () => {},
    resume: async () => {},
    stop: async () => ({ uri: "private", durationMs: 1000 }),
    seal: async () => {
      calls.push("seal");
      return new Promise<PrivateClip>((resolve) => {
        complete = resolve;
        markSealing();
      });
    },
    removeTemporary: async () => {
      calls.push("erase");
    },
    discard: async () => {
      calls.push("discard");
    },
    play: async () => {},
    stopPlayback: async () => {},
    release: async () => {
      calls.push("release");
    },
  };
  const controller = createRecorderController("owner", port);
  await controller.start();
  const stopping = controller.stop();
  await sealing;
  const leaving = controller.dispose();
  complete(clip);
  await stopping;
  await leaving;
  assert.equal(calls.filter((call) => call === "seal").length, 1);
  assert.equal(calls.includes("discard"), false);
  assert.equal(controller.getSnapshot().clip?.id, clip.id);
});
test("explicit cancel followed by route disposal never seals discarded audio", async () => {
  const f = recorder();
  await f.controller.start();
  await f.controller.cancel();
  await f.controller.dispose();
  assert.equal(f.calls.includes("seal"), false);
  assert.equal(f.controller.getSnapshot().clip, null);
});
