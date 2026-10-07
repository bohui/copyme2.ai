import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const output = execFileSync(
  process.execPath,
  [
    path.join(root, "node_modules/expo/bin/cli"),
    "config",
    "--type",
    "introspect",
    "--json",
  ],
  {
    cwd: path.join(root, "apps/mobile"),
    env: { ...process.env, EXPO_NO_TELEMETRY: "1", EXPO_OFFLINE: "1" },
    encoding: "utf8",
    maxBuffer: 10 * 1024 * 1024,
  },
);
const config = JSON.parse(output);
const manifest = config._internal.modResults.android.manifest.manifest;
const permissions = manifest["uses-permission"] ?? [];
const granted = (name) =>
  permissions.some(
    (permission) =>
      permission.$["android:name"] === name &&
      permission.$["tools:node"] !== "remove",
  );
assert.equal(
  granted("android.permission.RECORD_AUDIO"),
  true,
  "Recording permission must not be blocked by image-picker",
);
assert.equal(
  granted("android.permission.CAMERA"),
  false,
  "Image selection must not grant camera access",
);
assert.equal(
  granted("android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK"),
  false,
  "Playback is foreground-only",
);
assert.equal(
  granted("android.permission.FOREGROUND_SERVICE_MICROPHONE"),
  false,
  "Recording is foreground-only",
);
assert.equal(manifest.application[0].$["android:allowBackup"], "false");
assert.ok(
  !(config.ios.infoPlist.UIBackgroundModes ?? []).includes("audio"),
  "No iOS background audio capability",
);
assert.equal(
  config.ios.infoPlist.NSAppTransportSecurity.NSAllowsArbitraryLoads,
  false,
  "Private API traffic requires HTTPS",
);
assert.equal(
  config.ios.infoPlist.NSFaceIDUsageDescription,
  undefined,
  "Biometric permission is not requested",
);
assert.ok(
  config.plugins.some(
    (plugin) =>
      Array.isArray(plugin) &&
      plugin[0] === "expo-sqlite" &&
      plugin[1]?.useSQLCipher === true,
  ),
);
console.log(
  "Native config introspection passed (not a native binary/device test)",
);
