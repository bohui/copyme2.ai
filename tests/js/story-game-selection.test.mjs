import assert from "node:assert/strict";
import test from "node:test";
import { rankSceneOptions } from "../../apps/web/client/memoir/story-game.mjs";

test("count selection balances life stages and favours recommendations", () => {
  const options = [
    { id: "a", life_stage: "childhood", recommended: false },
    { id: "b", life_stage: "childhood", recommended: true },
    { id: "c", life_stage: "midlife", recommended: true },
    { id: "d", life_stage: "midlife", recommended: false },
  ];
  assert.deepEqual(rankSceneOptions(options).map(o => o.id), ["b", "c", "a", "d"]);
  assert.deepEqual(options.map(o => o.id), ["a", "b", "c", "d"]);
});
