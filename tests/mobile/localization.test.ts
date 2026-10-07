import test from "node:test";
import assert from "node:assert/strict";
import { messages } from "../../packages/i18n/src/index";
test("both native catalogues have complete nonempty keys", () => {
  assert.deepEqual(
    Object.keys(messages["en-AU"]).sort(),
    Object.keys(messages["zh-CN"]).sort(),
  );
  for (const catalog of Object.values(messages))
    for (const value of Object.values(catalog)) assert.ok(value.trim());
});
