import test from "node:test";
import assert from "node:assert/strict";
import { createMemoirApi } from "@memoir/api-client";
import { fixtureFetch, fixtureProject } from "../../apps/mobile/src/fixtures";
test("the labelled synthetic fixture matches actual current runtime DTOs", async () => {
  const api = createMemoirApi({
    baseUrl: "https://fixture.invalid/api/v1/memoir",
    fetch: fixtureFetch,
    getToken: async () => "synthetic",
  });
  assert.equal((await api.projects()).items[0]?.project_id, fixtureProject);
  assert.equal((await api.history(fixtureProject)).items.length, 1);
  assert.equal(
    (await api.privateDraft(fixtureProject)).preview?.title,
    "The kitchen by the harbour",
  );
  assert.equal((await api.storyState()).is_anonymous, true);
  assert.equal((await api.collection(fixtureProject)).sources?.length, 2);
  await api.readiness(fixtureProject);
});
test("profile settings accepts the existing structured conversation language state", async () => {
  const api = createMemoirApi({
    baseUrl: "https://fixture.invalid/api/v1/memoir",
    fetch: async () =>
      new Response(
        JSON.stringify({
          name: "Alex",
          preferred_language: "zh-CN",
          conversation_language: {
            version: 1,
            initialized: true,
            revision: 2,
            locale: "zh-CN",
            source: "explicit",
          },
        }),
        { headers: { "Content-Type": "application/json" } },
      ),
    getToken: async () => "synthetic",
  });
  const profile = await api.updateProfile({ name: "Alex" });
  assert.deepEqual(profile.conversation_language, {
    version: 1,
    initialized: true,
    revision: 2,
    locale: "zh-CN",
    source: "explicit",
  });
});
