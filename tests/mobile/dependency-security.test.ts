import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { redirectSystemPath } from "../../apps/mobile/app/+native-intent";

const require = createRequire(import.meta.url);

test("xcode uses the patched CommonJS UUID implementation without changing project IDs", () => {
  const xcodeRequire = createRequire(require.resolve("xcode/package.json"));
  const version = xcodeRequire("uuid/package.json") as { version: string };
  assert.equal(version.version, "11.1.1");
  const Project = require("xcode/lib/pbxProject") as {
    prototype: { generateUuid(this: { allUuids(): string[] }): string };
  };
  const ids: string[] = [];
  for (let index = 0; index < 1000; index++) {
    const id = Project.prototype.generateUuid.call({ allUuids: () => ids });
    assert.match(id, /^[A-F0-9]{24}$/);
    assert.ok(!ids.includes(id));
    ids.push(id);
  }
});

test("guarded native URLs use the installed Expo parser without its vulnerable decoder", () => {
  const decoderPath = require.resolve("decode-uri-component");
  require(decoderPath);
  const decoder = require.cache[decoderPath]!;
  const original = decoder.exports;
  let calls = 0;
  decoder.exports = () => {
    calls++;
    throw new Error("Vulnerable decoder reached by guarded native URL");
  };
  try {
    const { extractExpoPathFromURL } = require(
      "expo-router/build/fork/extractPathFromURL.js",
    ) as { extractExpoPathFromURL(prefixes: string[], path: string): string };
    const { parseQueryParams } = require(
      "expo-router/build/fork/getStateFromPath-forks.js",
    ) as {
      parseQueryParams(
        path: string,
        route: { name: string },
        config: undefined,
        prefix: string,
      ): Record<string, string>;
    };
    for (const initial of [true, false]) {
      for (const path of [
        "memoir://source?id=abc",
        "memoir://auth/callback?code=synthetic&flow=nonce",
        "memoir://source?text=%E4%BD%A0%E5%A5%BD",
        "memoir://source?text=" + "%ED%A0%80".repeat(400),
        "memoir://source?text=" + "%25E0".repeat(650),
        "memoir://source?text=" + "%E0%A4%A".repeat(400),
        "memoir://source?text=" + "%FE%FF".repeat(450),
        "memoir://source?text=" + "x".repeat(5000),
      ]) {
        const guarded = redirectSystemPath({ path, initial });
        assert.ok(guarded.length <= 4096);
        const extracted = extractExpoPathFromURL([], guarded);
        const params = parseQueryParams(extracted, { name: "source" }, undefined, "");
        if (path.includes("text=%E4")) assert.equal(params.text, "你好");
        if (path.length > 4096) assert.equal(guarded, "/");
      }
    }
    assert.equal(calls, 0);
  } finally {
    decoder.exports = original;
  }
});
