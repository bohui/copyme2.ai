import React from "react";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react-native";
import { router } from "expo-router";
import SignIn from "../../apps/mobile/app/sign-in";
import Record from "../../apps/mobile/app/record";
import { useForegroundRecorder } from "../../apps/mobile/src/platform/use-recorder";
import {
  context,
  deferred,
  inject,
  type ScreenContext,
} from "./support/fixtures";

it("keeps the guest draft and session when OAuth is cancelled", async () => {
  const signInWithOAuth = jest.fn().mockResolvedValue("cancelled");
  const getPendingTransfer = jest.fn();
  const m = inject(
    context({
      draft: "Unsent fictional guest memory",
      auth: {
        signInWithOAuth,
        getPendingTransfer,
      } as unknown as ScreenContext["auth"],
    }),
  );
  render(<SignIn />);
  fireEvent.press(screen.getByRole("button", { name: "Google" }));
  await waitFor(() => expect(signInWithOAuth).toHaveBeenCalledWith("google"));
  await act(async () => undefined);
  expect(m.session?.user.is_anonymous).toBe(true);
  expect(m.draft).toBe("Unsent fictional guest memory");
  expect(m.setDraft).not.toHaveBeenCalled();
  expect(m.signOut).not.toHaveBeenCalled();
  expect(m.refresh).not.toHaveBeenCalled();
  expect(getPendingTransfer).not.toHaveBeenCalled();
  expect(router.back).not.toHaveBeenCalled();
  expect(screen.queryByText(m.t("error"))).toBeNull();
  expect(screen.getByRole("button", { name: "Google" })).toBeEnabled();
});

it("blocks repeated and competing OAuth presses until cancellation resolves", async () => {
  const outcome = deferred<"cancelled">();
  const signInWithOAuth = jest.fn(() => outcome.promise);
  inject(
    context({ auth: { signInWithOAuth } as unknown as ScreenContext["auth"] }),
  );
  render(<SignIn />);
  fireEvent.press(screen.getByRole("button", { name: "Google" }));
  expect(screen.getByRole("button", { name: "Google" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Apple" })).toBeDisabled();
  fireEvent.press(screen.getByRole("button", { name: "Google" }));
  fireEvent.press(screen.getByRole("button", { name: "Apple" }));
  expect(signInWithOAuth).toHaveBeenCalledTimes(1);
  await act(async () => outcome.resolve("cancelled"));
  expect(screen.getByRole("button", { name: "Google" })).toBeEnabled();
});

it("labels email and secure password fields and preserves typed email after failed login", async () => {
  const signInWithPassword = jest
    .fn()
    .mockRejectedValue(new Error("Synthetic authentication error"));
  const m = inject(
    context({
      auth: { signInWithPassword } as unknown as ScreenContext["auth"],
    }),
  );
  render(<SignIn />);
  const email = screen.getByLabelText(m.t("email"));
  const password = screen.getByLabelText(m.t("password"));
  expect(email.props.keyboardType).toBe("email-address");
  expect(email.props.autoCapitalize).toBe("none");
  expect(password.props.secureTextEntry).toBe(true);
  fireEvent.changeText(email, "fictional@example.invalid");
  fireEvent.changeText(password, "synthetic-placeholder-only");
  fireEvent.press(screen.getByRole("button", { name: m.t("signIn") }));
  expect(await screen.findByText(m.t("error"))).toBeOnTheScreen();
  expect(
    screen.getByDisplayValue("fictional@example.invalid"),
  ).toBeOnTheScreen();
  expect(router.back).not.toHaveBeenCalled();
});

it.each(["en-AU", "zh-CN"] as const)(
  "offers working Cancel when recording is unavailable in %s",
  async (locale) => {
    const m = inject(context({ locale }));
    jest.mocked(useForegroundRecorder).mockReturnValue({
      controller: null,
      available: false,
      snapshot: { status: "idle", clip: null, error: null },
    });
    render(<Record />);
    expect(screen.getByText(m.t("unavailable"))).toBeOnTheScreen();
    expect(screen.getByRole("button", { name: m.t("record") })).toBeDisabled();
    fireEvent.press(screen.getByRole("button", { name: m.t("cancel") }));
    await waitFor(() => expect(router.back).toHaveBeenCalledTimes(1));
    expect(m.send).not.toHaveBeenCalled();
    expect(m.setDraft).not.toHaveBeenCalled();
  },
);

it("keeps microphone denial visible alongside the ability to cancel", () => {
  const m = inject(context());
  jest.mocked(useForegroundRecorder).mockReturnValue({
    controller: null,
    available: false,
    snapshot: {
      status: "error",
      clip: null,
      error: "Synthetic permission denial",
    },
  });
  render(<Record />);
  expect(screen.getByText(m.t("recordPermission"))).toBeOnTheScreen();
  expect(screen.getByRole("button", { name: m.t("cancel") })).toBeEnabled();
});

it("returns to the story after successful OAuth with no pending guest transfer", async () => {
  const signInWithOAuth = jest.fn().mockResolvedValue("signed-in");
  const getPendingTransfer = jest.fn().mockResolvedValue(null);
  const m = inject(
    context({
      auth: {
        signInWithOAuth,
        getPendingTransfer,
      } as unknown as ScreenContext["auth"],
    }),
  );
  render(<SignIn />);
  fireEvent.press(screen.getByRole("button", { name: "Apple" }));
  await waitFor(() => expect(m.refresh).toHaveBeenCalledTimes(1));
  expect(router.back).toHaveBeenCalledTimes(1);
});

it("lets a guest dismiss sign-in without altering the unsent memory", () => {
  const m = inject(context({ draft: "A preserved fictional guest draft" }));
  render(<SignIn />);
  fireEvent.press(screen.getByRole("button", { name: m.t("cancel") }));
  expect(router.back).toHaveBeenCalledTimes(1);
  expect(m.setDraft).not.toHaveBeenCalled();
  expect(m.signOut).not.toHaveBeenCalled();
});

it("waits for explicit transfer confirmation and prevents duplicate transfer taps", async () => {
  const outcome = deferred<void>();
  const confirmTransfer = jest.fn(() => outcome.promise);
  const auth = {
    signInWithOAuth: jest.fn().mockResolvedValue("signed-in"),
    getPendingTransfer: jest
      .fn()
      .mockResolvedValue({ destination: "fictional-destination" }),
    confirmTransfer,
  };
  const m = inject(context({ auth: auth as unknown as ScreenContext["auth"] }));
  render(<SignIn />);
  fireEvent.press(screen.getByRole("button", { name: "Google" }));
  const transfer = await screen.findByRole("button", { name: m.t("transfer") });
  expect(screen.getByText(m.t("transferNotice"))).toBeOnTheScreen();
  expect(confirmTransfer).not.toHaveBeenCalled();
  expect(router.back).not.toHaveBeenCalled();
  fireEvent.press(transfer);
  expect(screen.getByRole("button", { name: m.t("transfer") })).toBeDisabled();
  expect(screen.getByRole("button", { name: m.t("cancel") })).toBeDisabled();
  fireEvent.press(transfer);
  expect(confirmTransfer).toHaveBeenCalledTimes(1);
  await act(async () => outcome.resolve());
  await waitFor(() => expect(m.refresh).toHaveBeenCalledTimes(1));
  expect(router.back).toHaveBeenCalledTimes(1);
});

it("recovers an interrupted prepared transfer when the destination account reopens sign-in", async () => {
  const getPendingTransfer = jest.fn(async () => ({
    destination: { id: "destination" },
    expired: false,
  }));
  const m = inject(
    context({
      session: {
        access_token: "synthetic",
        refresh_token: "synthetic",
        user: { id: "destination", is_anonymous: false },
      },
      auth: { getPendingTransfer } as unknown as ScreenContext["auth"],
    }),
  );
  render(<SignIn />);
  expect(
    await screen.findByRole("button", { name: m.t("transfer") }),
  ).toBeEnabled();
  expect(screen.queryByRole("button", { name: m.t("signIn") })).toBeNull();
});
