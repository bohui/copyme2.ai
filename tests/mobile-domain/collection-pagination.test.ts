import test from "node:test";
import assert from "node:assert/strict";
import { createMemoirApi } from "../../packages/api-client/src/index.ts";
const cursor = "22222222-2222-4222-8222-222222222222";
function fixture(read: (url: string) => unknown) {
  return createMemoirApi({
    baseUrl: "https://memoir.example/api/v1/memoir",
    getToken: async () => "owner",
    fetch: async (url) => ({
      ok: true,
      status: 200,
      headers: { "Content-Type": "application/json" },
      text: async () => JSON.stringify(read(url)),
    }),
  });
}
test("collection and task page clients preserve opaque cursors and page completeness", async () => {
  const calls: string[] = [];
  const api = fixture((url) => {
    calls.push(url);
    return {
      revision: 1,
      periods: {},
      ready: false,
      sources: [],
      complete: false,
      next_cursor: cursor,
      source_fingerprint: null,
    };
  });
  const page = await api.collectionPage("project", cursor);
  assert.equal(page.complete, false);
  assert.equal(page.next_cursor, cursor);
  assert.match(calls[0]!, /cursor=/);
  await api.collectionTaskPage("project", cursor);
  assert.match(calls[1]!, /task_cursor=/);
});
test("explicit mobile export collects all pages, preserves source order and rejects root changes", async () => {
  let reads = 0;
  const api = fixture(() => ({
    id: "job",
    kind: "BuildSourceExport",
    status: "SUCCEEDED",
    root_digest: "root",
    complete: ++reads === 2,
    next_cursor: reads === 1 ? cursor : null,
    result: {
      title: "Selected title",
      sources: [{ id: `source-${reads}`, content: `words-${reads}` }],
      coverage: { complete: true },
    },
  }));
  const result = await api.completeTaskResult("job");
  assert.deepEqual(result.sources, [
    { id: "source-1", content: "words-1" },
    { id: "source-2", content: "words-2" },
  ]);
  assert.equal(result.title, "Selected title");
  reads = 0;
  const changing = fixture(() => ({
    id: "job",
    kind: "BuildSourceExport",
    status: "SUCCEEDED",
    root_digest: ++reads === 1 ? "old" : "new",
    complete: false,
    next_cursor: cursor,
    result: { sources: [] },
  }));
  await assert.rejects(changing.completeTaskResult("job"));
});
test("an incomplete task without continuation never becomes a successful export", async () => {
  const api = fixture(() => ({
    id: "job",
    kind: "BuildSourceExport",
    status: "SUCCEEDED",
    complete: false,
    next_cursor: null,
    result: { sources: [] },
  }));
  await assert.rejects(api.completeTaskResult("job"));
});
