import React from "react";
import { fireEvent, render, screen } from "@testing-library/react-native";
import { router } from "expo-router";
import Account from "../../apps/mobile/app/(tabs)/account";
import Privacy from "../../apps/mobile/app/privacy";
import { context, inject } from "./support/fixtures";

it.each(["en-AU", "zh-CN"] as const)(
  "makes unsupported privacy and notification actions explicit in %s",
  (locale) => {
    const m = inject(context({ locale }));
    render(<Privacy />);
    expect(screen.getByText(m.t("aiNotice"))).toBeOnTheScreen();
    expect(screen.getByText(m.t("deleteGate"))).toBeOnTheScreen();
    expect(screen.getByText(m.t("notificationsGate"))).toBeOnTheScreen();
    expect(
      screen.queryByRole("button", { name: m.t("deleteAccount") }),
    ).toBeNull();
    fireEvent.press(screen.getByRole("button", { name: m.t("export") }));
    expect(router.push).toHaveBeenCalledWith("/export");
  },
);

it.each(["en-AU", "zh-CN"] as const)(
  "shows an explicit purchases-unavailable notice without a checkout in %s",
  (locale) => {
    const m = inject(context({ locale }));
    render(<Account />);
    fireEvent.press(screen.getByRole("button", { name: m.t("commerce") }));
    expect(screen.getByText(m.t("commerceGate"))).toBeOnTheScreen();
    expect(router.push).not.toHaveBeenCalled();
    fireEvent.press(screen.getByRole("button", { name: m.t("notifications") }));
    expect(screen.getByText(m.t("notificationsGate"))).toBeOnTheScreen();
  },
);

it("exposes both language choices and preserves guest sign-in entry", () => {
  const m = inject(context());
  render(<Account />);
  fireEvent.press(screen.getByRole("button", { name: "简体中文" }));
  expect(m.setLocale).toHaveBeenCalledWith("zh-CN");
  fireEvent.press(screen.getByRole("button", { name: "English" }));
  expect(m.setLocale).toHaveBeenCalledWith("en-AU");
  fireEvent.press(screen.getByRole("button", { name: m.t("signIn") }));
  expect(router.push).toHaveBeenCalledWith("/sign-in");
});
