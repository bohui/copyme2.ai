import test from "node:test";
import assert from "node:assert/strict";
import { createMemoirApi } from "@memoir/api-client";
import {
  PrivateDraftSchema,
  PrivateDraftPageSchema,
  ReadPageOptionsSchema,
} from "@memoir/contracts";
const snapshot = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const cursor = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
test("native contracts retain partial draft/proposal coverage rather than claiming the first preview is whole", () => {
  const draft = PrivateDraftSchema.parse({
    preview: { title: "First", text: "Original" },
    snapshot_id: snapshot,
    next_cursor: cursor,
    page_complete: false,
    locale: "zh-CN",
    approval_required: true,
    proposed_preview: { title: "Proposal", text: "Unapproved" },
    publication_approved: false,
  });
  assert.equal(draft.page_complete, false);
  assert.equal(draft.approval_required, true);
  assert.equal(draft.proposed_preview?.text, "Unapproved");
  assert.equal(
    PrivateDraftPageSchema.safeParse({
      snapshot_id: snapshot,
      records: [],
      complete: false,
      next_cursor: cursor,
      publication_approved: true,
    }).success,
    false,
  );
  assert.equal(ReadPageOptionsSchema.safeParse({ limit: 9 }).success, false);
});
test("native draft/event page requests carry opaque cursors and scoped edition snapshot", async () => {
  const paths: string[] = [];
  const api = createMemoirApi({
    baseUrl: "https://fixture.invalid/api/v1/memoir",
    getToken: async () => "synthetic",
    fetch: async (url) => {
      paths.push(url);
      return new Response(
        JSON.stringify(
          url.includes("private-draft/page")
            ? {
                snapshot_id: snapshot,
                records: [],
                complete: true,
                next_cursor: null,
              }
            : {
                events: [{ id: "old", uncertainty: "Name uncertain" }],
                complete: false,
                next_cursor: cursor,
              },
        ),
        { headers: { "content-type": "application/json" } },
      );
    },
  });
  await api.privateDraftPage("p", snapshot, { cursor });
  const page = await api.eventsPage("p", { cursor, limit: 8 });
  assert.equal(page.complete, false);
  assert.equal(page.events[0].uncertainty, "Name uncertain");
  assert.match(paths[0], new RegExp("snapshot_id=" + snapshot));
  assert.equal(
    new URL(paths[0], "https://fixture.invalid").searchParams.has("legacy"),
    false,
  );
  assert.match(paths[1], new RegExp("cursor=" + cursor));
});
