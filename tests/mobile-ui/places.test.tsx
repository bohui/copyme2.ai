import React from "react";
import { act, fireEvent, render, screen } from "@testing-library/react-native";
import Places from "../../apps/mobile/app/places";
import {
  context,
  deferred,
  inject,
  type ScreenContext,
} from "./support/fixtures";

type Api = NonNullable<ScreenContext["api"]>;
type PhotoPage = Awaited<ReturnType<Api["placePhotos"]>>;
const townA = { place: "Town A", period: "1950" };
const townB = { place: "Town B", period: "1960" };
const page = (title: string, cursor: string | null = null): PhotoPage => ({
  items: [{ id: title, title }],
  status: "ready",
  searching: false,
  next_cursor: cursor,
});

async function renderPlaces(placePhotos: Api["placePhotos"]) {
  const m = inject(
    context({
      api: {
        workspaceProfile: jest
          .fn()
          .mockResolvedValue({ memory_places: [townA, townB] }),
        placePhotos,
      } as unknown as Api,
    }),
  );
  const view = render(<Places />);
  const buttons = await screen.findAllByRole("button", { name: m.t("photos") });
  return { m, view, a: buttons[0]!, b: buttons[1]! };
}

it("keeps photos associated with the most recently selected place", async () => {
  const a = deferred<PhotoPage>(),
    b = deferred<PhotoPage>();
  const placePhotos = jest.fn<
    ReturnType<Api["placePhotos"]>,
    Parameters<Api["placePhotos"]>
  >((_project, params) => (params.place === "Town A" ? a.promise : b.promise));
  const view = await renderPlaces(placePhotos);
  fireEvent.press(view.a);
  fireEvent.press(view.b);
  await act(async () => b.resolve(page("Photo from B")));
  await act(async () => a.resolve(page("Photo from A", "a-cursor")));
  expect(screen.getByRole("header", { name: "Town B" })).toBeOnTheScreen();
  expect(screen.queryByText("Photo from A")).toBeNull();
  expect(screen.getByText("Photo from B")).toBeOnTheScreen();
  expect(screen.queryByRole("button", { name: view.m.t("more") })).toBeNull();
});

it("uses request generation when a place is selected again before its first request returns", async () => {
  const firstA = deferred<PhotoPage>(),
    b = deferred<PhotoPage>(),
    latestA = deferred<PhotoPage>();
  const placePhotos = jest
    .fn<ReturnType<Api["placePhotos"]>, Parameters<Api["placePhotos"]>>()
    .mockReturnValueOnce(firstA.promise)
    .mockReturnValueOnce(b.promise)
    .mockReturnValueOnce(latestA.promise);
  const view = await renderPlaces(placePhotos);
  fireEvent.press(view.a);
  fireEvent.press(view.b);
  fireEvent.press(view.a);
  await act(async () => latestA.resolve(page("Latest A photo")));
  await act(async () => firstA.resolve(page("Superseded A photo", "old-a")));
  await act(async () => b.resolve(page("Superseded B photo", "old-b")));
  expect(screen.getByRole("header", { name: "Town A" })).toBeOnTheScreen();
  expect(screen.getByText("Latest A photo")).toBeOnTheScreen();
  expect(screen.queryByText("Superseded A photo")).toBeNull();
  expect(screen.queryByText("Superseded B photo")).toBeNull();
});

it("clears the old pagination cursor immediately when a different place is selected", async () => {
  const b = deferred<PhotoPage>();
  const placePhotos = jest
    .fn<ReturnType<Api["placePhotos"]>, Parameters<Api["placePhotos"]>>()
    .mockResolvedValueOnce(page("First A photo", "a-cursor"))
    .mockReturnValueOnce(b.promise);
  const view = await renderPlaces(placePhotos);
  fireEvent.press(view.a);
  expect(await screen.findByText("First A photo")).toBeOnTheScreen();
  expect(screen.getByRole("button", { name: view.m.t("more") })).toBeEnabled();
  fireEvent.press(view.b);
  expect(screen.queryByRole("button", { name: view.m.t("more") })).toBeNull();
  expect(screen.queryByText("First A photo")).toBeNull();
  expect(placePhotos).toHaveBeenLastCalledWith(view.m.projectId, townB);
  await act(async () => b.resolve(page("First B photo")));
});

it("does not append an old place's pending page or finish the new place's loading state", async () => {
  const moreA = deferred<PhotoPage>(),
    b = deferred<PhotoPage>();
  const placePhotos = jest
    .fn<ReturnType<Api["placePhotos"]>, Parameters<Api["placePhotos"]>>()
    .mockResolvedValueOnce(page("First A photo", "a-cursor"))
    .mockReturnValueOnce(moreA.promise)
    .mockReturnValueOnce(b.promise);
  const view = await renderPlaces(placePhotos);
  fireEvent.press(view.a);
  const more = await screen.findByRole("button", { name: view.m.t("more") });
  fireEvent.press(more);
  fireEvent.press(view.b);
  await act(async () => moreA.resolve(page("Late A page", "a-next-cursor")));
  expect(screen.getByText(view.m.t("loading"))).toBeOnTheScreen();
  expect(screen.queryByText("Late A page")).toBeNull();
  expect(screen.queryByRole("button", { name: view.m.t("more") })).toBeNull();
  await act(async () => b.resolve(page("First B photo")));
  expect(screen.getByText("First B photo")).toBeOnTheScreen();
});

it("admits only one pagination request when More is pressed twice before rerender", async () => {
  const next = deferred<PhotoPage>();
  const placePhotos = jest
    .fn<ReturnType<Api["placePhotos"]>, Parameters<Api["placePhotos"]>>()
    .mockResolvedValueOnce(page("First A photo", "a-cursor"))
    .mockReturnValue(next.promise);
  const view = await renderPlaces(placePhotos);
  fireEvent.press(view.a);
  const more = await screen.findByRole("button", { name: view.m.t("more") });
  act(() => {
    fireEvent.press(more);
    fireEvent.press(more);
  });
  expect(placePhotos).toHaveBeenCalledTimes(2);
  expect(placePhotos).toHaveBeenLastCalledWith(view.m.projectId, {
    ...townA,
    cursor: "a-cursor",
  });
  expect(screen.getByRole("button", { name: view.m.t("more") })).toBeDisabled();
  await act(async () => next.resolve(page("Second A photo")));
  expect(screen.getAllByText("Second A photo")).toHaveLength(1);
});

it("ignores a superseded request failure after the current place succeeds", async () => {
  const a = deferred<PhotoPage>(),
    b = deferred<PhotoPage>();
  const placePhotos = jest
    .fn<ReturnType<Api["placePhotos"]>, Parameters<Api["placePhotos"]>>()
    .mockReturnValueOnce(a.promise)
    .mockReturnValueOnce(b.promise);
  const view = await renderPlaces(placePhotos);
  fireEvent.press(view.a);
  fireEvent.press(view.b);
  await act(async () => b.resolve(page("Current B photo")));
  await act(async () =>
    a.reject(new Error("Synthetic superseded request error")),
  );
  expect(screen.getByText("Current B photo")).toBeOnTheScreen();
  expect(screen.queryByText(view.m.t("error"))).toBeNull();
});
