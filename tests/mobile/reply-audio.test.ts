import test from "node:test";
import assert from "node:assert/strict";
import {
  createReplyPlayer,
  type SpokenReply,
} from "../../apps/mobile/src/platform/reply-player";
test("stopping spoken reply before provider completion never begins playback", async () => {
  let resolve!: (reply: SpokenReply) => void;
  let plays = 0;
  const player = createReplyPlayer({
    generate: () =>
      new Promise((r) => {
        resolve = r;
      }),
    play: async () => {
      plays++;
    },
    stop: async () => {},
  });
  const pending = player.play("A remembered place", "en-AU");
  await Promise.resolve();
  await player.stop();
  resolve({ audio_base64: "AA==", mime_type: "audio/mpeg" });
  await pending;
  assert.equal(plays, 0);
});
test("overlong spoken reply does not call speech provider", async () => {
  let calls = 0;
  const player = createReplyPlayer({
    generate: async () => {
      calls++;
      return { audio_base64: "AA==", mime_type: "audio/mpeg" };
    },
    play: async () => {},
    stop: async () => {},
  });
  await assert.rejects(player.play("x".repeat(4097), "en-AU"));
  assert.equal(calls, 0);
});

test("stop during initial player cleanup never calls the speech provider", async () => {
  let finish!: () => void;
  let generated = 0;
  let stops = 0;
  const player = createReplyPlayer({
    stop: () =>
      ++stops === 1
        ? new Promise<void>((resolve) => {
            finish = resolve;
          })
        : Promise.resolve(),
    generate: async () => {
      generated++;
      return { audio_base64: "AA==", mime_type: "audio/mpeg" };
    },
    play: async () => {},
  });
  const pending = player.play("private reply", "en-AU");
  await player.stop();
  finish();
  await pending;
  assert.equal(generated, 0);
});
test("playback receives a generation lease that expires on stop or replacement", async () => {
  let lease: () => boolean = () => false;
  let finish!: () => void;
  const player = createReplyPlayer({
    stop: async () => {},
    generate: async () => ({ audio_base64: "AA==", mime_type: "audio/mpeg" }),
    play: async (_reply, isCurrent) => {
      lease = isCurrent;
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
    },
  });
  const pending = player.play("private reply", "en-AU");
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(lease(), true);
  await player.stop();
  assert.equal(lease(), false);
  finish();
  await pending;
});
