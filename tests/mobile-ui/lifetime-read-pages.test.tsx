import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react-native";
import Draft from "../../apps/mobile/app/draft";
import Timeline from "../../apps/mobile/app/timeline";
import {
  context,
  deferred,
  inject,
  projectId,
  type ScreenContext,
} from "./support/fixtures";
const snapshot = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const cursor = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

it.each(["en-AU", "zh-CN"] as const)(
  "reads later draft pages and selects an independent edition in %s",
  async (locale) => {
    const privateDraft = jest
      .fn()
      .mockImplementation(async (_project, language) => ({
        preview: { title: "First", text: `Saved ${language}` },
        locale: language,
        snapshot_id: snapshot,
        next_cursor: cursor,
        page_complete: false,
        approval_required: true,
        proposed_preview: { title: "Proposal", text: "Unapproved proposal" },
        publication_approved: false,
      }));
    const privateDraftPage = jest
      .fn()
      .mockResolvedValue({
        snapshot_id: snapshot,
        records: [
          {
            id: "later",
            preview: { title: "Later", text: "Later saved words" },
          },
        ],
        complete: true,
        next_cursor: null,
      });
    const m = inject(
      context({
        locale,
        api: {
          privateDraft,
          privateDraftPage,
        } as unknown as ScreenContext["api"],
      }),
    );
    render(<Draft />);
    expect(await screen.findByText(`Saved ${locale}`)).toBeOnTheScreen();
    expect(screen.getByText(m.t("draftPagesPartial"))).toBeOnTheScreen();
    expect(
      screen.getAllByText(m.t("draftProposalReadOnly")).length,
    ).toBeGreaterThan(0);
    expect(screen.getByText("Unapproved proposal")).toBeOnTheScreen();
    fireEvent.press(screen.getByRole("button", { name: m.t("loadMoreDraft") }));
    expect(await screen.findByText("Later saved words")).toBeOnTheScreen();
    expect(screen.queryByText(m.t("draftPagesPartial"))).toBeNull();
    expect(privateDraftPage).toHaveBeenCalledWith(projectId, snapshot, {
      cursor,
      legacy: undefined,
    });
    const other = locale === "en-AU" ? "zh-CN" : "en-AU";
    fireEvent.press(
      screen.getByRole("button", {
        name: other === "en-AU" ? "English" : "简体中文",
      }),
    );
    expect(await screen.findByText(`Saved ${other}`)).toBeOnTheScreen();
    expect(screen.queryByText("Later saved words")).toBeNull();
    expect(privateDraft).toHaveBeenLastCalledWith(projectId, other);
    expect(m.setLocale).not.toHaveBeenCalled();
  },
);

it("keeps ambiguous event claims visible while reaching later events and exact evidence", async () => {
  const events = jest
    .fn()
    .mockResolvedValue({
      events: [
        {
          id: "uncertain",
          title: "An uncertain name",
          status: "unresolved",
          assertion: "inferred",
          uncertainty: "Could have been Lin or Lim",
          timing_conflict: true,
          source_refs: [{ quote: "First exact quote" }],
          evidence_next_cursor: cursor,
          details_complete: false,
        },
      ],
      complete: false,
      next_cursor: cursor,
    });
  const eventsPage = jest
    .fn()
    .mockResolvedValue({
      events: [{ id: "later", title: "Later event" }],
      complete: true,
      next_cursor: null,
    });
  const eventEvidencePage = jest
    .fn()
    .mockResolvedValue({
      source_refs: [{ quote: "Older exact quote" }],
      complete: true,
      next_cursor: null,
    });
  const eventDetailsPage = jest
    .fn()
    .mockResolvedValue({
      details: [
        { kind: "temporal_accounts", value: { expression: "Maybe 1958" } },
      ],
      complete: true,
      next_cursor: null,
    });
  const m = inject(
    context({
      api: {
        events,
        eventsPage,
        eventEvidencePage,
        eventDetailsPage,
      } as unknown as ScreenContext["api"],
    }),
  );
  render(<Timeline />);
  expect(
    await screen.findByText("Could have been Lin or Lim"),
  ).toBeOnTheScreen();
  expect(screen.getByText(m.t("eventInferred"))).toBeOnTheScreen();
  expect(screen.getByText(m.t("eventUnresolved"))).toBeOnTheScreen();
  expect(screen.getByText(m.t("eventConflictingDates"))).toBeOnTheScreen();
  fireEvent.press(
    screen.getByRole("button", { name: m.t("loadMoreEvidence") }),
  );
  expect(await screen.findByText("Older exact quote")).toBeOnTheScreen();
  fireEvent.press(
    screen.getByRole("button", { name: m.t("loadMoreEventContext") }),
  );
  expect(await screen.findByText(/Maybe 1958/)).toBeOnTheScreen();
  fireEvent.press(screen.getByRole("button", { name: m.t("loadMoreEvents") }));
  expect(await screen.findByText("Later event")).toBeOnTheScreen();
  expect(screen.queryByText(m.t("timelinePagesPartial"))).toBeNull();
  expect(screen.getByText("Could have been Lin or Lim")).toBeOnTheScreen();
});

it("discards an old-owner draft page after switching projects", async () => {
  const later = deferred<{
    snapshot_id: string;
    records: unknown[];
    complete: boolean;
    next_cursor: null;
  }>();
  const privateDraft = jest
    .fn()
    .mockImplementation(async (project) => ({
      preview: { title: "Saved", text: project },
      snapshot_id: snapshot,
      next_cursor: cursor,
      page_complete: false,
    }));
  const m = inject(
    context({
      api: {
        privateDraft,
        privateDraftPage: jest.fn().mockReturnValue(later.promise),
      } as unknown as ScreenContext["api"],
    }),
  );
  const view = render(<Draft />);
  await screen.findByText(projectId);
  fireEvent.press(screen.getByRole("button", { name: m.t("loadMoreDraft") }));
  inject({
    ...m,
    projectId: "new-project",
    session: { ...m.session!, user: { ...m.session!.user, id: "new-owner" } },
  });
  view.rerender(<Draft />);
  await screen.findByText("new-project");
  await act(async () =>
    later.resolve({
      snapshot_id: snapshot,
      records: [
        { id: "old", preview: { title: "Old", text: "Old private text" } },
      ],
      complete: true,
      next_cursor: null,
    }),
  );
  expect(screen.queryByText("Old private text")).toBeNull();
});
