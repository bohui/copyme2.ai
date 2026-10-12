import React from "react";
import type { CollectionUpdate } from "@memoir/contracts";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react-native";
import Source from "../../apps/mobile/app/source";
import Collection from "../../apps/mobile/app/collection";
import Export from "../../apps/mobile/app/export";
import { shareSourceExport } from "../../apps/mobile/src/platform/export-file";
import {
  context,
  deferred,
  inject,
  projectId,
  type ScreenContext,
} from "./support/fixtures";
jest.mock("../../apps/mobile/src/platform/export-file", () => ({
  shareSourceExport: jest.fn(async () => undefined),
}));
const cursor = "22222222-2222-4222-8222-222222222222";
const first = {
  revision: 1,
  periods: {
    childhood: { status: "recorded", memory_ids: ["unseen"], note: "" },
  },
  ready: false,
  source_fingerprint: "stable",
  sources: [{ id: "first", content: "First private source" }],
  complete: false,
  next_cursor: cursor,
};
const last = {
  ...first,
  sources: [{ id: "later", content: "Later private source" }],
  complete: true,
  next_cursor: null,
};
function api(value: object) {
  return value as ScreenContext["api"];
}
it("reaches later sources and prevents repeated page requests", async () => {
  const later = deferred<typeof last>();
  const collectionPage = jest.fn(() => later.promise);
  const m = inject(
    context({
      api: api({ collection: jest.fn(async () => first), collectionPage }),
    }),
  );
  render(<Source />);
  await screen.findByText("First private source");
  const more = screen.getByRole("button", {
    name: m.t("collectionMoreSources"),
  });
  fireEvent.press(more);
  fireEvent.press(more);
  expect(collectionPage).toHaveBeenCalledTimes(1);
  await act(async () => later.resolve(last));
  expect(await screen.findByText("Later private source")).toBeOnTheScreen();
  expect(screen.getByText("First private source")).toBeOnTheScreen();
  expect(screen.queryByText(m.t("collectionPartial"))).toBeNull();
});
it("rejects changed collection roots instead of combining private pages", async () => {
  const m = inject(
    context({
      api: api({
        collection: jest.fn(async () => first),
        collectionPage: jest.fn(async () => ({
          ...last,
          source_fingerprint: "changed",
        })),
      }),
    }),
  );
  render(<Source />);
  await screen.findByText("First private source");
  fireEvent.press(
    screen.getByRole("button", { name: m.t("collectionMoreSources") }),
  );
  expect(await screen.findByText(m.t("revisionConflict"))).toBeOnTheScreen();
  expect(screen.queryByText("Later private source")).toBeNull();
});
it("discards a page returning after owner and project switch", async () => {
  const later = deferred<typeof last>();
  const m = inject(
    context({
      api: api({
        collection: jest.fn(async (p: string) =>
          p === projectId
            ? first
            : {
                ...last,
                sources: [{ id: "other", content: "New owner private source" }],
              },
        ),
        collectionPage: jest.fn(() => later.promise),
      }),
    }),
  );
  const view = render(<Source />);
  await screen.findByText("First private source");
  fireEvent.press(
    screen.getByRole("button", { name: m.t("collectionMoreSources") }),
  );
  inject({
    ...m,
    projectId: "another",
    session: { ...m.session!, user: { ...m.session!.user, id: "another" } },
  });
  view.rerender(<Source />);
  await screen.findByText("New owner private source");
  await act(async () => later.resolve(last));
  expect(screen.queryByText("Later private source")).toBeNull();
  expect(screen.queryByText("First private source")).toBeNull();
});
it("retains unseen selections when editing and saving a partial collection", async () => {
  const updateCollection = jest.fn(
    async (_project: string, _input: CollectionUpdate) => ({
      ...first,
      revision: 2,
    }),
  );
  const m = inject(
    context({
      api: api({ collection: jest.fn(async () => first), updateCollection }),
    }),
  );
  render(<Collection />);
  await screen.findByText("First private source");
  fireEvent.press(
    screen.getByRole("checkbox", { name: "First private source" }),
  );
  fireEvent.press(screen.getByRole("button", { name: m.t("saveReview") }));
  await screen.findByText(m.t("saved"));
  await act(async () => undefined);
  expect(updateCollection).toHaveBeenCalledTimes(1);
  expect(
    updateCollection.mock.calls[0]![1].periods.childhood!.memory_ids,
  ).toEqual(["unseen", "first"]);
});
it("downloads all result pages and never shares the partial status response", async () => {
  const complete = {
    title: "All",
    sources: [{ id: "first" }, { id: "later" }],
  };
  const completeTaskResult = jest.fn(async () => complete);
  const m = inject(
    context({
      api: api({
        collection: jest.fn(async () => first),
        collectionTask: jest.fn(async () => ({ id: "job" })),
        task: jest.fn(async () => ({
          status: "SUCCEEDED",
          complete: false,
          result: { sources: [{ id: "first" }] },
        })),
        completeTaskResult,
      }),
    }),
  );
  render(<Export />);
  await screen.findByText("First private source");
  fireEvent.press(
    screen.getByRole("checkbox", { name: "First private source" }),
  );
  fireEvent.press(screen.getByRole("button", { name: m.t("export") }));
  fireEvent.press(await screen.findByRole("button", { name: m.t("refresh") }));
  await screen.findByText(m.t("exportPartial"));
  expect(shareSourceExport).not.toHaveBeenCalled();
  fireEvent.press(screen.getByRole("button", { name: m.t("download") }));
  await waitFor(() => expect(shareSourceExport).toHaveBeenCalledWith(complete));
  expect(completeTaskResult).toHaveBeenCalledTimes(1);
});
it("aborts a downloading export on owner switch and never shares its late result", async () => {
  const pending = deferred<Record<string, unknown>>();
  const completeTaskResult = jest.fn(() => pending.promise);
  const m = inject(
    context({
      api: api({
        collection: jest.fn(async () => first),
        collectionTask: jest.fn(async () => ({ id: "job" })),
        task: jest.fn(async () => ({
          status: "SUCCEEDED",
          complete: false,
          result: { sources: [{ id: "first" }] },
        })),
        completeTaskResult,
      }),
    }),
  );
  const view = render(<Export />);
  await screen.findByText("First private source");
  fireEvent.press(
    screen.getByRole("checkbox", { name: "First private source" }),
  );
  fireEvent.press(screen.getByRole("button", { name: m.t("export") }));
  fireEvent.press(await screen.findByRole("button", { name: m.t("refresh") }));
  fireEvent.press(await screen.findByRole("button", { name: m.t("download") }));
  await waitFor(() => expect(completeTaskResult).toHaveBeenCalledTimes(1));
  inject({
    ...m,
    projectId: "another",
    session: { ...m.session!, user: { ...m.session!.user, id: "another" } },
  });
  view.rerender(<Export />);
  await act(async () =>
    pending.resolve({ sources: [{ id: "old", content: "Late secret" }] }),
  );
  expect(shareSourceExport).not.toHaveBeenCalled();
  expect(screen.queryByText(/Late secret/)).toBeNull();
});
it("offers explicit retry for a recoverable failed export without duplicate requests", async () => {
  const pending = deferred<{ status: string }>();
  const retryTask = jest.fn(() => pending.promise);
  const m = inject(
    context({
      api: api({
        collection: jest.fn(async () => first),
        collectionTask: jest.fn(async () => ({ id: "job" })),
        task: jest.fn(async () => ({
          status: "FAILED",
          error: "BOUNDED_JOB_RETRY",
        })),
        retryTask,
      }),
    }),
  );
  render(<Export />);
  await screen.findByText("First private source");
  fireEvent.press(
    screen.getByRole("checkbox", { name: "First private source" }),
  );
  fireEvent.press(screen.getByRole("button", { name: m.t("export") }));
  fireEvent.press(await screen.findByRole("button", { name: m.t("refresh") }));
  const retry = await screen.findByRole("button", { name: m.t("retry") });
  fireEvent.press(retry);
  fireEvent.press(retry);
  expect(retryTask).toHaveBeenCalledTimes(1);
  await act(async () => pending.resolve({ status: "QUEUED" }));
  expect(screen.queryByRole("button", { name: m.t("retry") })).toBeNull();
  expect(shareSourceExport).not.toHaveBeenCalled();
});
