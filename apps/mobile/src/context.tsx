import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { AppState, Platform } from "react-native";
import { fetch as expoFetch } from "expo/fetch";
import * as Crypto from "expo-crypto";
import * as Linking from "expo-linking";
import { getLocales } from "expo-localization";
import {
  createMemoirApi,
  type MemoirApi,
  MemoirApiError,
} from "@memoir/api-client";
import {
  type TurnState,
  type TurnOutboxItem,
  resolveDeepLink,
} from "@memoir/memoir-domain";
import { type Locale, type MessageKey, translate } from "@memoir/i18n";
import type { MemoirProject, StoryState, HistoryItem } from "@memoir/contracts";
import { createVault, type Vault } from "./platform/vault";
import {
  createAuthClient,
  type MobileAuthClient,
  type MobileSession,
} from "./auth/client";
import { TurnController } from "./turn-controller";
import { clearNativeMediaTemporaryFiles } from "./platform/native-media";
import { fixtureFetch, fixtureOwner, fixtureProject } from "./fixtures";
export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
};
const fixture =
  process.env.EXPO_PUBLIC_MEMOIR_FIXTURE === "1" &&
  (Platform.OS === "web" || __DEV__);
const baseUrl = process.env.EXPO_PUBLIC_MEMOIR_API_URL || "";
const hash = (value: string) =>
  Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, value);
interface MemoirContextValue {
  locale: Locale;
  t: (key: MessageKey) => string;
  setLocale: (locale: Locale) => Promise<void>;
  fixture: boolean;
  configured: boolean;
  loading: boolean;
  error: string | null;
  identityBusy: boolean;
  logoutNeedsRetry: boolean;
  api: MemoirApi | null;
  auth: MobileAuthClient | null;
  session: MobileSession | null;
  vault: Vault | null;
  projectId: string;
  projects: MemoirProject[];
  localProjectIds: string[];
  messages: ChatMessage[];
  draft: string;
  setDraft: (value: string) => Promise<void>;
  active: { state: TurnState; item: TurnOutboxItem } | null;
  pending: TurnOutboxItem[];
  storyState: StoryState | null;
  begin: () => Promise<void>;
  refresh: () => Promise<void>;
  selectProject: (id: string) => Promise<void>;
  newProject: () => Promise<void>;
  send: (sourceKind?: "narrator_chat" | "narrator_transcript") => Promise<void>;
  retry: (item: TurnOutboxItem) => Promise<void>;
  discard: (item: TurnOutboxItem) => Promise<void>;
  historyCursor: string | null;
  loadEarlier: () => Promise<void>;
  signOut: () => Promise<void>;
}
const Context = createContext<MemoirContextValue | null>(null);
export function MemoirProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(
    getLocales()[0]?.languageCode === "zh" ? "zh-CN" : "en-AU",
  );
  const [session, setSession] = useState<MobileSession | null>(null);
  const [auth, setAuth] = useState<MobileAuthClient | null>(null);
  const authRef = useRef<MobileAuthClient | null>(null);
  const [vault, setVault] = useState<Vault | null>(null);
  const vaultRef = useRef<Vault | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [identityBusy, setIdentityBusy] = useState(false);
  const identityBusyRef = useRef(false);
  const [logoutNeedsRetry, setLogoutNeedsRetry] = useState(false);
  const logoutVault = useRef<Vault | null>(null);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [projectId, setProjectId] = useState("");
  const projectRef = useRef("");
  const [projects, setProjects] = useState<MemoirProject[]>([]);
  const [localProjectIds, setLocalProjectIds] = useState<string[]>([]);
  const projectInteraction = useRef(0);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const messagesRef = useRef<ChatMessage[]>([]);
  const [draft, setDraftState] = useState("");
  const draftRef = useRef("");
  const sendAdmission = useRef(false);
  const [active, setActive] = useState<{
    state: TurnState;
    item: TurnOutboxItem;
  } | null>(null);
  const [pending, setPending] = useState<TurnOutboxItem[]>([]);
  const [storyState, setStoryState] = useState<StoryState | null>(null);
  const controller = useRef<TurnController | null>(null);
  const acknowledged = useRef(new Set<string>());
  const ownerEpoch = useRef(0);
  const projectEpoch = useRef(0);
  const sessionRef = useRef<MobileSession | null>(null);
  const t = (key: MessageKey) => translate(locale, key);
  function revokeOwnerView() {
    controller.current?.dispose();
    controller.current = null;
    ownerEpoch.current++;
    projectEpoch.current++;
    projectInteraction.current++;
    setActive(null);
    setMessages([]);
    messagesRef.current = [];
    setDraftState("");
    draftRef.current = "";
    sendAdmission.current = false;
    acknowledged.current.clear();
    setPending([]);
    setStoryState(null);
    setProjects([]);
    setLocalProjectIds([]);
    setHistoryCursor(null);
    setProjectId("");
    projectRef.current = "";
    setVault(null);
  }

  const bootstrapApi = useMemo(() => {
    if (!fixture && !baseUrl) return null;
    try {
      return createMemoirApi({
        baseUrl: fixture ? "https://fixture.invalid/api/v1/memoir" : baseUrl,
        fetch: fixture ? fixtureFetch : expoFetch,
        getToken: async () =>
          fixture
            ? "fixture-only-token"
            : await authRef.current?.getAccessToken(),
      });
    } catch {
      return null;
    }
  }, []);
  const api = useMemo(() => {
    if (!bootstrapApi || !session) return bootstrapApi;
    const owner = session.user.id;
    return createMemoirApi({
      baseUrl: fixture ? "https://fixture.invalid/api/v1/memoir" : baseUrl,
      fetch: fixture ? fixtureFetch : expoFetch,
      getToken: async () => {
        if (fixture) return "fixture-only-token";
        const current = await authRef.current?.getSession();
        if (current?.user.id !== owner) throw new Error("Account changed");
        const token = await authRef.current?.getAccessToken();
        if (sessionRef.current?.user.id !== owner)
          throw new Error("Account changed");
        return token;
      },
    });
  }, [bootstrapApi, session?.user.id]);
  const safeError = (failure: unknown) =>
    failure instanceof MemoirApiError
      ? `${translate(locale, failure.status === 403 ? "familyGate" : failure.status === 409 ? "revisionConflict" : "error")}${failure.requestId ? ` (${failure.requestId})` : ""}`
      : translate(locale, "error");
  useEffect(() => {
    let alive = true;
    let unsubscribe: (() => void) | undefined;
    (async () => {
      if (!bootstrapApi) {
        setLoading(false);
        return;
      }
      if (fixture) {
        const synthetic = {
          access_token: "fixture",
          refresh_token: "fixture",
          user: { id: fixtureOwner, is_anonymous: true },
        };
        sessionRef.current = synthetic;
        setSession(synthetic);
        setLoading(false);
        return;
      }
      try {
        const pinnedUrl = process.env.EXPO_PUBLIC_SUPABASE_URL;
        const pinnedKey = process.env.EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
        const config =
          pinnedUrl && pinnedKey
            ? {
                enabled: true,
                supabase_url: pinnedUrl,
                supabase_publishable_key: pinnedKey,
              }
            : await bootstrapApi.config();
        if (
          !config.enabled ||
          !config.supabase_url ||
          !config.supabase_publishable_key
        )
          throw new Error("Authentication unavailable");
        const namespace = new URL(baseUrl).host.replace(
          /[^A-Za-z0-9_.-]/g,
          "_",
        );
        const service = await createAuthClient({
          supabaseUrl: config.supabase_url,
          publishableKey: config.supabase_publishable_key,
          environment: namespace,
          onOperationStateChange: (busy) => {
            identityBusyRef.current = busy;
            setIdentityBusy(busy);
          },
          onIdentityChange: async () => {
            const previousVault = vaultRef.current;
            revokeOwnerView();
            if (previousVault) await previousVault.close();
            if (vaultRef.current === previousVault) vaultRef.current = null;
          },
          onLogout: async () => {
            // Session revocation has already disposed the controller. Cleanup
            // uses the captured resource, never a revoked operation API.
            const previousVault = logoutVault.current ?? vaultRef.current;
            if (Platform.OS !== "web") await clearNativeMediaTemporaryFiles();
            if (previousVault) await previousVault.clear();
            if (vaultRef.current === previousVault) vaultRef.current = null;
            logoutVault.current = null;
          },
          transfer: {
            prepare: async ({ token, accessToken }) => {
              const oldOwner = ownerEpoch.current;
              const pendingItems = (await controller.current?.pending()) ?? [];
              const composers = (await vaultRef.current?.listComposers()) ?? [];
              const media =
                (await vaultRef.current?.get<unknown[]>("media.index")) ?? [];
              if (
                oldOwner !== ownerEpoch.current ||
                draftRef.current.trim() ||
                sendAdmission.current ||
                pendingItems.length ||
                composers.length ||
                media.length
              )
                throw new Error("LOCAL_WORK_PENDING");
              const transferApi = createMemoirApi({
                baseUrl,
                fetch: expoFetch,
                getToken: async () => accessToken,
              });
              const workspace = await transferApi.workspaceProfile();
              const result = await transferApi.prepareTransfer({
                token,
                project_id: projectRef.current,
                messages: messagesRef.current.map(({ role, text }) => ({
                  role,
                  text,
                })),
                workspace_profile: workspace,
                ui_locale: locale,
              });
              const expires =
                typeof result.expires_at === "string"
                  ? Date.parse(result.expires_at)
                  : typeof result.expires_in === "number" &&
                      result.expires_in > 60
                    ? Date.now() + (result.expires_in - 60) * 1000
                    : NaN;
              if (!Number.isFinite(expires))
                throw new Error("Transfer expiry unavailable");
              return { expiresAt: expires };
            },
            attach: async ({ token, accessToken, guestWins }) => {
              const transferApi = createMemoirApi({
                baseUrl,
                fetch: expoFetch,
                getToken: async () => accessToken,
              });
              const result = await transferApi.attachTransfer({
                token,
                guest_wins: guestWins,
              });
              await transferApi.conversations();
              await transferApi.projects();
              return result;
            },
          },
        });
        if (!alive) return;
        authRef.current = service;
        setAuth(service);
        unsubscribe = service.subscribe((next) => {
          if (alive) {
            if (!next) revokeOwnerView();
            sessionRef.current = next;
            setSession(next);
          }
        });
        await service.getSession();
      } catch (failure) {
        if (alive) setError(safeError(failure));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
      unsubscribe?.();
      controller.current?.dispose();
    };
    // Initialization must not restart authentication when the UI locale changes.
  }, [bootstrapApi]);
  useEffect(() => {
    if (!session || !api) return;
    const epoch = ++ownerEpoch.current;
    let closed = false;
    setLoading(true);
    (async () => {
      try {
        const namespace = fixture
          ? "fixture"
          : new URL(baseUrl).host.replace(/[^A-Za-z0-9_.-]/g, "_");
        const nextVault = await createVault(session.user.id, {
          platform: fixture
            ? "fixture"
            : Platform.OS === "web"
              ? "web"
              : "native",
          namespace,
        });
        if (closed || epoch !== ownerEpoch.current) {
          await nextVault.close();
          return;
        }
        vaultRef.current = nextVault;
        setVault(nextVault);
        const savedLocale = await nextVault.get<Locale>("locale");
        if (closed || epoch !== ownerEpoch.current) return;
        if (savedLocale) setLocaleState(savedLocale);
        const ownerController = new TurnController({
          api,
          vault: nextVault,
          ownerId: session.user.id,
          hash,
          onChange: (state, item) => {
            if (
              epoch === ownerEpoch.current &&
              item.projectId === projectRef.current &&
              !acknowledged.current.has(item.operationId)
            )
              setActive({ state, item });
          },
          onSaved: (item, reply, state) => {
            if (epoch !== ownerEpoch.current) return;
            sendAdmission.current = false;
            acknowledged.current.add(item.operationId);
            if (state?.contentUnavailable) {
              if (item.projectId === projectRef.current) {
                setActive(null);
                void loadProject(item.projectId);
              }
              return;
            }
            if (item.projectId === projectRef.current) {
              setMessages((previous) => {
                const next = [
                  ...previous.filter((m) => !m.id.startsWith(item.operationId)),
                  {
                    id: item.operationId + "-user",
                    role: "user" as const,
                    text: item.command.conversation_text ?? item.command.text,
                  },
                  {
                    id: item.operationId + "-assistant",
                    role: "assistant" as const,
                    text: reply,
                  },
                ];
                messagesRef.current = next;
                return next;
              });
              setActive((current) =>
                current?.item.operationId === item.operationId ? null : current,
              );
            }
            setPending((previous) =>
              previous.filter((x) => x.operationId !== item.operationId),
            );
          },
        });
        controller.current = ownerController;
        const recovered = await ownerController.pending();
        if (closed || epoch !== ownerEpoch.current) return;
        setPending(recovered);
        const savedProject = await nextVault.get<string>("active-project");
        const localComposers = await nextVault.listComposers();
        if (closed || epoch !== ownerEpoch.current) return;
        setLocalProjectIds(localComposers.map((item) => item.projectId));
        // Local identity/project/composer recovery must not depend on the network.
        const localProject =
          savedProject ||
          recovered[0]?.projectId ||
          localComposers[0]?.projectId ||
          (fixture ? fixtureProject : "mobile-" + Crypto.randomUUID());
        const localDraft = await nextVault.get<string>(
          "composer:" + localProject,
        );
        if (closed || epoch !== ownerEpoch.current) return;
        projectRef.current = localProject;
        setProjectId(localProject);
        setDraftState(localDraft ?? "");
        draftRef.current = localDraft ?? "";
        await nextVault.set("active-project", localProject);
        if (closed || epoch !== ownerEpoch.current) return;
        setLoading(false);
        const initialInteraction = projectInteraction.current;
        try {
          const list = await api.projects();
          if (closed || epoch !== ownerEpoch.current) return;
          setProjects(list.items);
          // A first installation can choose existing account history; a local
          // project/draft always wins over discovery.
          if (
            !savedProject &&
            !recovered.length &&
            !localComposers.length &&
            projectRef.current === localProject &&
            projectInteraction.current === initialInteraction &&
            !sendAdmission.current &&
            !draftRef.current.trim() &&
            list.items[0]
          ) {
            projectRef.current = list.items[0].project_id;
            setProjectId(list.items[0].project_id);
          }
        } catch (failure) {
          if (!closed && epoch === ownerEpoch.current)
            setError(safeError(failure));
        }
        try {
          const snapshot = await api.storyState();
          if (closed || epoch !== ownerEpoch.current) return;
          setStoryState(snapshot);
        } catch (failure) {
          if (!closed && epoch === ownerEpoch.current)
            setError(safeError(failure));
        }
        for (const item of recovered) {
          if (closed || epoch !== ownerEpoch.current) return;
          try {
            await ownerController.check(item);
          } catch {
            /* Keep immutable local work while offline. */
          }
        }
        if (closed || epoch !== ownerEpoch.current) return;
        const remaining = await ownerController.pending();
        if (!closed && epoch === ownerEpoch.current) setPending(remaining);
      } catch (failure) {
        if (!closed && epoch === ownerEpoch.current)
          setError(safeError(failure));
      } finally {
        if (!closed && epoch === ownerEpoch.current) setLoading(false);
      }
    })();
    return () => {
      closed = true;
      if (epoch === ownerEpoch.current) controller.current?.dispose();
    };
  }, [session?.user.id, api]);
  function chatRows(items: HistoryItem[]): ChatMessage[] {
    return items.flatMap((item) => [
      ...(item.narrator_text
        ? [
            {
              id: item.server_turn_id + "-user",
              role: "user" as const,
              text: item.narrator_text,
            },
          ]
        : []),
      ...(item.reply
        ? [
            {
              id: item.server_turn_id + "-assistant",
              role: "assistant" as const,
              text: item.reply,
            },
          ]
        : []),
    ]);
  }
  async function loadEarlier() {
    if (!api || !historyCursor) return;
    const id = projectRef.current;
    const epoch = ownerEpoch.current;
    const page = await api.history(id, { cursor: historyCursor });
    if (id !== projectRef.current || epoch !== ownerEpoch.current) return;
    setHistoryCursor(page.next_cursor);
    setMessages((previous) => {
      const ids = new Set(previous.map((item) => item.id));
      const next = [
        ...chatRows(page.items).filter((item) => !ids.has(item.id)),
        ...previous,
      ];
      messagesRef.current = next;
      return next;
    });
  }
  async function loadProject(id: string) {
    const storage = vaultRef.current;
    if (!api || !storage) return;
    const epoch = ++projectEpoch.current;
    const owner = ownerEpoch.current;
    setActive(null);
    setMessages([]);
    setHistoryCursor(null);
    messagesRef.current = [];
    projectRef.current = id;
    setProjectId(id);
    await storage.set("active-project", id);
    if (epoch !== projectEpoch.current || owner !== ownerEpoch.current) return;
    const text = await storage.get<string>("composer:" + id);
    if (epoch !== projectEpoch.current || owner !== ownerEpoch.current) return;
    setDraftState(text ?? "");
    draftRef.current = text ?? "";
    try {
      const history = await api.history(id);
      if (epoch !== projectEpoch.current || owner !== ownerEpoch.current)
        return;
      setHistoryCursor(history.next_cursor);
      const restored = chatRows(history.items);
      setMessages(restored);
      messagesRef.current = restored;
    } catch (failure) {
      if (failure instanceof MemoirApiError && failure.status === 404) return;
      if (epoch === projectEpoch.current && owner === ownerEpoch.current)
        setError(safeError(failure));
    }
  }
  useEffect(() => {
    if (projectId && vault) void loadProject(projectId);
  }, [projectId, vault]);
  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => {
      if (state !== "active" || !authRef.current) return;
      const epoch = ownerEpoch.current;
      const sender = controller.current;
      void authRef.current
        .refreshSession()
        .then(async () => {
          if (epoch !== ownerEpoch.current) return;
          const recovered = (await sender?.pending()) ?? [];
          if (epoch !== ownerEpoch.current) return;
          for (const item of recovered) {
            await sender?.check(item);
            if (epoch !== ownerEpoch.current) return;
          }
          const remaining = (await sender?.pending()) ?? [];
          if (epoch === ownerEpoch.current) setPending(remaining);
        })
        .catch(() => {
          if (epoch === ownerEpoch.current) setError(t("signIn"));
        });
    });
    return () => subscription.remove();
  }, []);
  useEffect(() => {
    const handle = ({ url }: { url: string }) => {
      if (url.startsWith("memoir://auth/callback")) {
        void authRef.current
          ?.handleCallback(url)
          .catch(() => setError(t("signIn")));
        return;
      }
      const hosts = baseUrl ? [new URL(baseUrl).hostname] : [];
      const link = resolveDeepLink(url, {
        scheme: "memoir",
        httpsHosts: hosts,
      });
      if (link?.kind === "project" && sessionRef.current)
        void selectProject(link.projectId);
    };
    const sub = Linking.addEventListener("url", handle);
    void Linking.getInitialURL().then((url) => {
      if (url) handle({ url });
    });
    return () => sub.remove();
  }, []);
  async function setDraft(value: string) {
    if (identityBusyRef.current) return;
    projectInteraction.current++;
    setDraftState(value);
    draftRef.current = value;
    if (vaultRef.current && projectRef.current)
      try {
        const project = projectRef.current;
        const storage = vaultRef.current;
        const epoch = ownerEpoch.current;
        await storage.set("composer:" + project, value);
        if (epoch === ownerEpoch.current)
          setLocalProjectIds((previous) =>
            value.trim()
              ? [...new Set([...previous, project])]
              : previous.filter((id) => id !== project),
          );
      } catch {
        setError(t("failed"));
      }
  }
  async function setLocale(value: Locale) {
    setLocaleState(value);
    await vaultRef.current?.set("locale", value);
  }
  async function begin() {
    setError(null);
    if (!auth) {
      setError(t("notConfigured"));
      return;
    }
    try {
      await auth?.signInAnonymously();
    } catch (failure) {
      setError(safeError(failure));
    }
  }
  async function refresh() {
    if (!api || !sessionRef.current) return;
    const epoch = ownerEpoch.current;
    const selected = projectRef.current;
    const ownerController = controller.current;
    setError(null);
    try {
      const list = await api.projects();
      if (epoch !== ownerEpoch.current) return;
      setProjects(list.items);
      const snapshot = await api.storyState();
      if (epoch !== ownerEpoch.current) return;
      setStoryState(snapshot);
      if (selected === projectRef.current) await loadProject(selected);
      if (epoch !== ownerEpoch.current) return;
      const remaining = (await ownerController?.pending()) ?? [];
      if (epoch === ownerEpoch.current) setPending(remaining);
    } catch (failure) {
      if (epoch === ownerEpoch.current) setError(safeError(failure));
    }
  }
  async function selectProject(id: string) {
    projectInteraction.current++;
    if (
      identityBusyRef.current ||
      sendAdmission.current ||
      (active && !active.state.committed)
    ) {
      setError(t("awaitSave"));
      return;
    }
    try {
      await loadProject(id);
    } catch (failure) {
      setError(safeError(failure));
    }
  }
  async function newProject() {
    await selectProject("mobile-" + Crypto.randomUUID());
  }
  async function send(
    sourceKind: "narrator_chat" | "narrator_transcript" = "narrator_chat",
  ) {
    const sender = controller.current;
    const storage = vaultRef.current;
    const epoch = ownerEpoch.current;
    const project = projectRef.current;
    if (
      !sender ||
      !storage ||
      !draftRef.current.trim() ||
      !project ||
      sendAdmission.current ||
      identityBusyRef.current
    )
      return;
    sendAdmission.current = true;
    projectInteraction.current++;
    const text = draftRef.current.trim();
    setError(null);
    try {
      if ((await sender.pending()).some((item) => item.projectId === project)) {
        if (epoch === ownerEpoch.current) setError(t("awaitSave"));
        return;
      }
      if (epoch !== ownerEpoch.current) return;
      const transcript = await storage.get<{ text: string }>(
        "transcript:" + project,
      );
      const item = await sender.enqueue({
        text,
        project_id: project,
        client_turn_id: Crypto.randomUUID(),
        source_kind:
          transcript?.text === text ? "narrator_transcript" : sourceKind,
      });
      if (epoch !== ownerEpoch.current) return;
      if (draftRef.current.trim() === text) await setDraft("");
      await sender.runQueued(item);
      if (epoch === ownerEpoch.current) setPending(await sender.pending());
    } catch (failure) {
      if (epoch === ownerEpoch.current) {
        if (!draftRef.current.trim()) await setDraft(text);
        setError(safeError(failure));
      }
    } finally {
      if (epoch === ownerEpoch.current) sendAdmission.current = false;
    }
  }
  async function retry(item: TurnOutboxItem) {
    const epoch = ownerEpoch.current;
    const sender = controller.current;
    try {
      await sender?.retry(item);
      if (epoch !== ownerEpoch.current) return;
      const remaining = (await sender?.pending()) ?? [];
      if (epoch === ownerEpoch.current) setPending(remaining);
    } catch (failure) {
      if (epoch === ownerEpoch.current) setError(safeError(failure));
    }
  }
  async function discard(item: TurnOutboxItem) {
    const epoch = ownerEpoch.current;
    const sender = controller.current;
    try {
      await sender?.discard(item);
      if (epoch !== ownerEpoch.current) return;
      const remaining = (await sender?.pending()) ?? [];
      if (epoch !== ownerEpoch.current) return;
      setPending(remaining);
      setActive((current) =>
        current?.item.operationId === item.operationId ? null : current,
      );
    } catch (failure) {
      if (epoch === ownerEpoch.current) setError(safeError(failure));
    }
  }
  async function signOut() {
    if (!logoutNeedsRetry) {
      if (
        identityBusyRef.current ||
        sendAdmission.current ||
        draftRef.current.trim()
      )
        throw new Error(t("signOutWarning"));
      const remaining = (await controller.current?.pending()) ?? [];
      const composers = (await vaultRef.current?.listComposers()) ?? [];
      const media =
        (await vaultRef.current?.get<unknown[]>("media.index")) ?? [];
      if (
        sendAdmission.current ||
        draftRef.current.trim() ||
        remaining.length ||
        composers.length ||
        media.length
      )
        throw new Error(t("signOutWarning"));
      logoutVault.current = vaultRef.current;
    }
    identityBusyRef.current = true;
    setIdentityBusy(true);
    setLogoutNeedsRetry(true);
    try {
      await authRef.current?.signOut();
      revokeOwnerView();
      sessionRef.current = null;
      setSession(null);
      setLogoutNeedsRetry(false);
      setError(null);
    } catch {
      setError(t("logoutRetry"));
      throw new Error(t("logoutRetry"));
    } finally {
      identityBusyRef.current = false;
      setIdentityBusy(false);
    }
  }
  return (
    <Context.Provider
      value={{
        locale,
        t,
        setLocale,
        fixture,
        configured: !!api,
        loading,
        error,
        identityBusy,
        logoutNeedsRetry,
        api,
        auth,
        session,
        vault,
        projectId,
        projects,
        localProjectIds,
        messages,
        draft,
        setDraft,
        active,
        pending,
        storyState,
        begin,
        refresh,
        selectProject,
        newProject,
        send,
        retry,
        discard,
        historyCursor,
        loadEarlier,
        signOut,
      }}
    >
      {children}
    </Context.Provider>
  );
}
export function useMemoir() {
  const value = useContext(Context);
  if (!value) throw new Error("Missing Memoir provider");
  return value;
}
