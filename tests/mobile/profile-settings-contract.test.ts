import test from "node:test";
import assert from "node:assert/strict";
import { createMemoirApi } from "@memoir/api-client";
import {
  ProfileSettingsInputSchema,
  ProfileSettingsSchema,
} from "@memoir/contracts";

const automation = {
  schema_version: 1,
  revision: 7,
  auto_enabled: true,
  stopped: true,
  manual_complete: true,
  field_locks: { name: "manual", avatar_style: "preserved" },
  progress: {
    requested_round: 10,
    requested_frontier: 12,
    active_round: 10,
    source_frontier: 12,
    covered_round: 5,
    covered_frontier: 7,
    skipped_round: 0,
    status: "pending",
  },
};

test("mobile settings preserve new fields, control actions and read-only automation", async () => {
  const writes: unknown[] = [];
  const saved = {
    name: null,
    birth_date_expression: "around 1960",
    avatar_style: "female",
    profile_automation: automation,
    conversation_language: {
      version: 1,
      initialized: true,
      locale: "en-AU",
      revision: 2,
    },
  };
  const api = createMemoirApi({
    baseUrl: "https://fixture.invalid/api/v1/memoir",
    getToken: async () => "synthetic",
    fetch: async (_url, options) => {
      if (options?.method === "PATCH")
        writes.push(JSON.parse(String(options.body)));
      return new Response(JSON.stringify(saved), {
        headers: { "Content-Type": "application/json" },
      });
    },
  });
  assert.deepEqual(await api.profile(), saved);
  const changes = {
    birth_date_expression: "around 1960",
    avatar_style: "female" as const,
    name: null,
  };
  assert.deepEqual(await api.updateProfile(changes), saved);
  await api.updateProfile({ profile_confirm_all: true });
  await api.updateProfile({ profile_auto_enabled: true });
  await api.updateProfile({ profile_release_fields: ["avatar_style", "name"] });
  assert.deepEqual(writes, [
    changes,
    { profile_confirm_all: true },
    { profile_auto_enabled: true },
    { profile_release_fields: ["avatar_style", "name"] },
  ]);
});

for (const patch of [
  { profile_automation: automation },
  { story_focus: {} },
  { avatar_style: "other" },
  { birth_date_expression: "x".repeat(121) },
  { birth_year: "1960" },
  { profile_confirm_all: "true" },
  { profile_auto_enabled: null },
  { profile_release_fields: ["preferred_language"] },
  { profile_release_fields: ["name", "name"] },
  { name: "Avery", profile_release_fields: ["name"] },
  { profile_confirm_all: true, profile_auto_enabled: true },
  { profile_confirm_all: true, profile_release_fields: ["name"] },
]) {
  test(`settings input rejects ${JSON.stringify(patch).slice(0, 90)}`, () => {
    assert.equal(ProfileSettingsInputSchema.safeParse(patch).success, false);
  });
}

test("legacy settings responses remain accepted without invented automation state", () => {
  const legacy = {
    name: "Alex",
    conversation_language: { version: 1, source: "explicit" },
  };
  assert.deepEqual(ProfileSettingsSchema.parse(legacy), legacy);
  assert.deepEqual(
    ProfileSettingsInputSchema.parse({ name: "Alex", birth_year: 1960 }),
    { name: "Alex", birth_year: 1960 },
  );
});

test("changed source evidence remains pending until its next scheduled checkpoint", () => {
  const profile = {
    profile_automation: {
      ...automation,
      progress: {
        ...automation.progress,
        active_round: 0,
        covered_round: 10,
        status: "awaiting_checkpoint",
        pending_source_changes: true,
      },
    },
  };
  assert.deepEqual(ProfileSettingsSchema.parse(profile), profile);
});
