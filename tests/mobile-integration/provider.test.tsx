import React from "react";
import { act, render, waitFor } from "@testing-library/react-native";
import { MemoirProvider, useMemoir } from "../../apps/mobile/src/context";
import { TransferInputSchema, type TransferInput } from "@memoir/contracts";
import type { TurnOutboxItem } from "@memoir/memoir-domain";
import type { FetchResponse } from "@memoir/api-client";
import {
  authPort,
  cleanupMedia,
  createSupabase,
  deferred,
  jsonResponse,
  projectsResponse,
  publicAuth,
  requestCount,
  runtime,
  seedVault,
  sessionFor,
  storyResponse,
} from "./support/runtime";

type ProviderState = ReturnType<typeof useMemoir>;
let current: ProviderState | null = null;
function Probe() {
  current = useMemoir();
  return null;
}
function state() {
  if (!current) throw new Error("Provider has not rendered");
  return current;
}
async function mount() {
  current = null;
  const view = render(
    <MemoirProvider>
      <Probe />
    </MemoirProvider>,
  );
  await waitFor(() => expect(state().session?.user.id).toBe("owner-a"));
  await waitFor(() => expect(state().vault).not.toBeNull());
  await act(async () => undefined);
  return view;
}
async function switchOwner() {
  runtime.session = sessionFor("owner-b");
  await act(async () => {
    await state().auth!.getSession();
  });
  await waitFor(() => expect(state().session?.user.id).toBe("owner-b"));
  await waitFor(() => expect(state().storyState?.user_id).toBe("owner-b"));
}

it("clears the private vault after auth revokes the session and disposes the controller", async () => {
  const vault = await seedVault();
  const clear = jest.spyOn(vault, "clear");
  const logout = deferred<{ error: null }>();
  authPort.signOut.mockReturnValueOnce(logout.promise);
  await mount();
  let completion!: Promise<void>;
  await act(async () => {
    completion = state().signOut();
  });
  expect(state().session).toBeNull();
  expect(state().vault).toBeNull();
  expect(state().storyState).toBeNull();
  expect(state().projects).toEqual([]);
  expect(state().projectId).toBe("");
  // Capture rejection immediately so the intentionally red test has no unhandled rejection.
  const outcome = completion.then(
    () => "cleared",
    (failure: unknown) => failure,
  );
  await act(async () => {
    logout.resolve({ error: null });
    await outcome;
  });
  expect(await outcome).toBe("cleared");
  expect(clear).toHaveBeenCalledTimes(1);
  expect(cleanupMedia).toHaveBeenCalledTimes(1);
  await expect(vault.get("composer:project-owner-a")).rejects.toThrow(
    "Vault closed",
  );
});

it("retains failed logout cleanup for retry and prevents switching accounts meanwhile", async () => {
  const vault = await seedVault();
  const realClear = vault.clear.bind(vault);
  const clear = jest
    .spyOn(vault, "clear")
    .mockRejectedValueOnce(new Error("Synthetic erasure interrupted"))
    .mockImplementation(realClear);
  await mount();
  await act(async () => {
    await expect(state().signOut()).rejects.toThrow();
  });
  expect(state().session).toBeNull();
  await act(async () => {
    await expect(
      state().auth!.signInWithPassword(
        "fictional@example.invalid",
        "synthetic",
      ),
    ).rejects.toThrow("cleanup");
  });
  expect(authPort.signInWithPassword).not.toHaveBeenCalled();
  await act(async () => {
    await expect(state().signOut()).resolves.toBeUndefined();
  });
  expect(clear).toHaveBeenCalledTimes(2);
  await expect(vault.get("active-project")).rejects.toThrow("Vault closed");
});

it("restores and persists the local active project and composer while project discovery is offline", async () => {
  const vault = await seedVault();
  await vault.set("active-project", "saved-local-project");
  await vault.set(
    "composer:saved-local-project",
    "Previously saved fictional draft",
  );
  runtime.routes.set("/user/projects", async () => {
    throw new Error("Synthetic offline discovery");
  });
  await mount();
  expect(state().projectId).toBe("saved-local-project");
  expect(state().draft).toBe("Previously saved fictional draft");
  await act(async () => {
    await state().setDraft("Typed while offline");
  });
  expect(await vault.get("composer:saved-local-project")).toBe(
    "Typed while offline",
  );
});

it("uses build-pinned public Supabase config to cold-start without API config discovery", async () => {
  const vault = await seedVault();
  await vault.set("active-project", "saved-local-project");
  await vault.set(
    "composer:saved-local-project",
    "Restored before the API is reachable",
  );
  runtime.routes.set("/agent/config", async () => {
    throw new Error("Synthetic API offline");
  });
  runtime.routes.set("/user/projects", async () => {
    throw new Error("Synthetic API offline");
  });
  await mount();
  expect(requestCount("/agent/config")).toBe(0);
  expect(createSupabase).toHaveBeenCalledWith(
    publicAuth.url,
    publicAuth.publishableKey,
    expect.any(Object),
  );
  expect(state().draft).toBe("Restored before the API is reachable");
});

it("blocks a guest-to-existing-account switch before an unsent composer can disappear", async () => {
  runtime.session = sessionFor("owner-a", true);
  const vault = await seedVault();
  await mount();
  await act(async () => {
    await state().setDraft("Unsent fictional guest memory");
  });
  await act(async () => {
    await expect(
      state().auth!.signInWithPassword(
        "fictional@example.invalid",
        "synthetic",
      ),
    ).rejects.toThrow();
  });
  expect(authPort.signInWithPassword).not.toHaveBeenCalled();
  expect(requestCount("/user/conversation-transfer")).toBe(0);
  expect(state().session?.user.id).toBe("owner-a");
  expect(state().draft).toBe("Unsent fictional guest memory");
  expect(await vault.get("composer:project-owner-a")).toBe(
    "Unsent fictional guest memory",
  );
});

it("does not render an old owner's late story-state response after account switch", async () => {
  const late = deferred<FetchResponse>();
  runtime.routes.set("/story/state", async (_url, init) =>
    init.headers.Authorization === "Bearer synthetic-owner-a"
      ? late.promise
      : storyResponse("owner-b"),
  );
  await mount();
  expect(requestCount("/story/state")).toBe(1);
  await switchOwner();
  await act(async () => {
    late.resolve(storyResponse("owner-a"));
  });
  expect(state().storyState?.user_id).toBe("owner-b");
});

it("does not let an old owner's refresh replace the new owner's project list", async () => {
  await mount();
  const late = deferred<FetchResponse>();
  runtime.routes.set("/user/projects", async (_url, init) =>
    init.headers.Authorization === "Bearer synthetic-owner-a"
      ? late.promise
      : projectsResponse("owner-b"),
  );
  let refresh!: Promise<void>;
  await act(async () => {
    refresh = state().refresh();
  });
  await switchOwner();
  await act(async () => {
    late.resolve(projectsResponse("owner-a"));
    await refresh;
  });
  expect(state().projects.map((project) => project.project_id)).toEqual([
    "project-owner-b",
  ]);
  expect(state().projectId).toBe("project-owner-b");
  expect(state().storyState?.user_id).toBe("owner-b");
});

it("blocks existing-account transfer when a sealed recording remains in the guest vault", async () => {
  runtime.session = sessionFor("owner-a", true);
  const vault = await seedVault();
  await vault.saveMedia("clip-a", {
    id: "clip-a",
    ownerId: "owner-a",
    mimeType: "audio/mp4",
    filename: "clip-a.m4a",
    durationMs: 1000,
    byteLength: 3,
    base64: "YWJj",
  });
  await mount();
  await act(async () => {
    await expect(
      state().auth!.signInWithPassword(
        "fictional@example.invalid",
        "synthetic",
      ),
    ).rejects.toThrow();
  });
  expect(authPort.signInWithPassword).not.toHaveBeenCalled();
  expect(requestCount("/user/conversation-transfer")).toBe(0);
  expect(await vault.get("media.index")).toEqual(["clip-a"]);
  expect(state().session?.user.id).toBe("owner-a");
});

it("still permits same-owner guest signup while preserving draft and sealed media", async () => {
  runtime.session = sessionFor("owner-a", true);
  const vault = await seedVault();
  await vault.saveMedia("clip-a", {
    id: "clip-a",
    ownerId: "owner-a",
    mimeType: "audio/mp4",
    filename: "clip-a.m4a",
    durationMs: 1000,
    byteLength: 3,
    base64: "YWJj",
  });
  await mount();
  await act(async () => {
    await state().setDraft("Keep this fictional draft");
  });
  await act(async () => {
    await state().auth!.signUp("fictional@example.invalid", "synthetic");
  });
  expect(authPort.updateUser).toHaveBeenCalledTimes(1);
  expect(state().session?.user.id).toBe("owner-a");
  expect(state().session?.user.is_anonymous).toBe(false);
  expect(state().vault).toBe(vault);
  expect(state().draft).toBe("Keep this fictional draft");
  expect(await vault.get("media.index")).toEqual(["clip-a"]);
  expect(requestCount("/user/conversation-transfer")).toBe(0);
});

it("blocks guest transfer during send admission even before an outbox row exists", async () => {
  runtime.session = sessionFor("owner-a", true);
  const vault = await seedVault();
  await mount();
  await act(async () => {
    await state().setDraft("Fictional memory being admitted");
  });
  const admission = deferred<Awaited<ReturnType<typeof vault.listOutbox>>>();
  jest.spyOn(vault, "listOutbox").mockReturnValueOnce(admission.promise);
  let sending!: Promise<void>;
  await act(async () => {
    sending = state().send();
  });
  // Remove the composer independently; admission itself must still prevent transfer.
  await act(async () => {
    await state().setDraft("");
  });
  expect(await vault.listOutbox()).toEqual([]);
  await act(async () => {
    await expect(
      state().auth!.signInWithPassword(
        "fictional@example.invalid",
        "synthetic",
      ),
    ).rejects.toThrow();
  });
  expect(authPort.signInWithPassword).not.toHaveBeenCalled();
  expect(requestCount("/user/conversation-transfer")).toBe(0);
  expect(state().session?.user.id).toBe("owner-a");
  await act(async () => {
    admission.resolve([]);
    await sending;
  });
});

it("allows an existing-account transfer after all local guest work is resolved", async () => {
  runtime.session = sessionFor("owner-a", true);
  await mount();
  await act(async () => {
    await state().auth!.signInWithPassword(
      "fictional@example.invalid",
      "synthetic",
    );
  });
  expect(authPort.signInWithPassword).toHaveBeenCalledTimes(1);
  expect(requestCount("/user/conversation-transfer")).toBe(1);
  expect(state().session?.user.id).toBe("owner-b");
  await expect(state().auth!.getPendingTransfer()).resolves.toMatchObject({
    guestId: "owner-a",
    prepared: true,
    expired: false,
    destination: { id: "owner-b" },
  });
});

it("restores the saved composer before a still-pending project discovery completes", async () => {
  const vault = await seedVault();
  await vault.set("active-project", "saved-local-project");
  await vault.set("composer:saved-local-project", "Ready before discovery");
  const discovery = deferred<FetchResponse>();
  runtime.routes.set("/user/projects", () => discovery.promise);
  await mount();
  expect(requestCount("/user/projects")).toBe(1);
  expect(state().projectId).toBe("saved-local-project");
  expect(state().draft).toBe("Ready before discovery");
  await act(async () => {
    discovery.resolve(projectsResponse("owner-a"));
  });
  expect(state().projectId).toBe("saved-local-project");
  expect(state().draft).toBe("Ready before discovery");
});

it.each(["logout", "existing-account login"] as const)(
  "blocks %s when another project has an unsent local composer",
  async (operation) => {
    runtime.session = sessionFor("owner-a", true);
    const vault = await seedVault();
    await vault.set("active-project", "project-current");
    await vault.set(
      "composer:project-other",
      "Only local copy of another fictional story",
    );
    const clear = jest.spyOn(vault, "clear");
    await mount();
    expect(state().draft).toBe("");
    expect(state().projectId).toBe("project-current");
    expect(state().localProjectIds).toContain("project-other");
    await act(async () => {
      const result =
        operation === "logout"
          ? state().signOut()
          : state().auth!.signInWithPassword(
              "fictional@example.invalid",
              "synthetic",
            );
      await expect(result).rejects.toThrow();
    });
    expect(authPort.signOut).not.toHaveBeenCalled();
    expect(authPort.signInWithPassword).not.toHaveBeenCalled();
    expect(clear).not.toHaveBeenCalled();
    expect(requestCount("/user/conversation-transfer")).toBe(0);
    expect(state().session?.user.id).toBe("owner-a");
    expect(await vault.get("composer:project-other")).toBe(
      "Only local copy of another fictional story",
    );
  },
);

it("rechecks new local work after a prepared OAuth flow is cancelled", async () => {
  runtime.session = sessionFor("owner-a", true);
  const vault = await seedVault();
  await mount();
  await act(async () => {
    await expect(state().auth!.signInWithOAuth("google")).resolves.toBe(
      "cancelled",
    );
  });
  expect(requestCount("/user/conversation-transfer")).toBe(1);
  await expect(state().auth!.getPendingTransfer()).resolves.toMatchObject({
    prepared: true,
    guestId: "owner-a",
  });
  await act(async () => {
    await state().setDraft("New fictional draft after cancelled OAuth");
  });
  await act(async () => {
    await expect(
      state().auth!.signInWithPassword(
        "fictional@example.invalid",
        "synthetic",
      ),
    ).rejects.toThrow();
  });
  expect(authPort.signInWithPassword).not.toHaveBeenCalled();
  expect(requestCount("/user/conversation-transfer")).toBe(1);
  expect(state().session?.user.id).toBe("owner-a");
  expect(state().draft).toBe("New fictional draft after cancelled OAuth");
  expect(await vault.get("composer:project-owner-a")).toBe(
    "New fictional draft after cancelled OAuth",
  );
  await expect(state().auth!.getPendingTransfer()).resolves.toMatchObject({
    prepared: true,
    guestId: "owner-a",
  });
});

it("reprepares the same guest capability with a fresh snapshot before switching identity", async () => {
  runtime.session = sessionFor("owner-a", true);
  const snapshots: {
    input: TransferInput;
    owner: string | undefined;
    authorization: string | undefined;
  }[] = [];
  runtime.routes.set("/user/conversation-transfer", async (_url, init) => {
    snapshots.push({
      input: TransferInputSchema.parse(JSON.parse(init.body ?? "{}")),
      owner: runtime.session?.user.id,
      authorization: init.headers.Authorization,
    });
    return jsonResponse({ expires_in: 3600 });
  });
  runtime.routes.set("/user/profile", async () =>
    jsonResponse({ name: "Original fictional profile" }),
  );
  await mount();
  await act(async () => {
    await state().auth!.signInWithOAuth("google");
  });
  expect(snapshots).toHaveLength(1);
  runtime.routes.set("/user/profile", async () =>
    jsonResponse({ name: "Updated fictional profile" }),
  );
  await act(async () => {
    await state().newProject();
  });
  const newProject = state().projectId;
  await act(async () => {
    await state().auth!.signInWithPassword(
      "fictional@example.invalid",
      "synthetic",
    );
  });
  expect(snapshots).toHaveLength(2);
  expect(snapshots[1]!.input.token).toBe(snapshots[0]!.input.token);
  expect(snapshots[1]!.input.project_id).toBe(newProject);
  expect(snapshots[1]!.input.project_id).not.toBe(
    snapshots[0]!.input.project_id,
  );
  expect(snapshots[1]!.input.workspace_profile).toEqual({
    name: "Updated fictional profile",
  });
  expect(
    snapshots.every(
      (snapshot) =>
        snapshot.owner === "owner-a" &&
        snapshot.authorization === "Bearer synthetic-owner-a",
    ),
  ).toBe(true);
  expect(state().session?.user.id).toBe("owner-b");
  await act(async () => {
    await state().auth!.signInWithPassword(
      "fictional@example.invalid",
      "synthetic",
    );
  });
  expect(snapshots).toHaveLength(2);
});

it("does not replace a newer project selection with delayed initial discovery", async () => {
  const discovery = deferred<FetchResponse>();
  runtime.routes.set("/user/projects", () => discovery.promise);
  await mount();
  expect(state().projectId).toMatch(/^mobile-/);
  const initialProject = state().projectId;
  await act(async () => {
    await state().newProject();
  });
  const selected = state().projectId;
  expect(selected).not.toBe(initialProject);
  await act(async () => {
    discovery.resolve(projectsResponse("owner-a"));
  });
  expect(state().projectId).toBe(selected);
  expect(await state().vault!.get("active-project")).toBe(selected);
});

it("does not replace the project of an admitted turn when initial discovery resolves", async () => {
  const vault = await seedVault();
  const discovery = deferred<FetchResponse>();
  const streamed = deferred<FetchResponse>();
  runtime.routes.set("/user/projects", () => discovery.promise);
  runtime.routes.set("/agent/turn", () => streamed.promise);
  await mount();
  const admittedProject = state().projectId;
  expect(admittedProject).toMatch(/^mobile-/);
  await act(async () => {
    await state().setDraft("Fictional memory admitted before discovery");
  });
  let sending!: Promise<void>;
  await act(async () => {
    sending = state().send();
  });
  await waitFor(() => expect(requestCount("/agent/turn")).toBe(1));
  const outbox = await vault.listOutbox<TurnOutboxItem>();
  expect(outbox).toHaveLength(1);
  expect(outbox[0]!.value.projectId).toBe(admittedProject);
  expect(state().draft).toBe("");
  try {
    await act(async () => {
      discovery.resolve(projectsResponse("owner-a"));
    });
    expect(state().projectId).toBe(admittedProject);
    expect(await vault.get("active-project")).toBe(admittedProject);
  } finally {
    await act(async () => {
      streamed.resolve(
        jsonResponse({
          reply: "Synthetic saved reply",
          conversation_saved: true,
          project_id: admittedProject,
          turn_id: outbox[0]!.id,
        }),
      );
      await sending;
    });
  }
});

it("keeps expired prepared transfers blocked without regenerating their capability", async () => {
  let clock = Date.now();
  jest.spyOn(Date, "now").mockImplementation(() => clock);
  runtime.session = sessionFor("owner-a", true);
  await mount();
  await act(async () => {
    await state().auth!.signInWithOAuth("google");
  });
  expect(requestCount("/user/conversation-transfer")).toBe(1);
  clock += 3_600_000;
  await act(async () => {
    await expect(
      state().auth!.signInWithPassword(
        "fictional@example.invalid",
        "synthetic",
      ),
    ).rejects.toThrow("expired");
  });
  expect(requestCount("/user/conversation-transfer")).toBe(1);
  expect(authPort.signInWithPassword).not.toHaveBeenCalled();
  expect(state().session?.user.id).toBe("owner-a");
  await expect(state().auth!.getPendingTransfer()).resolves.toMatchObject({
    prepared: true,
    expired: true,
    guestId: "owner-a",
  });
});

it("allows logout when other projects contain only empty or whitespace composers", async () => {
  const vault = await seedVault();
  await vault.set("active-project", "project-current");
  await vault.set("composer:project-empty", "");
  await vault.set("composer:project-whitespace", " \n\t ");
  await mount();
  await act(async () => {
    await expect(state().signOut()).resolves.toBeUndefined();
  });
  expect(authPort.signOut).toHaveBeenCalledTimes(1);
  expect(state().session).toBeNull();
  await expect(vault.get("active-project")).rejects.toThrow("Vault closed");
});

it("keeps a sealed local recording when destructive logout is requested", async () => {
  const vault = await seedVault();
  await vault.saveMedia("clip-logout", {
    id: "clip-logout",
    ownerId: "owner-a",
    base64: "synthetic",
  });
  const clear = jest.spyOn(vault, "clear");
  await mount();
  await act(async () => {
    await expect(state().signOut()).rejects.toThrow();
  });
  expect(authPort.signOut).not.toHaveBeenCalled();
  expect(clear).not.toHaveBeenCalled();
  expect(await vault.get("media.index")).toEqual(["clip-logout"]);
  expect(state().session?.user.id).toBe("owner-a");
});
