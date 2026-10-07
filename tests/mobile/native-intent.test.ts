import test from "node:test";
import assert from "node:assert/strict";
import { redirectSystemPath } from "../../apps/mobile/app/+native-intent";
test("native intent rejects malformed/oversized encoded input before third-party router parsing", () => {
  for (const path of [
    "memoir://projects/a?x=" + "%".repeat(4000),
    "memoir://projects/a?x=%E0%A4%A",
    "memoir://projects/a?x=%00",
    "x".repeat(4097),
  ])
    assert.equal(redirectSystemPath({ path, initial: true }), "/");
});
test("bounded valid auth callback and Chinese native path are preserved without exposing content", () => {
  for (const path of [
    "memoir://auth/callback?code=one-time&flow=nonce",
    "memoir://projects/project-one",
    "memoir://source?name=%E4%BD%A0%E5%A5%BD",
  ])
    assert.equal(redirectSystemPath({ path, initial: false }), path);
});
