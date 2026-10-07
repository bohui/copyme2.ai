import React from "react";
import { FlatList, KeyboardAvoidingView, Platform } from "react-native";
import { act, fireEvent, render, screen } from "@testing-library/react-native";
import { router } from "expo-router";
import Talk from "../../apps/mobile/app/(tabs)/index";
import { useReplyAudio } from "../../apps/mobile/src/platform/use-reply-audio";
import {
  activeTurn,
  context,
  deferred,
  inject,
  projectId,
} from "./support/fixtures";

const languages = [
  {
    locale: "en-AU" as const,
    hello: "Your life, in your words.",
    begin: "Begin my story",
    consent: "I understand and want to begin",
    write: "Write a memory…",
    send: "Send memory",
    saved: "Saved to your account",
    uncertain: "Checking whether this memory was saved",
  },
  {
    locale: "zh-CN" as const,
    hello: "你的人生，由你讲述。",
    begin: "开始讲我的故事",
    consent: "我已了解，开始吧",
    write: "写下一段回忆…",
    send: "发送回忆",
    saved: "已保存到账户",
    uncertain: "正在确认这段回忆是否已保存",
  },
];

describe.each(languages)("Talk in $locale", (labels) => {
  it("requires a deliberate Listen press and exposes Stop for the active reply", () => {
    const play = jest.fn(async () => undefined);
    const speech = {
      play,
      stop: jest.fn(async () => undefined),
      active: null,
      busy: false,
      failed: false,
    };
    jest.mocked(useReplyAudio).mockReturnValue(speech);
    const m = inject(
      context({
        locale: labels.locale,
        messages: [
          {
            id: "fictional-user-message",
            role: "user",
            text: "A fictional memory.",
          },
          {
            id: "fictional-reply",
            role: "assistant",
            text: "A fictional reply to read aloud.",
          },
        ],
      }),
    );
    const view = render(<Talk />);
    expect(play).not.toHaveBeenCalled();
    expect(screen.getAllByRole("button", { name: m.t("listen") })).toHaveLength(
      1,
    );
    fireEvent.press(screen.getByRole("button", { name: m.t("listen") }));
    expect(play).toHaveBeenCalledWith(
      "fictional-reply",
      "A fictional reply to read aloud.",
      labels.locale,
    );
    jest
      .mocked(useReplyAudio)
      .mockReturnValue({ ...speech, active: "fictional-reply" });
    view.rerender(<Talk />);
    expect(screen.queryByRole("button", { name: m.t("listen") })).toBeNull();
    fireEvent.press(screen.getByRole("button", { name: m.t("stopPlayback") }));
    expect(play).toHaveBeenCalledTimes(2);
    // The hook owns the toggle and hardware cleanup; this checks the screen action.
  });

  it("requires explicit AI-processing consent before a guest can begin", async () => {
    const m = inject(context({ locale: labels.locale, session: null }));
    render(<Talk />);
    expect(
      screen.getByRole("header", { name: labels.hello }),
    ).toBeOnTheScreen();
    const begin = screen.getByRole("button", { name: labels.begin });
    expect(begin).toBeDisabled();
    fireEvent.press(begin);
    expect(m.begin).not.toHaveBeenCalled();
    expect(screen.getByText(m.t("aiNotice"))).toBeOnTheScreen();
    fireEvent.press(screen.getByRole("checkbox", { name: labels.consent }));
    expect(
      screen.getByRole("checkbox", { name: labels.consent }),
    ).toBeChecked();
    expect(begin).toBeEnabled();
    await act(async () => fireEvent.press(begin));
    expect(m.begin).toHaveBeenCalledTimes(1);
  });

  it("provides labelled multiline writing and prevents a blank send", () => {
    const m = inject(context({ locale: labels.locale }));
    const view = render(<Talk />);
    const input = screen.getByLabelText(labels.write);
    expect(input.props.multiline).toBe(true);
    expect(screen.getByRole("button", { name: labels.send })).toBeDisabled();
    fireEvent.changeText(input, "A fictional memory");
    expect(m.setDraft).toHaveBeenCalledWith("A fictional memory");
    inject({ ...m, draft: "A fictional memory" });
    view.rerender(<Talk />);
    fireEvent.press(screen.getByRole("button", { name: labels.send }));
    expect(m.send).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: m.t("record") })).toBeEnabled();
  });

  it("never calls an uncommitted reply saved, and retries the same operation", () => {
    const active = activeTurn({
      phase: "uncertain",
      reply: "A provisional fictional reply",
      replyComplete: true,
    });
    const m = inject(context({ locale: labels.locale, active }));
    const view = render(<Talk />);
    expect(screen.getByText("A provisional fictional reply")).toBeOnTheScreen();
    expect(screen.getByText(labels.uncertain)).toBeOnTheScreen();
    expect(screen.queryByText(labels.saved)).toBeNull();
    fireEvent.press(screen.getByRole("button", { name: m.t("retry") }));
    expect(m.retry).toHaveBeenCalledWith(active.item);
    inject({
      ...m,
      active: {
        ...active,
        state: {
          ...active.state,
          committed: true,
          phase: "conversation_committed",
        },
      },
    });
    view.rerender(<Talk />);
    expect(screen.getByText(labels.saved)).toBeOnTheScreen();
    expect(screen.queryByText(labels.uncertain)).toBeNull();
    expect(screen.queryByRole("button", { name: m.t("retry") })).toBeNull();
  });
});

it("keeps live reply submission disabled while allowing the draft to remain readable", () => {
  const m = inject(
    context({
      draft: "A second memory is still here",
      active: activeTurn({ phase: "receiving", reply: "Listening…" }),
    }),
  );
  render(<Talk />);
  expect(screen.getByDisplayValue(m.draft)).toBeOnTheScreen();
  expect(screen.getByRole("button", { name: m.t("send") })).toBeDisabled();
  expect(screen.queryByText(m.t("saved"))).toBeNull();
});

it("exposes keyboard-aware layout properties and handled list taps", () => {
  inject(context());
  const view = render(<Talk />);
  expect(Platform.OS).toBe(
    process.env.MEMOIR_TEST_PLATFORM === "android" ? "android" : "ios",
  );
  const avoiding = view.UNSAFE_getByType(KeyboardAvoidingView);
  expect(avoiding.props.behavior).toBe(
    Platform.OS === "ios" ? "padding" : undefined,
  );
  expect(avoiding.props.keyboardVerticalOffset).toBeGreaterThanOrEqual(0);
  expect(view.UNSAFE_getByType(FlatList).props.keyboardShouldPersistTaps).toBe(
    "handled",
  );
  // Property inspection is not evidence that the OS keyboard avoids the composer.
});

it("does not offer a fake guest session when the backend is unconfigured", () => {
  const m = inject(context({ session: null, configured: false }));
  render(<Talk />);
  expect(screen.getByText(m.t("configureBody"))).toBeOnTheScreen();
  expect(screen.queryByRole("button", { name: m.t("begin") })).toBeNull();
  expect(m.begin).not.toHaveBeenCalled();
});

it("labels synthetic previews explicitly and routes the recording action", () => {
  const m = inject(context({ fixture: true }));
  render(<Talk />);
  expect(screen.getByText(m.t("fixture"))).toBeOnTheScreen();
  fireEvent.press(screen.getByRole("button", { name: m.t("record") }));
  expect(router.push).toHaveBeenCalledWith("/record");
});

it("shows only queued recovery work for the selected project", () => {
  const selected = activeTurn().item;
  const other = {
    ...selected,
    operationId: "another-operation",
    projectId: "another-story",
  };
  const m = inject(context({ projectId, pending: [other, selected] }));
  render(<Talk />);
  const retries = screen.getAllByRole("button", { name: m.t("retry") });
  expect(retries).toHaveLength(1);
  fireEvent.press(retries[0]!);
  expect(m.retry).toHaveBeenCalledWith(selected);
});

it("prevents repeated guest onboarding submissions while the first attempt is pending", async () => {
  const pending = deferred<void>();
  const begin = jest.fn(() => pending.promise);
  const m = inject(context({ session: null, begin }));
  render(<Talk />);
  fireEvent.press(screen.getByRole("checkbox", { name: m.t("consent") }));
  fireEvent.press(screen.getByRole("button", { name: m.t("begin") }));
  expect(screen.getByRole("button", { name: m.t("begin") })).toBeDisabled();
  fireEvent.press(screen.getByRole("button", { name: m.t("begin") }));
  expect(begin).toHaveBeenCalledTimes(1);
  await act(async () => pending.resolve());
});

it("keeps the composer usable when spoken reply playback is unavailable", () => {
  jest.mocked(useReplyAudio).mockReturnValue({
    play: jest.fn(async () => undefined),
    stop: jest.fn(async () => undefined),
    active: null,
    busy: false,
    failed: true,
  });
  const m = inject(context({ draft: "Typing can continue." }));
  render(<Talk />);
  expect(screen.getByText(m.t("unavailable"))).toBeOnTheScreen();
  expect(screen.getByDisplayValue("Typing can continue.")).toBeOnTheScreen();
  expect(screen.getByRole("button", { name: m.t("send") })).toBeEnabled();
});

it("does not offer spoken playback for user messages or oversized replies", () => {
  const m = inject(
    context({
      messages: [
        {
          id: "fictional-user-message",
          role: "user",
          text: "Private user words.",
        },
        {
          id: "oversized-fictional-reply",
          role: "assistant",
          text: "x".repeat(4097),
        },
      ],
    }),
  );
  render(<Talk />);
  expect(screen.queryByRole("button", { name: m.t("listen") })).toBeNull();
});

it("does not accept ephemeral composing before the encrypted vault and project are ready", () => {
  const m = inject(
    context({ vault: null, projectId: "", draft: "Not durably saved yet" }),
  );
  render(<Talk />);
  expect(screen.getByLabelText(m.t("write")).props.editable).toBe(false);
  expect(screen.getByRole("button", { name: m.t("send") })).toBeDisabled();
});
