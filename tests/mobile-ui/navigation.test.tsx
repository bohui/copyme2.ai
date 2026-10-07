import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react-native";
import { router, useLocalSearchParams } from "expo-router";
import Story from "../../apps/mobile/app/(tabs)/story";
import Draft from "../../apps/mobile/app/draft";
import Source from "../../apps/mobile/app/source";
import {
  context,
  deferred,
  inject,
  projectId,
  type ScreenContext,
} from "./support/fixtures";

it("opens a private draft directly from My story without requiring a map", () => {
  const m = inject(context());
  render(<Story />);
  fireEvent.press(screen.getByRole("button", { name: m.t("readDraft") }));
  expect(router.push).toHaveBeenCalledWith("/draft");
  expect(router.push).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("button", { name: m.t("places") })).toBeNull();
});

it("prevents unsigned-in draft navigation", () => {
  const m = inject(context({ session: null }));
  render(<Story />);
  fireEvent.press(screen.getByRole("button", { name: m.t("readDraft") }));
  expect(screen.getByRole("button", { name: m.t("readDraft") })).toBeDisabled();
  expect(router.push).not.toHaveBeenCalled();
});

it.each(["en-AU", "zh-CN"] as const)(
  "renders a readable private draft and source links in %s",
  async (locale) => {
    const privateDraft = jest.fn().mockResolvedValue({
      status: "ready",
      preview: {
        title: "A fictional garden",
        text: "A fictional first paragraph.\n\nA second remembered moment.",
        source_ids: ["fictional-source-1"],
      },
    });
    const m = inject(
      context({
        locale,
        api: { privateDraft } as unknown as ScreenContext["api"],
      }),
    );
    render(<Draft />);
    expect(
      await screen.findByRole("header", { name: "A fictional garden" }),
    ).toBeOnTheScreen();
    expect(screen.getByText("A fictional first paragraph.")).toBeOnTheScreen();
    expect(screen.getByText("A second remembered moment.")).toBeOnTheScreen();
    expect(screen.getByText(m.t("readOnly"))).toBeOnTheScreen();
    expect(screen.queryByRole("button", { name: m.t("save") })).toBeNull();
    expect(privateDraft).toHaveBeenCalledWith(projectId, locale);
    fireEvent.press(screen.getByRole("button", { name: `${m.t("source")} 1` }));
    expect(router.push).toHaveBeenCalledWith({
      pathname: "/source",
      params: { id: "fictional-source-1" },
    });
    // The injected API has only privateDraft: map/place APIs cannot be invoked.
  },
);

it("keeps a previously saved draft visible while reporting generation failure", async () => {
  const m = inject(
    context({
      api: {
        privateDraft: jest.fn().mockResolvedValue({
          status: "failed",
          preview: {
            title: "Saved title",
            text: "Preserved saved prose.",
            source_ids: [],
          },
        }),
        retryPrivateDraft: jest.fn().mockResolvedValue({ status: "pending" }),
      } as unknown as ScreenContext["api"],
    }),
  );
  render(<Draft />);
  expect(await screen.findByText("Preserved saved prose.")).toBeOnTheScreen();
  expect(screen.getByText(m.t("draftError"))).toBeOnTheScreen();
  expect(screen.getByText(m.t("sourceMissing"))).toBeOnTheScreen();
  expect(screen.getByRole("button", { name: m.t("retryDraft") })).toBeEnabled();
});

it("returns an empty-draft reader to the conversation", async () => {
  const m = inject(
    context({
      api: {
        privateDraft: jest.fn().mockResolvedValue({ status: "not_ready" }),
      } as unknown as ScreenContext["api"],
    }),
  );
  render(<Draft />);
  fireEvent.press(await screen.findByRole("button", { name: m.t("resume") }));
  expect(screen.getByText(m.t("draftEmpty"))).toBeOnTheScreen();
  expect(router.replace).toHaveBeenCalledWith("/(tabs)");
});

it("keeps a paragraph citation attached to the exact source version in navigation", async () => {
  const m = inject(
    context({
      api: {
        privateDraft: jest.fn().mockResolvedValue({
          status: "ready",
          preview: {
            title: "A sourced fictional draft",
            text: "Fallback prose.",
          },
          sections: [
            {
              id: "paragraph-1",
              title: "A remembered room",
              text: "Version-cited fictional prose.",
              source_refs: [
                { source_id: "source-uuid", version: "9007199254740993" },
              ],
            },
          ],
        }),
      } as unknown as ScreenContext["api"],
    }),
  );
  render(<Draft />);
  expect(
    await screen.findByText("Version-cited fictional prose."),
  ).toBeOnTheScreen();
  fireEvent.press(screen.getByRole("button", { name: `${m.t("source")} 1` }));
  expect(router.push).toHaveBeenCalledWith({
    pathname: "/source",
    params: { id: "source-uuid", version: "9007199254740993" },
  });
  expect(screen.queryByText("Fallback prose.")).toBeNull();
});

it("does not substitute another source when a versioned reference is unavailable", async () => {
  jest
    .mocked(useLocalSearchParams)
    .mockReturnValue({ id: "source-uuid", version: "7" });
  const sourceDetail = jest
    .fn()
    .mockRejectedValue(new Error("Synthetic stale or inaccessible reference"));
  const collection = jest.fn();
  const m = inject(
    context({
      api: { sourceDetail, collection } as unknown as ScreenContext["api"],
    }),
  );
  render(<Source />);
  expect(await screen.findByText(m.t("sourceMissing"))).toBeOnTheScreen();
  expect(sourceDetail).toHaveBeenCalledWith(projectId, "source-uuid", "7");
  expect(collection).not.toHaveBeenCalled();
});

it("drops an old-owner response arriving after a newer owner and project are displayed", async () => {
  const oldRead = deferred<{
    status: string;
    preview: { title: string; text: string };
  }>();
  const privateDraft = jest
    .fn()
    .mockImplementationOnce(() => oldRead.promise)
    .mockResolvedValue({
      status: "ready",
      preview: { title: "New owner title", text: "New owner fictional prose." },
    });
  const initial = inject(
    context({ api: { privateDraft } as unknown as ScreenContext["api"] }),
  );
  const view = render(<Draft />);
  inject({
    ...initial,
    projectId: "another-story",
    session: {
      access_token: "synthetic-test-only",
      refresh_token: "synthetic-test-only",
      user: { id: "another-fictional-owner", is_anonymous: false },
    },
  });
  view.rerender(<Draft />);
  expect(
    await screen.findByText("New owner fictional prose."),
  ).toBeOnTheScreen();
  await act(async () =>
    oldRead.resolve({
      status: "ready",
      preview: { title: "Old owner title", text: "Old owner fictional prose." },
    }),
  );
  expect(screen.queryByText("Old owner fictional prose.")).toBeNull();
  expect(screen.getByText("New owner fictional prose.")).toBeOnTheScreen();
});
