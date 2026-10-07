import { createAuthReminder } from "./auth-reminder.js";
import { linkSocialIdentity } from "./social-auth.mjs";
import { createGuestConversationTransfer } from "./guest-conversation-transfer.mjs";
import { openAttachedConversations, retryConversationTransfer } from "./conversation-attachments.js";
import { mergePlaces, placeHistoryKey, mapTarget, matchesPlaceStage, groupPlaces, groupMapPins, groupMapFrame } from "./places.mjs";
import { MEMOIR_ROUTES } from "../routes.js";
import { currentUiLocale, translate, translateWith } from "../i18n.js";
import { openCollectionReview } from "./collection.js";
import { openProfileSettings } from "./profile.js";
import { formatDateExpression } from "./dates.mjs";
import { createConversationScroll, installConversationViewport } from "./conversation-scroll.mjs";
import englishMessages from "../../messages/en-AU.json";
import chineseMessages from "../../messages/zh-CN.json";

const openingMessages = [englishMessages, chineseMessages].map(messages => messages.Memoir.conversation.opening);

const state = {
  accountId: null,
  csrfToken: "",
  project: null,
  session: null,
  memories: [],
  sources: [],
  chapters: [],
  people: [],
  relationships: [],
  timeline: [],
  stageReadiness: {},
  privateDraft: null,
  pendingConversationTurn: null,
  preview: null,
  chat: [],
  chatHistoryCollapsed: false,
  freshAnonymousSession: false,
  codexStarting: false,
  codexReady: false,
  showThinkingSteps: false,
  profileIntakePending: true,
  placeJourney: null,
  placeJourneyChange: null,
  workspaceTab: "memoir",
  selectedMemoirChapter: null,
  selectedFamilyPerson: null,
  familyPhotoTask: null,
  workspaceUnlocked: false,
  compositionStage: 0,
  workspaceCollapsed: false,
  lifeStage: "childhood",
  selectedPlace: null,
  chapterDecision: null,
  story: null,
  familyEntitlement: null,
  recallStatus: null,
  recallPreview: null,
  familyFeaturesEnabled: false,
  familyContext: null,
  storyPlans: [],
  selectedStoryPlan: "electronic_memoir_v1",
  storyBookCount: 2,
  storyAnswers: [],
  storyChapter: null,
  storyRecording: false,
  storyRecorder: null,
  storyRecordingStream: null,
  storyRecordedChunks: [],
  storyAudioBase64: "",
  storyAudioFilename: "story-round.webm",
  storyAudioMimeType: "audio/webm",
  storyTranscript: "",
  storyAudioPlayer: null,
  checkout: null,
  loading: false,
  recording: false,
  recorder: null,
  recordingStream: null,
  recordedChunks: [],
  attachments: [],
  attachmentRights: false,
  attachmentProgress: "",
  audioUploadId: null,
  audioTranscript: "",
  audioTranscriptKind: "narrator_chat",
  audioPlayer: null,
  voiceMode: false,
  voiceModeStatus: "off",
  voiceModeRecorder: null,
  voiceModeStream: null,
  voiceModeAudioContext: null,
  voiceModeAnalyser: null,
  voiceModeMonitor: null,
  voiceModeCancelTurn: false,
  voiceModeTurnId: 0,
  voiceModePlaybackFinish: null,
  voiceModeSpeechResolve: null,
  voiceMuted: false,
  dictationStatus: "off",
  dictationId: 0,
  dictationSend: false,
  dictationMonitor: null,
  dictationAudioContext: null,
  recognition: null,
  supabase: null,
  authPromise: null,
};

const guestTransfer = createGuestConversationTransfer({
  getAuth: () => state.supabase,
  getConversation: () => ({
    project_id: state.project?.id || localStorage.getItem("memory-spark-project") || "guest-conversation",
    messages: state.chat.filter(message => ["user", "assistant"].includes(message.role) && message.text)
      .map(message => ({ role: message.role, text: message.role === "assistant" ? cleanAssistantText(message.text) : String(message.text) })),
    workspace_profile: profile(),
    ui_locale: currentUiLocale(),
  }),
  api: storyApi,
  storage: {
    getItem: key => sessionStorage.getItem(key),
    setItem: (key, value) => sessionStorage.setItem(key, value),
    removeItem: key => sessionStorage.removeItem(key),
  },
  redirectTo: window.location.origin + window.location.pathname,
  onMerged: async result => {
    const { data, error } = await state.supabase.client.auth.getUser();
    if (error) throw error;
    if (data?.user) state.supabase.user = data.user;
    await applyProfileUiLocale(result.ui_locale || result.profile?.preferred_language);
  },
});

const authReminder = createAuthReminder({
  getAuth: () => state.supabase,
  busy: () => state.loading || state.recording || state.storyRecording || state.voiceMode || state.dictationStatus !== "off",
  signInExisting: provider => guestTransfer.signIn(provider),
  cancelTransfer: () => guestTransfer.cancel(),
  onUserChanged: () => refreshProfileMenu(),
});

const MEMOIR_API_PREFIX = "/api/v1/memoir";
const PLACE_PHOTO_RESULT_LIMIT = 10;
let photoPaginationObserver = null;
const CESIUM_VERSION = "1.145";
const PLACE_MAP_VIEW_HEIGHTS = {
  country: 1_400_000,
  region: 420_000,
  city: 40_000,
  town: 28_000,
  suburb: 16_000,
  neighbourhood: 12_000,
  landmark: 6_000,
};
const FAMILY_CHART_VERSION = "0.9.0";
const VIS_TIMELINE_VERSION = "7.7.3";
const PLACE_JOURNEY_PROJECT_STORAGE_KEY = "memory-spark-place-journey-project";
const CHAT_HISTORY_STORAGE_PREFIX = "memory-spark-chat-history:";
let cesiumPlaceJourneyViewer = null;
let cesiumLoadPromise = null;
const visualizationLoadPromises = new Map();
let familyChartMountId = 0;
const familyCharts = new WeakMap();
let timelineMountId = 0;
let assistantMessageSequence = 0;
let workspaceUpdateQueue = Promise.resolve();
const appliedWorkspaceSequences = new Map();
const WORKSPACE_VISIBILITY_DEBOUNCE_MS = 180;
const workspaceVisibility = { projectId: null, stable: false, pending: null, timer: null };
const conversationScroll = createConversationScroll();

const ASSISTANT_STREAM_CHUNK_SIZE = 3;
const ASSISTANT_STREAM_DELAY_MS = 12;

const LIFE_STAGES = [
  { id: "baby", icon: "baby", scale: 0.68 },
  { id: "toddler", icon: "toddler", scale: 0.76 },
  { id: "childhood", icon: "childhood", scale: 0.84 },
  { id: "adolescence", icon: "adolescence", scale: 0.9 },
  { id: "young_adulthood", icon: "youngAdulthood", scale: 0.96 },
  { id: "midlife", icon: "midlife", scale: 1 },
  { id: "later_life", icon: "laterLife", scale: 0.94 },
];

const CHATBOT_NAME = "Mira";
const PROFILE_INTAKE_PROMPT = `This is the storyteller's first answer to the shared profile-intake opening. Extract only explicit facts
about the storyteller and the current memory thread. Save any name, birth year or date expression, birthplace,
childhood place, and story focus as who, where, when, and what. Use the profile marker contract when there is
something explicit to save. Do not infer missing details or interrogate for missing fields. Acknowledge one
specific detail, then ask exactly one low-pressure, concrete follow-up—prefer an object, sensory scene, familiar
activity, or something they hoped to talk about today.`;

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value = "") => String(value).replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;", "'":"&#039;"}[char]));
const formatText = (value = "") => escapeHtml(value).replace(/\n/g, "<br>");
function cleanAssistantText(value = "") {
  return String(value || "")
    .replace(/\[\[MEMORY_SPARK_PROFILE\]\][\s\S]*?\[\[\/MEMORY_SPARK_PROFILE\]\]/g, "")
    .replace(/<!--\s*profile\s*:[\s\S]*?(?:-->|$)/gi, "");
}

function originalConversationText(text = "") {
  const prefix = "The storyteller said: ";
  if (!text.startsWith(prefix)) return text;
  const boundaries = [
    "This is the storyteller's first answer to the shared profile-intake opening.",
    "Acknowledge the storyteller naturally, then ask one gentle open-ended follow-up question.",
    "Acknowledge the storyteller briefly, then ask one gentle follow-up question about their memory.",
  ].map(instruction => text.indexOf(`\n${instruction}`, prefix.length)).filter(index => index >= 0);
  return boundaries.length ? text.slice(prefix.length, Math.min(...boundaries)) : text;
}

function resizeChatInput(input = $("#chat-input")) {
  if (!input) return;
  input.style.height = "auto";
  const maxHeight = Number.parseFloat(window.getComputedStyle(input).maxHeight);
  const contentHeight = input.scrollHeight;
  const height = Number.isFinite(maxHeight) ? Math.min(contentHeight, maxHeight) : contentHeight;
  input.style.height = `${height}px`;
  input.style.overflowY = Number.isFinite(maxHeight) && contentHeight > maxHeight ? "auto" : "hidden";
}

function conversationLanguage() {
  // Conversation language is an explicit profile preference. An omitted
  // value lets the runtime infer it without changing the UI locale.
  return profile().preferred_language || profile().conversation_language?.locale || undefined;
}

function conversationMessage(key) {
  return translate(`Memoir.conversation.${key}`);
}

function memoirApiPath(path) {
  if (path.startsWith(MEMOIR_API_PREFIX)) return path;
  if (path === "/v1") return MEMOIR_API_PREFIX;
  if (path.startsWith("/v1/")) return `${MEMOIR_API_PREFIX}${path.slice(3)}`;
  return path;
}

const ERROR_MESSAGE_KEYS = {
  PAYMENT_REQUIRED: "paymentRequired",
  ENTITLEMENT_REQUIRED: "entitlementRequired",
  INVALID_AUDIO_PAYLOAD: "invalidAudio",
  ALREADY_PAID: "alreadyPaid",
  INVALID_STRIPE_ORDER: "invalidCheckout",
  STRIPE_ORDER_MISMATCH: "stripeMismatch",
  SESSION_EXPIRED: "sessionExpired",
};

function localizedErrorMessage(code) {
  const key = ERROR_MESSAGE_KEYS[code] || "generic";
  return translate(`Errors.${key}`);
}

function currentPath() {
  return window.location.pathname.replace(/\/$/, "") || "/";
}

function isMemoirRoute() {
  return currentPath() === MEMOIR_ROUTES.home || currentPath().startsWith("/memoir/");
}

function navigateTo(path, replace = false) {
  window.history[replace ? "replaceState" : "pushState"]({}, "", path);
  render();
}

async function api(path, options = {}) {
  const { onPhotoPage, ...requestOptions } = options;
  const method = (options.method || "GET").toUpperCase();
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (!path.startsWith("/v1/auth/") && method !== "GET" && method !== "HEAD") {
    headers["X-CSRF-Token"] = state.csrfToken || readCookie("memory_spark_csrf");
  }
  if (onPhotoPage) headers.Accept = "application/x-ndjson";
  const response = await fetch(memoirApiPath(path), { ...requestOptions, headers });
  if (response.ok && onPhotoPage && response.headers.get("Content-Type")?.includes("application/x-ndjson")) {
    return consumePhotoStream(response, onPhotoPage);
  }
  let body = null;
  try { body = await response.json(); } catch { body = { detail: response.statusText }; }
  if (!response.ok) {
    const error = new Error(localizedErrorMessage(response.headers.get("X-Error-Code") || body?.error?.code));
    error.status = response.status;
    error.code = response.headers.get("X-Error-Code") || body?.error?.code || null;
    throw error;
  }
  return body;
}

async function consumePhotoStream(response, onPage) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const lines = buffer.split("\n");
      buffer = done ? "" : lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        result = JSON.parse(line);
        await onPage(result);
      }
      if (done) break;
    }
    if (!result || result.searching) throw new Error(localizedErrorMessage());
    return result;
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

function readCookie(name) {
  const prefix = `${name}=`;
  const match = document.cookie.split("; ").find((item) => item.startsWith(prefix));
  return match ? decodeURIComponent(match.slice(prefix.length)) : "";
}

function chatHistoryStorageKey(projectId = state.project?.id) {
  return projectId ? `${CHAT_HISTORY_STORAGE_PREFIX}${projectId}` : "";
}

function persistChatHistory() {
  const key = chatHistoryStorageKey();
  if (!key) return;
  try {
    if (!state.chat.length) {
      sessionStorage.removeItem(key);
      return;
    }
    const messages = state.chat.filter((message) => message.text || message.error).map((message) => {
      const saved = {
        id: message.id,
        role: message.role,
        text: message.role === "assistant" ? cleanAssistantText(message.text) : String(message.text || ""),
        error: message.error || "",
      };
      if (Array.isArray(message.cues) && message.cues.length) saved.cues = message.cues;
      if (Array.isArray(message.trace) && message.trace.length) {
        saved.trace = message.trace;
        saved.traceMode = message.traceMode;
      }
      if (message.action && typeof message.action === "object") {
        saved.action = { name: message.action.name, label: message.action.label };
      }
      return saved;
    });
    sessionStorage.setItem(key, JSON.stringify(messages));
  } catch {
    // The conversation remains usable when session storage is unavailable or full.
  }
}

function restoreChatHistory(projectId) {
  const key = chatHistoryStorageKey(projectId);
  if (!key) return [];
  try {
    const saved = JSON.parse(sessionStorage.getItem(key) || "[]");
    if (!Array.isArray(saved)) return [];
    const messages = saved
      .filter((message) => ["user", "assistant"].includes(message?.role) && typeof message.text === "string")
      .map((message) => {
        const action = message.action && typeof message.action === "object"
          && typeof message.action.name === "string"
          && /^[a-z-]+$/.test(message.action.name)
          && typeof message.action.label === "string"
          ? { name: message.action.name, label: message.action.label }
          : undefined;
        return {
          id: typeof message.id === "string" ? message.id : undefined,
          role: message.role,
          text: message.role === "assistant" ? cleanAssistantText(message.text) : message.text,
          error: typeof message.error === "string" ? message.error : "",
          cues: Array.isArray(message.cues) ? message.cues : undefined,
          trace: Array.isArray(message.trace) ? message.trace : undefined,
          traceMode: typeof message.traceMode === "string" ? message.traceMode : undefined,
          action,
        };
      });
    const sequence = messages.reduce((highest, message) => {
      const match = message.id?.match(/^assistant-message-(\d+)$/);
      return match ? Math.max(highest, Number(match[1])) : highest;
    }, 0);
    assistantMessageSequence = Math.max(assistantMessageSequence, sequence);
    return messages;
  } catch {
    return [];
  }
}

const UI_LOCALES = new Set(["en-AU", "zh-CN"]);
const UI_LOCALE_COOKIE = "copyme2_ui_locale";
const UI_LOCALE_SOURCE_COOKIE = "copyme2_ui_locale_source";

function writeUiLocaleCookie(locale) {
  if (!UI_LOCALES.has(locale)) return;
  document.cookie = `${UI_LOCALE_COOKIE}=${encodeURIComponent(locale)}; Path=/; Max-Age=${60 * 60 * 24 * 365}; SameSite=Lax`;
}

function writeUiLocaleSource(source = "fixed") {
  if (!["fixed", "automatic", "profile"].includes(source)) return;
  document.cookie = `${UI_LOCALE_SOURCE_COOKIE}=${source}; Path=/; Max-Age=${60 * 60 * 24 * 365}; SameSite=Lax`;
}

function firstReplyLanguage(text) {
  const letters = Array.from(String(text || "")).filter((character) => /\p{L}/u.test(character));
  if (!letters.length) return undefined;
  const han = letters.filter((character) => /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/u.test(character)).length;
  if (han >= 2 && han / letters.length >= 0.35) return "zh-CN";
  const latin = letters.filter((character) => /[A-Za-z]/u.test(character)).length;
  if (latin >= 3 && latin / letters.length >= 0.6) return "en-AU";
  return undefined;
}

function hasFixedUiLocale() {
  if (["fixed", "profile"].includes(readCookie(UI_LOCALE_SOURCE_COOKIE))) return true;
  const accountLocale = state.supabase?.user?.user_metadata?.ui_locale;
  return UI_LOCALES.has(accountLocale);
}

async function applyProfileUiLocale(locale) {
  if (!UI_LOCALES.has(locale) || readCookie(UI_LOCALE_SOURCE_COOKIE) === "fixed" || currentUiLocale() === locale) return false;
  const setUiLocale = globalThis.__copyme2SetUiLocale;
  if (typeof setUiLocale !== "function") return false;
  const changed = await setUiLocale(locale, {
    persistAccount: false,
    persistCookie: true,
    source: "profile",
  });
  return changed;
}

async function applyFirstReplyLocalization(locale) {
  if (!UI_LOCALES.has(locale) || hasFixedUiLocale()) return false;
  const setUiLocale = globalThis.__copyme2SetUiLocale;
  if (typeof setUiLocale !== "function") return false;
  // This is the explicitly requested product exception: only the first
  // narrator answer may provide a bounded UI-language signal. It changes
  // the current session and never writes account metadata.
  const changed = await setUiLocale(locale, { persistAccount: false, persistCookie: true, source: "automatic" });
  if (changed) writeUiLocaleSource("automatic");
  return changed;
}

async function syncProfileUiLocale() {
  if (readCookie(UI_LOCALE_SOURCE_COOKIE) === "fixed" || UI_LOCALES.has(state.supabase?.user?.user_metadata?.ui_locale)) return false;
  let preferredLanguage = state.project?.profile?.preferred_language;
  if (!preferredLanguage && state.supabase?.accessToken) {
    try {
      preferredLanguage = (await storyApi("/v1/agent/profile")).preferred_language;
    } catch {
      // The profile endpoint is optional during boot; conversation still works.
    }
  }
  return applyProfileUiLocale(preferredLanguage);
}

function installUiLocaleBridge() {
  globalThis.__copyme2BeforeUiLocaleChange = async (nextLocale, { persistAccount = true } = {}) => {
    if (!UI_LOCALES.has(nextLocale)) return false;
    if (state.recording || state.storyRecording || state.voiceModeRecorder) {
      toast(translate("Common.finishRecordingFirst"));
      return false;
    }
    const client = state.supabase?.client;
    const user = state.supabase?.user;
    if (persistAccount && state.project && state.supabase?.accessToken) {
      const projectId = state.project.id;
      const ownerId = user?.id;
      try {
        const saved = await storyApi("/v1/agent/profile", {method:"PATCH", body:JSON.stringify({preferred_language:nextLocale})});
        if (state.project?.id !== projectId || state.supabase?.user?.id !== ownerId) return false;
        state.project = {...state.project, profile:preserveConversationLocale({...profile(), ...saved}, profile())};
      } catch {
        toast(translate("Profile.saveError"));
        return false;
      }
    }
    if (!persistAccount || !client || !user || user.is_anonymous) return true;
    try {
      const result = await client.auth.updateUser({
        data: { ...(user.user_metadata || {}), ui_locale: nextLocale },
      });
      if (result.error) throw result.error;
      if (result.data?.user) state.supabase.user = result.data.user;
    } catch (error) {
      // Keep the device choice usable even if the account metadata update is unavailable.
      console.warn("Unable to persist the UI locale to the account; keeping the device preference.", error);
    }
    return true;
  };
}

async function ensureAuth() {
  await loadSupabaseConfig();
  if (state.supabase?.auth_mode === "test") {
    syncSupabaseSession({ access_token: "browser-test-token", refresh_token: null, user: { is_anonymous: true } });
    return;
  }
  if (!state.supabase?.client) throw new Error(translate("Errors.supabaseNotConfigured"));
  const { data, error } = await state.supabase.client.auth.getSession();
  if (error) throw new Error(translate("Errors.sessionUnavailable"));
  let session = data.session;
  if (!session) {
    const signedIn = await state.supabase.client.auth.signInAnonymously();
    if (signedIn.error) {
      const message = signedIn.error.message || "";
      if (message.toLowerCase().includes("anonymous sign-ins are disabled")) {
        throw new Error(translate("Errors.anonymousDisabled"));
      }
      throw new Error(translate("Errors.authFailed"));
    }
    session = signedIn.data.session;
  }
  syncSupabaseSession(session);
}

async function loadSupabaseConfig() {
  const response = await fetch(memoirApiPath("/v1/agent/config"));
  const config = await response.json();
  state.showThinkingSteps = Boolean(config.show_thinking_steps);
  if (config.auth_mode === "test") {
    state.supabase = config;
    return;
  }
  if (!config.supabase_url || !config.supabase_publishable_key || !globalThis.supabase?.createClient) {
    state.supabase = config;
    return;
  }
  const client = globalThis.supabase.createClient(config.supabase_url, config.supabase_publishable_key, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
  });
  state.supabase = { ...config, client };
  client.auth.onAuthStateChange((_event, session) => {
    syncSupabaseSession(session);
    if (state.story && session) refreshStoryState().catch(() => {});
  });
}

function syncSupabaseSession(session) {
  state.supabaseSession = session || null;
  if (!state.supabase) return;
  const previousUser = state.supabase.user;
  state.supabase.accessToken = session?.access_token || null;
  state.supabase.refreshToken = session?.refresh_token || null;
  state.supabase.user = session?.user || null;
  authReminder.tick();
  const user = state.supabase.user;
  if (previousUser?.id !== user?.id || previousUser?.is_anonymous !== user?.is_anonymous
      || previousUser?.email !== user?.email
      || previousUser?.user_metadata?.full_name !== user?.user_metadata?.full_name
      || previousUser?.user_metadata?.name !== user?.user_metadata?.name) refreshProfileMenu();
  const accountLocale = session?.user?.user_metadata?.ui_locale;
  if (UI_LOCALES.has(accountLocale) && !readCookie(UI_LOCALE_COOKIE)) {
    writeUiLocaleCookie(accountLocale);
    writeUiLocaleSource("fixed");
    if (globalThis.__copyme2Intl?.locale && globalThis.__copyme2Intl.locale !== accountLocale) {
      window.location.reload();
    }
  }
}

async function supabaseAuth(action) {
  if (!state.supabase?.supabase_url || !state.supabase?.supabase_publishable_key) return toast(translate("Errors.supabaseNotConfigured"));
  const email = $("#agent-email")?.value.trim();
  const password = $("#agent-password")?.value || "";
  if (!email || password.length < 8) return toast(translate("Errors.authInput"));
  if (state.supabase.client) {
    const result = action === "signup"
      ? await state.supabase.client.auth.signUp({ email, password })
      : await state.supabase.client.auth.signInWithPassword({ email, password });
    if (result.error) return toast(translate("Errors.authFailed"));
    if (!result.data.session) return toast(translate("Errors.authConfirm"));
    syncSupabaseSession(result.data.session);
    renderLanding();
    toast(translate("Errors.memoryConnected"));
    return;
  }
  const path = action === "signup" ? "/auth/v1/signup" : "/auth/v1/token?grant_type=password";
  const response = await fetch(`${state.supabase.supabase_url}${path}`, { method: "POST", headers: { "Content-Type": "application/json", apikey: state.supabase.supabase_publishable_key }, body: JSON.stringify({ email, password }) });
  const body = await response.json();
  if (!response.ok) return toast(translate("Errors.authFailed"));
  if (!body.access_token) return toast(translate("Errors.authConfirm"));
  state.supabase = { ...state.supabase, accessToken: body.access_token, refreshToken: body.refresh_token, user: body.user };
  try { sessionStorage.setItem("memory-spark-supabase-session", JSON.stringify({ accessToken: body.access_token, refreshToken: body.refresh_token, user: body.user })); } catch { /* session remains in memory */ }
  renderLanding();
  toast(translate("Errors.memoryConnected"));
}

async function storySession() {
  if (state.supabase?.auth_mode === "test") return { access_token: "browser-test-token" };
  if (!state.supabase?.client) throw new Error(translate("Errors.supabaseNotConfigured"));
  const { data, error } = await state.supabase.client.auth.getSession();
  if (error || !data.session) throw new Error(translate("Errors.sessionUnavailable"));
  syncSupabaseSession(data.session);
  return data.session;
}

async function storyApi(path, options = {}) {
  const session = await storySession();
  const headers = {
    "Content-Type": "application/json",
    Authorization: `Bearer ${session.access_token}`,
    ...(options.headers || {}),
  };
  const response = await fetch(memoirApiPath(path), { ...options, headers });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(localizedErrorMessage(response.headers.get("X-Error-Code") || body?.error?.code));
    error.status = response.status;
    error.code = response.headers.get("X-Error-Code") || body?.error?.code;
    throw error;
  }
  return body;
}

async function supabaseApi(path, options = {}) {
  if (!state.supabase?.accessToken) return null;
  const headers = {
    "Content-Type": "application/json",
    "X-CSRF-Token": state.csrfToken || readCookie("memory_spark_csrf"),
    Authorization: `Bearer ${state.supabase.accessToken}`,
    ...(options.headers || {}),
  };
  const response = await fetch(memoirApiPath(path), { ...options, headers });
  const body = await response.json().catch(() => ({}));
  if (response.status === 401) {
    state.supabase.accessToken = null;
    try { sessionStorage.removeItem("memory-spark-supabase-session"); } catch { /* private browsing */ }
    throw new Error(translate("Errors.sessionExpired"));
  }
  if (!response.ok) throw new Error(localizedErrorMessage(response?.headers?.get("X-Error-Code") || body?.error?.code));
  return body;
}

function simulatedLoopTrace(toolNames = ["memory.search"], finalDetail = translate("Memoir.trace.final")) {
  const tools = toolNames.flatMap((name) => [
    { kind: "tool_call", label: name, detail: translateWith("Memoir.trace.toolCall", { tool: name }) },
    { kind: "tool_result", label: `${name} result`, detail: translate("Memoir.trace.toolResult") },
  ]);
  return [
    { kind: "analysis", label: translate("Memoir.trace.analysis"), detail: translate("Memoir.trace.analysis") },
    ...tools,
    { kind: "final", label: translate("Memoir.trace.final"), detail: finalDetail },
  ];
}

async function agentTurn(text, fallback = "", toolNames = ["memory.search"], language = conversationLanguage(), firstReplyLocalization = false, conversationText = undefined, serverAction = null, sourceKind = "narrator_chat") {
  const simulated = simulatedLoopTrace(toolNames);
  if (!state.supabase?.accessToken) return { reply: fallback || null, trace: simulated, traceMode: "simulated" };
  let streamedMessage = null;
  const liveTrace = [];
  const streamProjectId = state.project?.id || null;
  const ownerId = state.supabase?.user?.id;
  const previousTurn = state.pendingConversationTurn;
  const requestTurn = previousTurn?.projectId === streamProjectId && previousTurn?.ownerId === ownerId
      && previousTurn?.text === text ? previousTurn : {projectId:streamProjectId,ownerId,text,
      id:globalThis.crypto?.randomUUID?.() || null};
  state.pendingConversationTurn = requestTurn;
  const previousJourney = state.placeJourney;
  const previousSelection = state.selectedPlace;
  let previewJourney = null;
  const recordProgress = (step) => {
    if (state.project?.id !== streamProjectId || !step?.id) return;
    const index = liveTrace.findIndex(item => item.id === step.id);
    if (index < 0) liveTrace.push(step);
    else if (step.status === "completed" || step.status === "failed") {
      liveTrace.splice(index, 1);
      liveTrace.push(step);
    } else liveTrace[index] = step;
    if (!streamedMessage) {
      streamedMessage = { id: nextAssistantMessageId(), role: "assistant", text: "", streaming: true };
      state.chat.push(streamedMessage);
    }
    streamedMessage.trace = liveTrace;
    streamedMessage.traceMode = "live";
    updateStreamingAssistantMessage(streamedMessage);
  };
  if (state.supabase.google_maps_browser_api_key) void loadCesium().catch(() => {});
  try {
    const applyWorkspace = async (update) => {
      if (!update || typeof update !== "object") return;
      if (update.project_id && update.project_id !== streamProjectId) return;
      if (!streamProjectId || state.project?.id !== streamProjectId) return;
      const sourceSequence = Number(update.source_sequence || 0);
      const markCurrent = (component) => {
        // Server sequences are nanosecond timestamps, larger than MAX_SAFE_INTEGER.
        // Distinct turns remain ordered even after JSON's sub-microsecond rounding.
        if (!Number.isInteger(sourceSequence) || sourceSequence <= 0) return true;
        const key = `${streamProjectId}:${component}`;
        const previous = appliedWorkspaceSequences.get(key) || 0;
        if (sourceSequence < previous) return false;
        appliedWorkspaceSequences.set(key, sourceSequence);
        return true;
      };
      if (update.preview === true) {
        if (!update.place_journey || !markCurrent("place")) return;
        previewJourney = { ...update.place_journey, preview: true };
        state.placeJourney = previewJourney;
        state.selectedPlace = placeHistoryKey(previewJourney);
        state.lifeStage = "all";
        state.workspaceCollapsed = false;
        resolvePlaceMap(previewJourney);
        render();
        return;
      }
      if (update.profile_updates && markCurrent("profile")) {
        await saveProfileUpdates(update.profile_updates, streamProjectId);
        if (update.profile_updates.story_focus?.when && state.placeJourney) {
          // Profile and place are separate stream events. Restart discovery
          // for the new period even if the earlier search is still pending.
            void loadPlacePictures(state.placeJourney, streamProjectId, {onProgress: recordProgress});
        }
      }
      if (Object.prototype.hasOwnProperty.call(update, "place_journey")) {
        if (!markCurrent("place")) return;
        state.placeJourneyChange = update.place_journey_change || null;
        // The API returns the latest saved journey even when this turn emitted
        // no marker. A persisted user-level record must not activate a fresh
        // conversation's workspace on its own.
        if (update.place_journey && (update.place_journey_change?.changed || update.place_journey_change?.mentioned)) {
          state.placeJourney = update.place_journey;
          // A newly detected place is an explicit workspace trigger. Reopen the
          // workspace if the storyteller had collapsed it earlier in the turn.
          state.workspaceCollapsed = false;
          const stage = update.profile_updates?.story_focus?.life_stage;
          const lifeStage = LIFE_STAGES.some(item => item.id === stage) ? stage : null;
          const candidates = (update.place_journeys?.length ? update.place_journeys : [update.place_journey])
            .map(journey => ({ period: "", ...journey, life_stage: lifeStage }));
          const places = mergePlaces([...(profile().memory_places || []), ...candidates]);
          const entries = candidates.map(candidate => places.find(item => placeHistoryKey(item) === placeHistoryKey(candidate)));
          const entry = entries.at(-1);
          await saveProfileUpdates({ memory_places: places }, streamProjectId);
          state.lifeStage = "all";
          state.selectedPlace = placeHistoryKey(entry);
          rememberPlaceJourneyProject(streamProjectId);
          // Discovery can take much longer than the saved place update.
          // Render the map and loading panel while it runs independently.
          for (const place of entries) {
            resolvePlaceMap(place);
            void loadPlacePictures(place, streamProjectId, {onProgress: recordProgress});
          }
        }
        // Places and pictures are presented together in the workspace overview,
        // rather than as separate navigation destinations.
      }
      const composition = update.composer_delivery || update.memoir_composition || null;
      const rawCompositionStage = update.composition_stage ?? update.memoir_stage ?? composition?.stage;
      const nextCompositionStage = Number(rawCompositionStage);
      if (Number.isFinite(nextCompositionStage) && markCurrent("composition")) {
        state.compositionStage = nextCompositionStage;
        const deliveredChapters = Array.isArray(composition?.chapters)
          ? composition.chapters
          : Array.isArray(update.chapters) ? update.chapters : null;
        if (deliveredChapters) state.chapters = deliveredChapters;
        if (composition?.story_chapter) state.storyChapter = composition.story_chapter;
        state.project = { ...state.project, composition_stage: nextCompositionStage };
        if (nextCompositionStage >= 3) {
          state.workspaceUnlocked = true;
          state.project.workspace_unlocked = true;
          state.workspaceCollapsed = false;
          state.workspaceTab = "memoir";
        }
      }
      if (state.familyFeaturesEnabled && update.family_features_enabled === true && update.family_context_update?.persisted === true && update.family_context && markCurrent("family")) {
        applyPersistedFamilyContext(update.family_context);
        if (!composingWorkspaceActive()) state.workspaceTab = "family";
      }
      if (update.task_errors?.length) toast(translate("Collection.taskFailed"));
      else if (update.tasks?.length) toast(translate("Collection.taskQueued"));
      if (update.stage_readiness) state.stageReadiness = update.stage_readiness;
      render();
    };
    const body = await streamAgentTurn(text, async (delta) => {
      if (!streamedMessage) {
        streamedMessage = { id: nextAssistantMessageId(), role: "assistant", text: "", streaming: true };
        state.chat.push(streamedMessage);
        render();
      }
      streamedMessage.text += delta;
      updateStreamingAssistantMessage(streamedMessage);
    }, async (event) => {
      if (event.type === "progress") {
        recordProgress(event.data);
      } else if (event.type === "conversation_saved") {
        if (state.project?.id === streamProjectId && state.supabase?.user?.id === ownerId) {
          await applyCommittedConversationLocale(event.data?.profile_updates);
        }
      } else if (event.type === "workspace_error") {
        for (const step of liveTrace) if (step.status === "running") step.status = "failed";
        if (streamedMessage) updateStreamingAssistantMessage(streamedMessage);
      } else if (event.type === "place_preview") {
        await applyWorkspace({ ...event.data, preview: true });
      } else if (event.type === "workspace_update") {
        // Workspace writes are serialized globally so late turns cannot race
        // on the same project revision. This queue is independent of the
        // conversation-ready promise, so the storyteller can send again.
        workspaceUpdateQueue = workspaceUpdateQueue
          .then(() => applyWorkspace(event.data))
          .catch((error) => toast(error.message));
      }
    }, language, firstReplyLocalization, conversationText, requestTurn.id, serverAction, sourceKind);
    // A saved reply is ready even when an earlier workspace write is pending.
    // Legacy responses still need their bundled workspace applied here.
    if (!body.conversation_saved) {
      workspaceUpdateQueue = workspaceUpdateQueue.then(() => applyWorkspace(body));
      await workspaceUpdateQueue;
    }
    if (body.profile_updates?.conversation_language && state.project?.id === streamProjectId && state.supabase?.user?.id === ownerId) {
      await applyCommittedConversationLocale(body.profile_updates);
    }
    if (body.recall_status) state.recallStatus = body.recall_status;
    if (body.reply && state.pendingConversationTurn === requestTurn) state.pendingConversationTurn = null;
    if (body.conversation_saved) void refreshPrivateDraft();
    if (state.recallStatus?.payment_required) void ensureRecallPreview();
    if (state.recallStatus?.payment_required && state.voiceMode) stopVoiceMode({ silent: true });
    if (!streamedMessage && body.reply) {
      // Compatibility responses may contain the entire reply in one event.
      // They are already complete; do not replay them as simulated typing.
      streamedMessage = { id: nextAssistantMessageId(), role: "assistant", text: body.reply, streaming: false };
      state.chat.push(streamedMessage);
      render();
    }
    return { blocked: body.recall_status?.payment_required && !body.reply, streamedMessage, reply: body.reply || fallback || null, trace: liveTrace.length ? liveTrace : (body.trace || []), traceMode: liveTrace.length ? "live" : (body.trace_mode || "codex"), placeJourney: body.place_journey || null, placeJourneyChange: body.place_journey_change || null, familyContextUpdate: body.family_context_update || null };
  } catch (error) {
    if (state.project?.id === streamProjectId && state.placeJourney === previewJourney && previewJourney) {
      state.placeJourney = previousJourney;
      state.selectedPlace = previousSelection;
      render();
    }
    toast(error.message);
    if (streamedMessage) {
      streamedMessage.failed = true;
      streamedMessage.error = error.message;
    }
    return { streamedMessage, reply: streamedMessage?.text || error.message, trace: liveTrace.map(step => ({ ...step, status: step.status === "running" ? "failed" : step.status })), traceMode: "error" };
  }
}

async function streamAgentTurn(text, onDelta, onEvent = async () => {}, language = conversationLanguage(), firstReplyLocalization = false, conversationText = undefined, clientTurnId = undefined, serverAction = null, sourceKind = "narrator_chat") {
  const isGreeting = serverAction === "begin" || serverAction === "continue";
  const body = isGreeting
    ? { action: serverAction, client_turn_id: clientTurnId || undefined, project_id: state.project?.id || null, language, first_reply_localization: firstReplyLocalization }
    : { text, conversation_text: conversationText, source_kind: sourceKind, client_turn_id: clientTurnId || undefined, project_id: state.project?.id || null, language, first_reply_localization: firstReplyLocalization };
  const response = await fetch(memoirApiPath(isGreeting ? "/v1/agent/greeting" : "/v1/agent/turn"), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/x-ndjson",
      Authorization: `Bearer ${state.supabase.accessToken}`,
      "X-CSRF-Token": state.csrfToken || readCookie("memory_spark_csrf") },
    body: JSON.stringify(body),
  });
  if (response.status === 401) {
    state.supabase.accessToken = null;
    throw new Error(translate("Errors.sessionExpired"));
  }
  if (!response.ok) throw new Error(localizedErrorMessage(response.headers.get("X-Error-Code")));
  if (!response.body) return response.json();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;
  let ready = false;
  let resolveReady;
  let rejectReady;
  const readyPromise = new Promise((resolve, reject) => {
    resolveReady = resolve;
    rejectReady = reject;
  });

  function jsonObjectEnd(value) {
    const start = value.search(/\S/);
    if (start < 0) return null;
    if (value[start] !== "{" && value[start] !== "[") throw new Error("Invalid streaming response");
    const opening = value[start];
    const closing = opening === "{" ? "}" : "]";
    let depth = 0;
    let quoted = false;
    let escaped = false;
    for (let index = start; index < value.length; index += 1) {
      const character = value[index];
      if (quoted) {
        if (escaped) escaped = false;
        else if (character === "\\") escaped = true;
        else if (character === '"') quoted = false;
        continue;
      }
      if (character === '"') {
        quoted = true;
        continue;
      }
      if (character === opening) depth += 1;
      if (character === closing) {
        depth -= 1;
        if (depth === 0) return index + 1;
      }
    }
    return null;
  }

  async function consumeBuffer(final = false) {
    while (buffer.trim()) {
      const end = jsonObjectEnd(buffer);
      if (end === null) {
        if (final) throw new Error("Incomplete streaming response");
        return;
      }
      const value = buffer.slice(0, end);
      buffer = buffer.slice(end);
      const event = JSON.parse(value);
      if (event.type === "text_delta") await onDelta(event.text || "");
      else if (event.type === "reply_complete") result = { ...(result || {}), ...(event.data || {}) };
      else if (event.type === "conversation_saved") {
        result = { ...(result || {}), ...(event.data || {}) };
        if (!ready) {
          ready = true;
          resolveReady(result);
        }
      } else if (["place_preview", "workspace_update", "progress", "workspace_error"].includes(event.type)) {
        await onEvent(event);
      } else if (event.type === "result") {
        result = { ...(result || {}), ...(event.data || {}) };
        if (ready) {
          // The fast path already delivered each workspace component as its
          // own event. Keep the terminal envelope for compatibility, but do
          // not replay place/profile/family writes when it arrives.
          const {
            place_journey: _placeJourney,
            place_journey_change: _placeJourneyChange,
            place_journeys: _placeJourneys,
            profile_updates: _profileUpdates,
            family_context: _familyContext,
            family_context_update: _familyContextUpdate,
            family_features_enabled: _familyFeaturesEnabled,
            ...workspaceTail
          } = event.data || {};
          await onEvent({ type: "workspace_update", data: workspaceTail });
        }
        else {
          ready = true;
          resolveReady(result);
        }
      } else if (event.type === "error") {
        if (ready) await onEvent({ type: "workspace_error", message: event.message });
        else {
          ready = true;
          rejectReady(new Error(event.message));
        }
      } else if (event && typeof event === "object" && !event.type) {
        result = event;
        if (!ready) {
          ready = true;
          resolveReady(result);
        } else {
          await onEvent({ type: "workspace_update", data: event });
        }
      }
    }
  };
  const consumeStream = async () => {
    try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      await consumeBuffer(done);
      if (done) break;
    }
      if (!ready) {
        if (!result) throw new Error(localizedErrorMessage());
        ready = true;
        resolveReady(result);
      }
    } catch (error) {
      if (!ready) {
        ready = true;
        rejectReady(error);
      } else {
        await onEvent({ type: "workspace_error", message: error.message });
      }
    } finally {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  };
  void consumeStream();
  return readyPromise;
}

async function loadPlacePictures(entry, projectId, { more = false, force = false, onProgress = null } = {}) {
  if (!projectId || !entry?.place) return;
  const key = placeHistoryKey(entry);
  entry = (profile().memory_places || []).find(item => placeHistoryKey(item) === key) || entry;
  const period = photoSearchPeriod(entry, profile().story_focus);
  const parents = (entry.hierarchy || []).filter(label => label && label !== entry.place && label !== "Earth");
  const parent = ["suburb", "landmark"].includes(entry.granularity) ? parents.at(-1) : "";
  const searchPlace = parent && !entry.place.includes(parent) ? `${entry.place}, ${parent}` : entry.place;
  const center = placePhotoCenter(entry);
  const samePlace = (entry.photo_search_place || entry.place) === searchPlace;
  const sameCenter = !center || (entry.photo_search_latitude === center.latitude && entry.photo_search_longitude === center.longitude);
  const sameSearch = entry.photo_search_period === period && samePlace && sameCenter
    && entry.photo_search_policy === "place-radius20-period-v6";
  if (more && (!sameSearch || !entry.photo_next_cursor)) return;
  if (!more && !force && sameSearch && ((entry.pictures || []).length
      || entry.photo_search_complete || (Object.hasOwn(entry, "photo_next_cursor")
        && entry.photo_search_policy === "place-radius20-period-v6" && entry.photo_search_at > 0))) return;
  state.photoRequests ||= new Map();
  const requestKey = photoRequestKey(entry, projectId);
  if (state.photoRequests.get(requestKey)?.loading) return;
  state.photoRequests.set(requestKey, { loading: true });
  let photoStatus = "SEARCHING";
  const reportProgress = (status, label) => {
    if (onProgress) onProgress({id: `photos:${requestKey}`, kind: "skill", skill: "place-photo-research",
      label: "place-photo-research", status,
      detail: `${translate(`Memoir.workspace.${label}`)} · ${entry.place}${period ? ` · ${period}` : ""}`});
  };
  reportProgress("running", "picturesSearching");
  render();
  const control = document.querySelector("[data-photo-more]");
  if (control) { control.disabled = true; control.setAttribute("aria-busy", "true"); }
  try {
    const query = new URLSearchParams({ place: searchPlace, period });
    if (center) {
      query.set("latitude", center.latitude);
      query.set("longitude", center.longitude);
    }
    if (force) query.set("refresh", "true");
    if (more) query.set("cursor", entry.photo_next_cursor);
    let deliveredFinal = false;
    const acceptPage = async (result) => {
      if (state.project?.id !== projectId) return;
      photoStatus = result.status || "PARTIAL";
      if (!Array.isArray(result.items) || result.status === "UNAVAILABLE") {
        state.photoRequests.set(requestKey, { error: true, failures: result.failures || [] });
        return;
      }
      if (result.searching && !result.items.length) return;
      // Discovery overlaps workspace events. Serialize persistence against the
      // latest places, but paint each verified batch before saving it.
      const persist = workspaceUpdateQueue.then(async () => {
        if (state.project?.id !== projectId) return;
        const places = [...(profile().memory_places || [])];
        const index = places.findIndex(item => placeHistoryKey(item) === key);
        const latest = index >= 0 ? places[index] : entry;
        if (photoSearchPeriod(latest, profile().story_focus) !== period) return;
        if (photoRequestKey(latest, projectId) !== requestKey) return;
        const latestCenter = placePhotoCenter(latest);
        if (center && latestCenter && (center.latitude !== latestCenter.latitude || center.longitude !== latestCenter.longitude)) return;
        const resultCenter = result.search_center || center;
        const scope = {...latest, ...(resultCenter ? {photo_search_latitude: resultCenter.latitude,
          photo_search_longitude: resultCenter.longitude} : {})};
        const pictures = mergePlacePictures(latest.photo_search_period === period
          && (latest.photo_search_place || latest.place) === searchPlace
          && latest.photo_search_policy === "place-radius20-period-v6" ? latest.pictures || [] : [], result.items)
          .filter(picture => photoMatchesScope(picture, scope, profile().story_focus));
        const updatedEntry = { ...latest, pictures, photo_search_period: period,
          ...(resultCenter ? {photo_search_latitude: resultCenter.latitude, photo_search_longitude: resultCenter.longitude} : {}),
          photo_search_place: searchPlace,
          photo_next_cursor: result.next_cursor || null,
          photo_search_at: result.searching ? 0 : Date.now(),
          photo_search_status: result.status || ((result.items || []).length ? "PARTIAL" : "NO_MATCH"),
          photo_search_complete: !result.searching,
          photo_search_policy: "place-radius20-period-v6" };
        if (index >= 0) places[index] = updatedEntry;
        else places.push(updatedEntry);
        profile().memory_places = places;
        if (state.placeJourney && placeHistoryKey(state.placeJourney) === key) state.placeJourney = updatedEntry;
        render();
        await saveProfileUpdates({ memory_places: places }, projectId, { force: true });
      });
      workspaceUpdateQueue = persist.catch(() => {});
      await persist;
    };
    const options = { onPhotoPage: async result => {
      await acceptPage(result);
      if (!result.searching) deliveredFinal = true;
    } };
    let result;
    try {
      result = await api(`/v1/projects/${projectId}/place-photos?${query}`, options);
    } catch (error) {
      if (!more || error.status !== 410) throw error;
      query.delete("cursor");
      result = await api(`/v1/projects/${projectId}/place-photos?${query}`, options);
    }
    // JSON-only servers and cached responses retain the existing contract.
    if (!deliveredFinal) await acceptPage(result);
  } catch { /* Pictures are optional; retry explicitly without erasing them. */
    state.photoRequests.set(requestKey, { error: true });
  } finally {
    state.photoRequests.set(requestKey, {...state.photoRequests.get(requestKey), loading: false});
    const failed = state.photoRequests.get(requestKey)?.error;
    reportProgress(failed ? "failed" : "completed",
      failed ? "picturesUnavailable" : photoStatus === "NO_MATCH" ? "picturesNoMatch" : "pictures");
    if (state.project?.id === projectId) render();
  }
}

function mergePlacePictures(existing, incoming) {
  const seen = new Set();
  const unique = [];
  for (const picture of [...existing, ...incoming]) {
    const keys = [picture.asset_id && `asset:${picture.asset_id}`, picture.content_hash && `hash:${picture.content_hash}`];
    for (const value of [picture.original_url, picture.image_url]) {
      if (!value) continue;
      try {
        const url = new URL(value, window.location.origin);
        url.hash = "";
        let filename = "";
        const decodedPath = decodeURIComponent(url.pathname);
        if (url.hostname === "upload.wikimedia.org") {
          let path = decodedPath.replace("/thumb/", "/");
          if (decodedPath.includes("/thumb/")) path = path.slice(0, path.lastIndexOf("/"));
          filename = path.split("/").at(-1).replace(/^\d{14}!/, "");
        } else if (url.hostname === "commons.wikimedia.org" || url.hostname.endsWith(".wikipedia.org")) {
          const match = decodedPath.match(/\/(?:Special:(?:FilePath|Redirect\/file)\/|(?:File|文件|檔案):)(.+)$/i);
          filename = (match?.[1] || url.searchParams.get("title") || "").replace(/^(?:File|文件|檔案):/i, "");
        }
        if (/\.(?:jpe?g|png|webp|gif|tiff?)$/i.test(filename)) keys.push(`wikimedia:${filename.replaceAll("_", " ").trim()}`);
        if (url.hostname === "upload.wikimedia.org" && url.pathname.includes("/thumb/")) {
          url.pathname = url.pathname.replace("/thumb/", "/").split("/").slice(0, -1).join("/");
        }
        if (/^(live|farm\d+)\.staticflickr\.com$/.test(url.hostname)) {
          url.hostname = "staticflickr.com";
          url.pathname = url.pathname.replace(/_[sqtmnzcbhokw](\.[a-z]+)$/i, "$1");
        }
        for (const key of [...url.searchParams.keys()]) {
          if (key.startsWith("utm_") || ["width", "height", "w", "h", "fbclid", "gclid"].includes(key)) url.searchParams.delete(key);
        }
        url.searchParams.sort();
        keys.push(`image:${url.href}`);
      } catch { /* Invalid URLs cannot create image identities. */ }
    }
    try {
      const source = new URL(picture.source_url);
      const id = source.pathname.match(/^\/photos\/[^/]+\/(\d+)\/?$/)?.[1];
      if (["www.flickr.com", "flickr.com"].includes(source.hostname) && id) keys.push(`flickr:${id}`);
    } catch { /* Source links are optional. */ }
    const valid = keys.filter(Boolean);
    const similar = /^[0-9a-f]{16}$/.test(picture.perceptual_hash || "") && unique.some(other => {
      if (!/^[0-9a-f]{16}$/.test(other.perceptual_hash || "")) return false;
      let difference = BigInt(`0x${picture.perceptual_hash}`) ^ BigInt(`0x${other.perceptual_hash}`);
      let bits = 0;
      while (difference) { difference &= difference - 1n; bits++; }
      return bits <= 6;
    });
    const duplicate = valid.some(key => seen.has(key)) || similar;
    valid.forEach(key => seen.add(key));
    if (!duplicate) unique.push(picture);
  }
  return unique;
}

function placePhotoCenter(entry) {
  const target = entry?.place && typeof placeMapTarget === "function" ? placeMapTarget(entry) : null;
  const candidates = [entry, target?.place === entry?.place ? target : null,
    {latitude: entry?.photo_search_latitude, longitude: entry?.photo_search_longitude}];
  for (const candidate of candidates) {
    if (!candidate || candidate.latitude == null || candidate.longitude == null
        || String(candidate.latitude).trim() === "" || String(candidate.longitude).trim() === ""
        || typeof candidate.latitude === "boolean" || typeof candidate.longitude === "boolean") continue;
    const latitude = Number(candidate.latitude), longitude = Number(candidate.longitude);
    if (Number.isFinite(latitude) && Number.isFinite(longitude) && Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180) {
      return {latitude, longitude};
    }
  }
  return null;
}

function photoRequestKey(entry, projectId = state.project?.id) {
  const center = placePhotoCenter({...entry, photo_search_latitude: undefined, photo_search_longitude: undefined});
  return JSON.stringify([projectId, placeHistoryKey(entry), photoSearchPeriod(entry, profile().story_focus),
    center?.latitude ?? null, center?.longitude ?? null]);
}

function photoMatchesScope(picture, entry, focus = null) {
  const period = photoSearchPeriod(entry, focus);
  const expression = picture.date_expression || "";
  const years = Array.from(expression.matchAll(/(?<!\d)((?:18|19|20)\d{2})(?!\d)/g), match => Number(match[1]));
  if (!years.length || /circa|\bca\.?\s|before|after|unknown|约|不详|以前|以后/i.test(expression)
      || /upload|publication|published|modified|visual_guess/i.test(picture.date_basis || "")) return false;
  const today = new Date().toLocaleDateString("en-CA", {timeZone: "Australia/Sydney"});
  const isoDate = expression.match(/^(\d{4}-\d{2}-\d{2})(?:[T ].*)?$/)?.[1];
  if (Math.max(...years) > Number(today.slice(0, 4)) || (isoDate && (isoDate > today
      || !Number.isFinite(Date.parse(isoDate)) || new Date(isoDate).toISOString().slice(0, 10) !== isoDate))) return false;
  const bounds = (value, expandBareYear = false) => {
    const years = Array.from(value.matchAll(/(?<!\d)((?:18|19|20)\d{2})(?!\d)/g), match => Number(match[1]));
    if (!years.length) return null;
    return /(?:18|19|20)\d0\s*(?:s|年代)/i.test(value)
      || (expandBareYear && /^\s*(?:18|19|20)\d{2}\s*$/.test(value))
      ? [years[0], years[0] + 9] : [Math.min(...years), Math.max(...years)];
  };
  const requested = bounds(period, true), captured = bounds(expression);
  if (requested) {
    const yearOnly = /^\s*(?:(?:about|around|circa|approximately|ca\.?|c\.)\s+|(?:大约|约|大概)\s*)?(?:18|19|20)\d{2}\s*年?\s*(?:左右|前后|前後)?\s*$/i.test(period);
    const tolerance = requested[0] === requested[1] && yearOnly ? 10 : 0;
    if (captured[0] < requested[0] - tolerance || captured[1] > requested[1] + tolerance) return false;
  } else {
    const recent = new Date(`${today}T00:00:00Z`);
    const day = recent.getUTCDate();
    recent.setUTCDate(1);
    recent.setUTCFullYear(recent.getUTCFullYear() - 2);
    recent.setUTCDate(Math.min(day, new Date(Date.UTC(recent.getUTCFullYear(), recent.getUTCMonth() + 1, 0)).getUTCDate()));
    const exact = expression.match(/^(\d{4}-\d{2}-\d{2})(?:[T ].*)?$/)?.[1];
    const parsed = /^[A-Za-z]+ \d{1,2},? \d{4}$/.test(expression) ? new Date(expression) : null;
    const date = exact || (parsed && Number.isFinite(parsed.getTime()) ? parsed.toISOString().slice(0, 10) : null);
    const start = date || `${captured[0]}-01-01`, end = date || `${captured[1]}-12-31`;
    if (start < recent.toISOString().slice(0, 10) || end > today) return false;
  }
  const center = placePhotoCenter(entry);
  const point = placePhotoCenter({latitude: picture.latitude, longitude: picture.longitude});
  if (!center || !point) return false;
  const radians = value => value * Math.PI / 180;
  const deltaLat = radians(point.latitude - center.latitude), deltaLon = radians(point.longitude - center.longitude);
  const haversine = Math.sin(deltaLat / 2) ** 2 + Math.cos(radians(center.latitude)) * Math.cos(radians(point.latitude)) * Math.sin(deltaLon / 2) ** 2;
  return 6371.0088 * 2 * Math.asin(Math.sqrt(Math.min(1, Math.max(0, haversine)))) <= 20;
}

function photoPaginationMarkup(entry) {
  if (!entry) return "";
  const requestKey = photoRequestKey(entry);
  const request = state.photoRequests?.get(requestKey);
  if (!entry.photo_next_cursor) {
    if (request?.loading) return `<p class="photo-search-status assistant-progress-shimmer" role="status">${escapeHtml(translate("Memoir.workspace.picturesLoading"))}</p>`;
    if (request?.error) return `<button type="button" class="button button-secondary button-small" data-photo-retry="${escapeHtml(placeHistoryKey(entry))}">${escapeHtml(translate("Memoir.workspace.picturesSearchRetry"))}</button>`;
    return "";
  }
  const label = request?.loading ? "picturesLoading" : request?.error ? "picturesRetry" : "picturesMore";
  return `<div class="photo-pagination"><button type="button" class="button button-secondary button-small" data-photo-more="${escapeHtml(placeHistoryKey(entry))}" ${request?.loading ? 'disabled aria-busy="true"' : ""}>${escapeHtml(translate(`Memoir.workspace.${label}`))}</button></div>`;
}

function bindPhotoPagination() {
  photoPaginationObserver?.disconnect();
  const retry = document.querySelector("[data-photo-retry]");
  if (retry) retry.addEventListener("click", () => {
    const entry = (profile().memory_places || []).find(item => placeHistoryKey(item) === retry.dataset.photoRetry);
    if (entry) void loadPlacePictures(entry, state.project?.id, { force: true });
  });
  const button = document.querySelector("[data-photo-more]");
  if (!button) return;
  const projectId = state.project?.id;
  const entry = (profile().memory_places || []).find(item => placeHistoryKey(item) === button.dataset.photoMore);
  if (!entry || !entry.photo_next_cursor) return;
  const load = () => {
    if (button.isConnected && state.project?.id === projectId) void loadPlacePictures(entry, projectId, { more: true });
  };
  button.addEventListener("click", load);
  const requestKey = photoRequestKey(entry, projectId);
  if (state.photoRequests?.get(requestKey)?.error || !("IntersectionObserver" in window)) return;
  const wall = button.closest(".place-pictures");
  photoPaginationObserver = new IntersectionObserver(entries => {
    if (entries.some(item => item.isIntersecting)) load();
  }, { root: wall && wall.scrollHeight > wall.clientHeight + 1 ? wall : null,
    rootMargin: "0px 0px 160px 0px" });
  photoPaginationObserver.observe(button);
}

function photoSearchPeriod(entry, focus) {
  // Life-stage labels such as 青年时期 describe the memoir, not calendar
  // dates. Only a grounded year/range can restrict a historical photo search.
  if (entry?.period === "" || /(?:18|19|20)\d{2}/.test(entry?.period || "")) {
    return /(?:18|19|20)\d{2}/.test(entry.period || "") ? entry.period : "";
  }
  return /(?:18|19|20)\d{2}/.test(focus?.when || "") ? focus.when : "";
}

function referenceUrl(value) {
  try {
    const url = new URL(value, window.location.origin);
    return url.protocol === "https:" || (url.origin === window.location.origin && url.pathname.startsWith("/static/")) ? url.href : "";
  } catch { return ""; }
}

function pictureWall(pictures = [], entry = null) {
  const t = key => escapeHtml(translate(`Memoir.workspace.${key}`));
  const renderablePictures = mergePlacePictures([], pictures).filter((picture) => picture.allowed_actions?.embed
    && (!entry || photoMatchesScope(picture, entry, profile().story_focus)));
  if (!renderablePictures.length) return "";
  return `<section class="place-pictures" ${entry ? `data-photo-place="${escapeHtml(placeHistoryKey(entry))}"` : ""} aria-label="${t("publicReferenceCues")}">${renderablePictures.map((picture) => {
    const src = referenceUrl(picture.image_url);
    const source = referenceUrl(picture.source_url);
    const sceneDate = formatDateExpression(picture.date_expression ||
      [picture.scene_date_range?.start, picture.scene_date_range?.end].filter(Boolean).join("–"), currentUiLocale())
      || translate("Memoir.workspace.dateUnknown");
    const detail = [...new Set([picture.reference_place,
      picture.attribution || picture.location || picture.label || t("historicalReference")].filter(Boolean))].join(" · ");
    const sourceLink = source
      ? `<a href="${escapeHtml(source)}" target="_blank" rel="noreferrer">${escapeHtml(picture.title || t("historicalReference"))}</a>`
      : `<strong>${escapeHtml(picture.title || t("historicalReference"))}</strong>`;
    const media = src
      ? `<img src="${escapeHtml(src)}" alt="${escapeHtml(picture.title || "")}" loading="lazy" />`
      : `<div class="picture-wall-placeholder ${picture.kind === "video" ? "video-art" : "image-art"}" aria-hidden="true"><span>${picture.kind === "video" ? "▶" : "✦"}</span></div>`;
    const periodNote = picture.period_match === "decade" ? ` · ${t("sameDecadeReference")}`
      : picture.period_match === "nearby" ? ` · ${t("nearbyPeriodReference")}` : "";
    return `<figure><div class="picture-wall-media">${media}</div><figcaption>${sourceLink}<small>${escapeHtml(sceneDate)} · ${escapeHtml(detail)}${periodNote}</small></figcaption></figure>`;
  }).join("")}${photoPaginationMarkup(entry)}</section>`;
}

function placePictures(pictures = []) {
  return pictures.some((picture) => picture.allowed_actions?.embed) ? pictureWall(pictures) : "";
}

function nextAssistantMessageId() {
  assistantMessageSequence += 1;
  return `assistant-message-${assistantMessageSequence}`;
}

function updateStreamingAssistantMessage(message) {
  const row = document.querySelector(`[data-message-id="${message.id}"]`);
  if (!row) {
    render();
    return;
  }
  const scroll = $("#chat-scroll");
  const followConversation = conversationScroll.following();
  const text = row.querySelector(".message-text");
  const visibleText = cleanAssistantText(message.text);
  const responseStarted = Boolean(visibleText) && Boolean(text?.hidden);
  if (text) {
    text.innerHTML = formatText(visibleText);
    text.hidden = !visibleText;
  }
  const traceHtml = renderAgentTrace(message.trace || [], message.traceMode, message.streaming && !visibleText);
  const thinking = row.querySelector(".message-thinking");
  if (thinking) thinking.hidden = !message.streaming || Boolean(visibleText);
  const trace = row.querySelector(".message-trace");
  if (trace) {
    const expanded = trace.querySelector("details")?.open;
    trace.innerHTML = traceHtml;
    if (!responseStarted && expanded !== undefined && trace.querySelector("details")) trace.querySelector("details").open = expanded;
  }
  if (scroll && followConversation) conversationScroll.refresh();
}

function waitForAssistantStream() {
  return new Promise((resolve) => window.setTimeout(resolve, ASSISTANT_STREAM_DELAY_MS));
}

async function streamAssistantMessage(text, metadata = {}) {
  if (metadata.streamedMessage) {
    const { streamedMessage, ...details } = metadata;
    Object.assign(streamedMessage, details, { text: cleanAssistantText(String(text || streamedMessage.text)), streaming: false });
    render();
    return streamedMessage;
  }
  const value = cleanAssistantText(String(text || ""));
  if (!value) return null;
  const message = {
    ...metadata,
    id: nextAssistantMessageId(),
    role: "assistant",
    text: "",
    streaming: true,
  };
  state.chat.push(message);
  render();

  const characters = Array.from(value);
  for (let index = 0; index < characters.length; index += ASSISTANT_STREAM_CHUNK_SIZE) {
    message.text = characters.slice(0, index + ASSISTANT_STREAM_CHUNK_SIZE).join("");
    updateStreamingAssistantMessage(message);
    if (index + ASSISTANT_STREAM_CHUNK_SIZE < characters.length) await waitForAssistantStream();
  }
  message.text = value;
  message.streaming = false;
  render();
  return message;
}

async function hydratePlaceJourney() {
  const savedPlaces = mergePlaces(profile().memory_places || []);
  const projectId = state.project?.id;
  if (Array.isArray(profile().memory_places)
      && JSON.stringify(savedPlaces) !== JSON.stringify(profile().memory_places)) {
    await saveProfileUpdates({ memory_places: savedPlaces }, projectId);
    if (state.project?.id !== projectId) return;
  }
  if (Array.isArray(savedPlaces) && savedPlaces.length) {
    // History is ordered by life stage, while the current place follows the
    // most recent explicit mention. Server sequence/revision records recency.
    state.placeJourney = savedPlaces.reduce((current, place) =>
      Number(place.source_sequence || place.revision || 0) > Number(current.source_sequence || current.revision || 0)
        ? place : current, savedPlaces.at(-1));
    state.lifeStage = state.placeJourney.life_stage || "all";
    state.selectedPlace = placeHistoryKey(state.placeJourney);
    state.workspaceTab = "memoir";
    rememberPlaceJourneyProject(state.project?.id);
    void loadPlacePictures(state.placeJourney, projectId);
    resolvePlaceMap(state.placeJourney);
    return;
  }
  if (!state.supabase?.accessToken || !placeJourneyIsActivatedForProject()) return;
  try {
    const body = await supabaseApi("/v1/agent/place-journey");
    state.placeJourney = body.place_journey || null;
    state.placeJourneyChange = null;
    if (state.placeJourney) {
      state.lifeStage = state.placeJourney.life_stage || "all";
      state.selectedPlace = placeHistoryKey(state.placeJourney);
      resolvePlaceMap(state.placeJourney);
      void loadPlacePictures(state.placeJourney, state.project?.id);
    }
  } catch {
    // A missing journey endpoint must not prevent the memoir conversation.
  }
}

function placeJourneyIsActivatedForProject(projectId = state.project?.id) {
  if (!projectId) return false;
  try {
    return localStorage.getItem(PLACE_JOURNEY_PROJECT_STORAGE_KEY) === projectId;
  } catch {
    return false;
  }
}

function rememberPlaceJourneyProject(projectId = state.project?.id) {
  if (!projectId) return;
  try {
    localStorage.setItem(PLACE_JOURNEY_PROJECT_STORAGE_KEY, projectId);
  } catch {
    // The journey remains available for the current page when storage is restricted.
  }
}

function applyPersistedFamilyContext(context) {
  if (!context || typeof context !== "object") return;
  if (state.familyContext?.project_id === context.project_id
      && Number.isInteger(state.familyContext?.revision) && Number.isInteger(context.revision)
      && state.familyContext.revision > context.revision) return;
  const previous = state.familyContext?.project_id === context.project_id ? state.people : [];
  state.familyContext = context;
  state.people = Array.isArray(context.people) ? context.people.map(person => {
    const saved = previous.find(item => item.id === person.id && item.photo_path && item.photo_path === person.photo_path);
    return saved?.photo_url && !person.photo_url ? { ...person, photo_url: saved.photo_url } : person;
  }) : [];
  state.relationships = Array.isArray(context.relationships) ? context.relationships : [];
  if (state.memoryEventProject !== context.project_id) state.timeline = Array.isArray(context.timeline) ? context.timeline : [];
}

let memoryEventTimer = null;
async function refreshFamilyContext() {
  if (!state.familyFeaturesEnabled || !state.project?.id || !state.supabase?.accessToken) return null;
  const projectId = state.project.id;
  const ownerId = state.supabase.user?.id;
  try {
    const body = await supabaseApi(`/v1/agent/family-context?project_id=${encodeURIComponent(projectId)}`);
    if (state.project?.id !== projectId || state.supabase?.user?.id !== ownerId) return null;
    if (body?.family_features_enabled === true && body.family_context) applyPersistedFamilyContext(body.family_context);
    const snapshot = await storyApi(`/v1/story/events?project_id=${encodeURIComponent(projectId)}`);
    if (state.project?.id !== projectId || state.supabase?.user?.id !== ownerId) return null;
    if (Array.isArray(snapshot?.events)) {
      state.memoryEventProject = projectId;
      state.timeline = snapshot.events.map(event => ({ ...event,
        date_expression: event.temporal?.expression || "unknown",
        start_expression: event.temporal?.legacy_start_expression || event.temporal?.expression || "unknown",
        end_expression: event.temporal?.legacy_end_expression || event.temporal?.year_end?.toString() || "unknown",
        precision: event.temporal?.precision || "unknown", canonical: true }));
      render();
      if (memoryEventTimer) clearTimeout(memoryEventTimer);
      if (snapshot.processing?.pending_inputs) memoryEventTimer = setTimeout(refreshFamilyContext, 15000);
    }
    return body?.family_context || null;
  } catch (failure) {
    if (failure.status === 403 && state.project?.id === projectId && state.supabase?.user?.id === ownerId) {
      state.familyFeaturesEnabled = false;
      state.timeline = [];
      state.familyContext = null;
      state.people = [];
      state.relationships = [];
      state.memoryEventEdit = null;
      render();
    }
    return null;
  }
}

async function refreshFamilyEntitlement() {
  try {
    const entitlement = await storyApi("/v1/story/state");
    const features = new Set(entitlement.payment_features || []);
    state.familyEntitlement = entitlement;
    state.recallStatus = entitlement.recall_status || null;
    if (state.recallStatus?.payment_required) void ensureRecallPreview();
    state.familyFeaturesEnabled = entitlement.family_features_enabled === true
      && features.has("family_tree")
      && features.has("timeline");
    if (!state.familyFeaturesEnabled) {
      state.familyContext = null;
    } else {
      await refreshFamilyContext();
    }
  } catch {
    state.familyEntitlement = null;
    state.familyFeaturesEnabled = false;
    state.familyContext = null;
  }
  return state.familyFeaturesEnabled;
}

function loadVisualizationStylesheet(href) {
  const existing = Array.from(document.querySelectorAll("link[rel='stylesheet']")).some((link) => link.href === href);
  if (existing) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  link.dataset.memorySparkVisualization = href;
  document.head.appendChild(link);
}

function loadVisualizationScript(src) {
  if (visualizationLoadPromises.has(src)) return visualizationLoadPromises.get(src);
  const promise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.dataset.memorySparkVisualization = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Unable to load visualization renderer: ${src}`));
    document.head.appendChild(script);
  });
  visualizationLoadPromises.set(src, promise);
  return promise;
}

async function loadFamilyChartRenderer() {
  if (globalThis.f3?.createChart) return globalThis.f3;
  loadVisualizationStylesheet(`https://unpkg.com/family-chart@${FAMILY_CHART_VERSION}/dist/styles/family-chart.css`);
  if (!globalThis.d3) await loadVisualizationScript("https://unpkg.com/d3@7.9.0/dist/d3.min.js");
  await loadVisualizationScript(`https://unpkg.com/family-chart@${FAMILY_CHART_VERSION}/dist/family-chart.min.js`);
  if (!globalThis.f3?.createChart) throw new Error("Family chart renderer is unavailable");
  return globalThis.f3;
}

async function loadVisTimelineRenderer() {
  if (globalThis.vis?.Timeline) return globalThis.vis;
  loadVisualizationStylesheet(`https://unpkg.com/vis-timeline@${VIS_TIMELINE_VERSION}/styles/vis-timeline-graph2d.min.css`);
  await loadVisualizationScript(`https://unpkg.com/vis-timeline@${VIS_TIMELINE_VERSION}/standalone/umd/vis-timeline-graph2d.min.js`);
  if (!globalThis.vis?.Timeline) throw new Error("Timeline renderer is unavailable");
  return globalThis.vis;
}

function familyChartData() {
  const records = state.people
    .filter((person) => person?.id && person?.name)
    .map((person) => {
      const parts = String(person.name).trim().split(/\s+/).filter(Boolean);
      const data = {
        "first name": parts.shift() || person.name,
        "last name": parts.join(" "),
        gender: person.gender || "U",
      };
      if (person.family_title) data["family title"] = person.family_title;
      if (person.birth_date_expression) data.birthday = person.birth_date_expression;
      return { id: String(person.id), data, rels: { parents: [], children: [], spouses: [] } };
    });
  const byId = new Map(records.map((record) => [record.id, record]));
  const connect = (record, key, targetId) => {
    if (record && !record.rels[key].includes(targetId)) record.rels[key].push(targetId);
  };
  state.relationships.forEach((relation) => {
    const fromId = String(relation?.from_person_id || "");
    const toId = String(relation?.to_person_id || "");
    const from = byId.get(fromId);
    const to = byId.get(toId);
    if (!from || !to) return;
    switch (relation.relationship_type) {
      case "parent":
      case "adoptive_parent":
      case "step_parent":
        connect(from, "children", toId);
        connect(to, "parents", fromId);
        break;
      case "child":
      case "adopted_child":
      case "step_child":
        connect(from, "parents", toId);
        connect(to, "children", fromId);
        break;
      case "spouse":
        connect(from, "spouses", toId);
        connect(to, "spouses", fromId);
        break;
      default:
        break;
    }
  });
  return records;
}

function timelineDate(expression, end = false) {
  if (typeof expression !== "string") return null;
  const cleaned = expression.trim();
  const exact = cleaned.match(/\b(\d{4})[-/](\d{1,2})(?:[-/](\d{1,2}))?\b/);
  if (exact) {
    const month = String(Number(exact[2])).padStart(2, "0");
    const day = String(Number(exact[3] || (end ? 28 : 1))).padStart(2, "0");
    return `${exact[1]}-${month}-${day}`;
  }
  const year = cleaned.match(/\b([12]\d{3})\b/);
  if (!year) return null;
  return `${year[1]}-${end ? "12-31" : "07-01"}`;
}

function timelineRendererItems() {
  return state.timeline.map((item) => ({
    id: String(item.id),
    content: escapeHtml(item.title),
    start: timelineDate(item.kind === "period" ? item.start_expression : item.date_expression),
    end: item.kind === "period" ? timelineDate(item.end_expression, true) : null,
    className: item.kind === "period" ? "memoir-period" : "memoir-event",
  }))
    .filter((item) => item.start)
    .map((item) => (item.end && item.end <= item.start ? { ...item, end: null } : item));
}

async function mountFamilyChartAdapter(container) {
  try {
    const data = familyChartData();
    if (!data.length) return;
    const f3 = await loadFamilyChartRenderer();
    if (!document.body.contains(container)) return;
    const mount = document.createElement("div");
    mount.className = "family-chart-library f3";
    mount.id = `family-chart-renderer-${familyChartMountId += 1}`;
    mount.setAttribute("aria-label", translate("Memoir.workspace.familyChart"));
    container.insertBefore(mount, container.querySelector(".family-chart-fallback"));
    const chart = f3.createChart(`#${mount.id}`, data);
    chart.setSingleParentEmptyCard(false);
    chart.setShowSiblingsOfMain(true);
    chart.setCardXSpacing(210);
    chart.setCardYSpacing(230);
    const author = familyAuthor();
    if (author) chart.updateMainId(String(author.id));
    chart.setCardHtml()
      .setCardInnerHtmlCreator((datum) => familyPersonCard(state.people.find(person => String(person.id) === datum.data.id)))
      .setOnCardClick((event, datum) => selectFamilyPerson(datum.data.id));
    chart.updateTree({ initial: true, transition_time: 0, tree_position: "fit" });
    familyCharts.set(container, { chart, f3 });
    container.querySelectorAll("[data-family-zoom]").forEach(button => { button.disabled = false; });
    const renderedIds = new Set(Array.from(mount.querySelectorAll("[data-family-person]"), button => button.dataset.familyPerson));
    const fallback = container.querySelector(".family-chart-fallback");
    fallback?.querySelectorAll("[data-family-person]").forEach(button => {
      if (renderedIds.has(button.dataset.familyPerson)) button.remove();
    });
    if (fallback) {
      fallback.hidden = !fallback.querySelector("[data-family-person]");
      if (!fallback.hidden) fallback.insertAdjacentHTML("afterbegin", `<p class="family-chart-hint">${escapeHtml(translate("Memoir.workspace.familyUnlinked"))}</p>`);
    }
    mount.dataset.libraryMounted = "family-chart";
    container.dataset.rendererStatus = "family-chart";
  } catch (error) {
    container.querySelector(".family-chart-library")?.remove();
    container.dataset.rendererStatus = "fallback";
    console.warn("Family chart renderer unavailable; using the accessible person cards.", error);
  }
}

async function mountVisTimelineAdapter(container) {
  try {
    const items = timelineRendererItems();
    if (!items.length) return;
    const vis = await loadVisTimelineRenderer();
    if (!document.body.contains(container)) return;
    const mount = document.createElement("div");
    mount.className = "vis-timeline-library";
    mount.id = `vis-timeline-renderer-${timelineMountId += 1}`;
    mount.setAttribute("aria-hidden", "true");
    container.appendChild(mount);
    const dataset = vis.DataSet ? new vis.DataSet(items) : items;
    new vis.Timeline(mount, dataset, {
      stack: true,
      zoomMin: 31_536_000_000,
      orientation: "top",
      height: "280px",
      margin: { item: 12, axis: 8 },
    });
    mount.dataset.libraryMounted = "vis-timeline";
    container.dataset.rendererStatus = "vis-timeline";
  } catch (error) {
    container.dataset.rendererStatus = "fallback";
    console.warn("Timeline renderer unavailable; using the accessible list.", error);
  }
}

function initFamilyVisualizations() {
  const family = document.querySelector("[data-renderer='family-chart']");
  const timeline = document.querySelector("[data-renderer='vis-timeline']");
  if (family) mountFamilyChartAdapter(family);
  if (timeline) mountVisTimelineAdapter(timeline);
}

async function startCodexConversation({ resume = false } = {}) {
  if (!state.project || state.codexStarting || state.codexReady || state.chat.length) return;
  if (state.recallStatus?.payment_required) return;
  state.codexStarting = true;
  const profileOpening = !resume || state.profileIntakePending;
  if (profileOpening) {
    // The opening is product copy, not an agent turn. Keep it available while
    // the first real storyteller answer creates or resumes the Codex thread.
    state.loading = false;
    try {
      await streamAssistantMessage(conversationMessage("opening"), {
        trace: simulatedLoopTrace(
          ["conversation.start", "memory.search"],
          translate("Memoir.trace.opening"),
        ),
        traceMode: "simulated",
      });
    } finally {
      state.codexStarting = false;
      state.codexReady = true;
      state.loading = false;
      render();
    }
    return;
  }

  state.loading = true;
  render();
  const fallback = conversationMessage("resume");
  try {
    // Returning to saved memories is navigation, not a new recall round.
    const message = await streamAssistantMessage(fallback, { traceMode: "simulated" });
    if (message) render();
  } finally {
    state.codexStarting = false;
    state.codexReady = true;
    state.loading = false;
    render();
  }
}

function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.classList.add("show");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => node.classList.remove("show"), 3600);
}

function setLoading(value) {
  state.loading = value;
  if (value && !state.project) $("#app").innerHTML = `<div class="loading">${escapeHtml(translate("Common.loading"))}</div>`;
}

function profile() {
  return state.project?.profile || {};
}

function isFreshAnonymousSession() {
  return Boolean(state.freshAnonymousSession && state.supabase?.user?.is_anonymous);
}

function profileHasContext(profileValue = profile()) {
  const focus = profileValue?.story_focus;
  return Boolean(
    profileValue?.name
    || profileValue?.birth_year
    || profileValue?.birth_date_expression
    || profileValue?.birth_place
    || profileValue?.childhood_place
    || (focus && Object.values(focus).some(Boolean))
  );
}

function mergeProfileUpdates(updates) {
  if (!updates || typeof updates !== "object") return null;
  const current = { ...profile() };
  const next = { ...current };
  ["name", "birth_date_expression", "birth_place", "childhood_place"].forEach((key) => {
    if (typeof updates[key] === "string" && updates[key].trim()) next[key] = updates[key].trim();
  });
  const incomingLocale = updates.conversation_language;
  const savedLocale = current.conversation_language;
  const validLocale = incomingLocale?.version === 1 && incomingLocale.initialized === true;
  const currentLocale = !savedLocale || validLocale && Number(incomingLocale.revision || 0) >= Number(savedLocale.revision || 0);
  if (validLocale && currentLocale) {
    next.conversation_language = incomingLocale;
    if (["en-AU", "zh-CN"].includes(incomingLocale.locale)) next.preferred_language = incomingLocale.locale;
    else delete next.preferred_language;
  }
  if (["en-AU", "zh-CN"].includes(updates.preferred_language) && currentLocale) next.preferred_language = updates.preferred_language;
  if (Array.isArray(updates.memory_places)) next.memory_places = updates.memory_places;
  if (["male", "female"].includes(updates.avatar_style)) next.avatar_style = updates.avatar_style;
  if (Number.isInteger(updates.birth_year)) next.birth_year = updates.birth_year;
  if (updates.story_focus && typeof updates.story_focus === "object") {
    const focus = { ...(current.story_focus || {}) };
    ["who", "where", "when", "what", "life_stage"].forEach((key) => {
      if (typeof updates.story_focus[key] === "string" && updates.story_focus[key].trim()) focus[key] = updates.story_focus[key].trim();
    });
    if (Object.keys(focus).length) next.story_focus = focus;
  }
  return JSON.stringify(next) === JSON.stringify(current) ? null : next;
}

async function saveProfileUpdates(updates, expectedProjectId = null, { force = false } = {}) {
  if (!updates || !state.project || (expectedProjectId && state.project.id !== expectedProjectId)) return;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    if (!state.project || (expectedProjectId && state.project.id !== expectedProjectId)) return;
    const project = state.project;
    const merged = mergeProfileUpdates(updates) || (force ? { ...profile(), ...updates } : null);
    if (!merged) return;
    state.project = { ...project, profile: merged };
    state.profileIntakePending = false;
    try {
      const saved = await api(`/v1/projects/${project.id}`, {
        method: "PATCH",
        body: JSON.stringify({ profile: merged, expected_revision: project.revision }),
      });
      if (state.project?.id === project.id) state.project = { ...state.project, ...saved,
        profile: { ...saved.profile, ...(state.project.profile?.conversation_language ? {
          preferred_language:state.project.profile.preferred_language, conversation_language:state.project.profile.conversation_language} : {}) } };
      return;
    } catch (error) {
      if (error.status === 409 && attempt === 0 && state.project?.id === project.id) {
        // Another serialized workspace update may have advanced the project
        // revision. Reload the base profile and retry the same explicit fields.
        const latest = await api(`/v1/projects/${project.id}`);
        if (state.project?.id === project.id) state.project = { ...state.project, ...latest,
          profile: preserveConversationLocale(latest.profile, state.project.profile) };
        continue;
      }
      toast(translateWith("Memoir.conversation.profileSaveError", { error: error.message }));
      return;
    }
  }
}

async function applyCommittedConversationLocale(updates) {
  if (!updates?.conversation_language || !state.project) return;
  const merged = mergeProfileUpdates({preferred_language:updates.preferred_language,
    conversation_language:updates.conversation_language});
  if (merged) state.project = {...state.project, profile:merged};
  await applyProfileUiLocale(conversationLanguage());
}

function preserveConversationLocale(incoming = {}, current = {}) {
  const saved = current.conversation_language;
  const candidate = incoming.conversation_language;
  if (saved?.initialized && (!candidate?.initialized || Number(candidate.revision || 0) < Number(saved.revision || 0))) {
    return { ...incoming, preferred_language: current.preferred_language, conversation_language: saved };
  }
  return incoming;
}

function profileDetails() {
  const user = state.supabase?.user || state.supabaseSession?.user || {};
  const metadata = user.user_metadata || {};
  const name = profile().name || metadata.full_name || metadata.name || user.email || (user.is_anonymous ? translate("Common.privateSession") : translate("Common.yourProfile"));
  const parts = String(name).trim().split(/\s+/).filter(Boolean);
  const initials = parts.length > 1
    ? `${parts[0][0]}${parts[parts.length - 1][0]}`
    : (parts[0] || "Me").slice(0, 2);
  return { name, initials: initials.toUpperCase() };
}

function profileMenu() {
  const details = profileDetails();
  const t = (key) => escapeHtml(translate(`Common.${key}`));
  const anonymous = Boolean(state.supabase?.user?.is_anonymous);
  const authAction = anonymous ? "login" : "logout";
  return `
    <div class="profile-menu" data-profile-menu>
      <button class="profile-trigger" type="button" data-profile-trigger aria-label="${t("openProfile")}" aria-expanded="false" aria-haspopup="menu" aria-controls="profile-menu-content">
        <span class="profile-avatar" aria-hidden="true">${escapeHtml(details.initials)}</span>
        <span class="profile-trigger-copy"><span class="profile-trigger-label">${t("profile")}</span><span class="profile-trigger-name">${escapeHtml(details.name)}</span></span>
        <span class="profile-chevron" aria-hidden="true"></span>
      </button>
      <div class="profile-dropdown" id="profile-menu-content" role="menu" hidden>
        <button class="profile-menu-item" type="button" role="menuitem" data-profile-action="settings">${t("profile")}</button>
        <button class="profile-menu-item" type="button" role="menuitem" data-profile-action="collection">${escapeHtml(translate("Collection.title"))}</button>
        ${state.supabase?.user && !state.supabase.user.is_anonymous ? `<button class="profile-menu-item" type="button" role="menuitem" data-profile-action="attached-history">${escapeHtml(translate("AuthReminder.attachedHistory"))}</button>` : ""}
        <button class="profile-menu-item profile-auth-action" type="button" role="menuitem" data-profile-action="${authAction}"><span>${t(authAction)}</span><span aria-hidden="true">↗</span></button>
      </div>
    </div>`;
}

function closeProfileMenu(restoreFocus = false) {
  const menu = $("[data-profile-menu]");
  const trigger = menu?.querySelector("[data-profile-trigger]");
  const dropdown = menu?.querySelector(".profile-dropdown");
  if (!menu || !trigger || !dropdown) return;
  menu.classList.remove("is-open");
  trigger.setAttribute("aria-expanded", "false");
  dropdown.hidden = true;
  if (restoreFocus) trigger.focus();
}

function refreshProfileMenu() {
  const menu = $("[data-profile-menu]");
  if (!menu) return;
  const open = menu.querySelector("[data-profile-trigger]")?.getAttribute("aria-expanded") === "true";
  menu.outerHTML = profileMenu();
  bindProfileMenu();
  if (open) $("[data-profile-trigger]")?.click();
}

function bindProfileMenu() {
  const menu = $("[data-profile-menu]");
  const trigger = menu?.querySelector("[data-profile-trigger]");
  const dropdown = menu?.querySelector(".profile-dropdown");
  if (!menu || !trigger || !dropdown) return;
  trigger.addEventListener("click", () => {
    const open = trigger.getAttribute("aria-expanded") === "true";
    if (open) {
      closeProfileMenu();
      return;
    }
    menu.classList.add("is-open");
    trigger.setAttribute("aria-expanded", "true");
    dropdown.hidden = false;
  });
  menu.querySelector("[data-profile-action='settings']")?.addEventListener("click", () => {
    closeProfileMenu();
    openProfileSettings({
      api: storyApi,
      onLanguageChange: applyProfileUiLocale,
      onSave: async (settings) => {
        if (state.project) {
          const projectId = state.project.id;
          const ownerId = state.supabase?.user?.id;
          const updated = preserveConversationLocale({ ...profile(), ...settings }, profile());
          state.project = {...state.project, profile:updated};
          const saved = await api(`/v1/projects/${projectId}`, {
            method: "PATCH",
            body: JSON.stringify({ profile: updated, expected_revision: state.project.revision }),
          });
          if (state.project?.id !== projectId || state.supabase?.user?.id !== ownerId) return;
          state.project = { ...state.project, ...saved,
            profile:preserveConversationLocale({...saved.profile, ...settings}, profile()) };
        }
        await applyProfileUiLocale(conversationLanguage());
        render();
      },
      onClose: () => $("[data-profile-trigger]")?.focus(),
    });
  });
  menu.querySelector("[data-profile-action='logout']")?.addEventListener("click", signOut);
  menu.querySelector("[data-profile-action='login']")?.addEventListener("click", () => {
    closeProfileMenu();
    authReminder.open({ signIn: true });
  });
  menu.querySelector("[data-profile-action='collection']")?.addEventListener("click", reviewCollection);
  menu.querySelector("[data-profile-action='attached-history']")?.addEventListener("click", () => {
    closeProfileMenu();
    openAttachedConversations(storyApi);
  });
}

async function reviewCollection() {
  closeProfileMenu();
  if (state.loading || state.recording || state.voiceMode || state.storyRecording) return;
  try {
    await openCollectionReview({ api: storyApi, projectId: state.project.id, language: conversationLanguage() });
  } catch (error) { toast(error.message); }
}

async function signOut() {
  closeProfileMenu();
  try {
    const previousProjectId = state.project?.id;
    if (state.supabase?.client) {
      const { error } = await state.supabase.client.auth.signOut();
      if (error) throw new Error(translate("Errors.logoutFailed"));
    }
    state.recordingStream?.getTracks().forEach((track) => track.stop());
    state.supabase = null;
    state.supabaseSession = null;
    state.accountId = null;
    state.csrfToken = "";
    state.project = null;
    state.session = null;
    state.memories = [];
    state.sources = [];
    state.chapters = [];
    state.people = [];
    state.relationships = [];
    state.timeline = [];
    state.preview = null;
    state.chat = [];
    state.freshAnonymousSession = false;
    state.codexStarting = false;
    state.codexReady = false;
    state.profileIntakePending = true;
    state.placeJourney = null;
    state.placeJourneyChange = null;
    state.workspaceTab = "memoir";
    state.workspaceUnlocked = false;
    state.compositionStage = 0;
    state.workspaceCollapsed = false;
    state.lifeStage = "childhood";
    state.chapterDecision = null;
    state.story = null;
    state.familyEntitlement = null;
    state.familyFeaturesEnabled = false;
    state.familyContext = null;
    state.storyPlans = [];
    state.selectedStoryPlan = "electronic_memoir_v1";
    state.storyBookCount = 2;
    state.storyAnswers = [];
    state.storyChapter = null;
    state.storyRecording = false;
    state.storyRecorder = null;
    state.storyRecordingStream = null;
    state.storyRecordedChunks = [];
    state.storyAudioBase64 = "";
    state.storyTranscript = "";
    state.storyAudioPlayer = null;
    state.checkout = null;
    state.recording = false;
    state.recorder = null;
    state.recordingStream = null;
    state.recordedChunks = [];
    state.audioUploadId = null;
    state.audioTranscript = "";
    state.audioPlayer = null;
    state.recognition = null;
    try {
      localStorage.removeItem("memory-spark-project");
      localStorage.removeItem(PLACE_JOURNEY_PROJECT_STORAGE_KEY);
      localStorage.removeItem("memory-spark-story-started");
      sessionStorage.removeItem("memory-spark-supabase-session");
      if (previousProjectId) sessionStorage.removeItem(chatHistoryStorageKey(previousProjectId));
    } catch { /* private browsing or storage restrictions */ }
    navigateTo(MEMOIR_ROUTES.home, true);
    await boot();
  } catch (error) {
    toast(error.message || translate("Errors.logoutFailed"));
  }
}

function memoryFollowUpBudget(session = state.session) {
  const offered = Number(session?.follow_ups_offered || 0);
  return Math.max(1, Math.min(3, offered));
}

function memoryFollowUpsRemaining(session = state.session) {
  const used = Number(session?.follow_ups_used || 0);
  return Math.max(0, memoryFollowUpBudget(session) - used);
}

function memoryFollowUpPrompt(session = state.session) {
  if (session?.context_cues?.length) return conversationMessage("publicCueFollowUp");
  return conversationMessage("memoryFollowUp");
}

function memoryTurnFallback(session = state.session) {
  if (memoryFollowUpsRemaining(session) > 0) return memoryFollowUpPrompt(session);
  return conversationMessage("memoryComplete");
}

function storyRoundQuestion() {
  return conversationMessage("fallback");
}

const STORY_ROUNDS_REQUIRED = 5;

const FALLBACK_STORY_PLANS = [
  { plan_key: "electronic_memoir_v1", name: "Electronic memoir", price_minor: 4900, description: "A beautifully shaped electronic version of your memoir.", features: ["Electronic memoir", "Source-linked story chapters", "Private digital delivery"], electronic_only: true, additional_book_price_minor: 0, minimum_books: 0, default_books: 0 },
  { plan_key: "printed_memoir_v1", name: "Printed memoir", price_minor: 7900, description: "Two printed books, with extra copies available for A$10 each.", features: ["Electronic memoir", "2 printed books", "Add extra books for A$10 each"], electronic_only: false, additional_book_price_minor: 1000, minimum_books: 2, default_books: 2 },
  { plan_key: "family_memoir_v1", name: "Family legacy memoir", price_minor: 12900, description: "Two printed books plus a richer family record.", features: ["Electronic memoir", "2 printed books", "Family tree", "Life timeline", "More detailed story context"], electronic_only: false, additional_book_price_minor: 1000, minimum_books: 2, default_books: 2 },
];

function formatAudMinor(amountMinor) {
  return new Intl.NumberFormat(currentUiLocale(), { style: "currency", currency: "AUD", currencyDisplay: "code", maximumFractionDigits: 0 }).format(Number(amountMinor || 0) / 100);
}

function storyPlanTotal(plan, bookCount) {
  if (plan.electronic_only) return plan.price_minor;
  return plan.price_minor + Math.max(0, Number(bookCount || plan.default_books || 2) - 2) * (plan.additional_book_price_minor || 1000);
}

function storyPlanCopy(plan) {
  const copy = globalThis.__copyme2Intl?.messages?.Memoir?.storyFlow?.plans?.[plan.plan_key];
  if (!copy) return { name: plan.name, description: plan.description, features: plan.features || [] };
  return { ...copy, features: Object.values(copy.features || {}) };
}

function storyCheckoutForm() {
  const plans = state.storyPlans.length ? state.storyPlans : FALLBACK_STORY_PLANS;
  const selectedPlan = plans.find((plan) => plan.plan_key === state.selectedStoryPlan) || plans[0];
  const selectedKey = selectedPlan.plan_key;
  const bookCount = Math.max(2, Number(state.storyBookCount || selectedPlan.default_books || 2));
  const printed = !selectedPlan.electronic_only;
  const total = storyPlanTotal(selectedPlan, printed ? bookCount : 0);
  const t = (key, values = {}) => escapeHtml(translateWith(`Memoir.storyFlow.${key}`, values));
  const checkoutMessage = state.checkout?.message ? `<p class="fine-print story-payment-note">${escapeHtml(state.checkout.message)}</p>` : "";
  return `
    <form id="story-checkout-form" class="story-checkout-form">
      <div class="story-plan-grid" role="radiogroup" aria-label="${t("packagesLabel")}">
        ${plans.map((plan) => { const copy = storyPlanCopy(plan); return `
          <label class="story-plan-card ${plan.plan_key === selectedKey ? "selected" : ""}">
            <input type="radio" name="plan_key" value="${escapeHtml(plan.plan_key)}" ${plan.plan_key === selectedKey ? "checked" : ""} />
            <span class="story-plan-card-top"><span class="eyebrow">${escapeHtml(copy.name)}</span><strong>${t("fromPrice", { price: formatAudMinor(plan.price_minor) })}</strong></span>
            <span class="story-plan-description">${escapeHtml(copy.description)}</span>
            <span class="story-plan-features">${copy.features.map((feature) => `<span>✓ ${escapeHtml(feature)}</span>`).join("")}</span>
          </label>`; }).join("")}
      </div>
      <div class="story-book-options ${printed ? "" : "is-disabled"}">
        <label for="story-book-count"><span>${t("printedBooks")}</span><select id="story-book-count" name="book_count" ${printed ? "" : "disabled"}>${Array.from({ length: 19 }, (_, index) => index + 2).map((count) => `<option value="${count}" ${count === bookCount ? "selected" : ""}>${t("bookCount", { count })}${count > 2 ? t("extraBooks", { price: formatAudMinor((count - 2) * 1000) }) : ""}</option>`).join("")}</select></label>
        <div class="story-checkout-total"><span>${t("totalToday")}</span><strong data-story-total>${formatAudMinor(total)}</strong></div>
      </div>
      <button type="submit" class="button button-primary" ${state.loading ? "disabled" : ""}>${t("continueCheckout")} <span>↗</span></button>
      <p class="fine-print">${t("pricesNote")}</p>
      ${checkoutMessage}
    </form>`;
}

function checkoutRedirectNotice() {
  const status = new URLSearchParams(window.location.search).get("checkout");
  if (status === "success" && state.story?.payment_status !== "paid") return translate("Memoir.storyFlow.paymentConfirming");
  if (status === "cancelled") return translate("Memoir.storyFlow.paymentCancelled");
  return "";
}

function renderStoryFlow() {
  const t = (key, values = {}) => escapeHtml(translateWith(`Memoir.storyFlow.${key}`, values));
  const completed = Number(state.story?.rounds_completed || 0);
  const anonymous = Boolean(state.story?.is_anonymous);
  const chapter = state.storyChapter;
  const isAnswering = completed < STORY_ROUNDS_REQUIRED;
  const isLinking = completed >= STORY_ROUNDS_REQUIRED && anonymous;
  const needsFreeChapter = completed >= STORY_ROUNDS_REQUIRED && !anonymous && !state.story?.free_chapter_claimed;
  const needsPayment = Boolean(state.story?.free_chapter_claimed && state.story?.next_action === "payment");
  let body = "";

  if (isAnswering) {
    body = `
      <div class="story-progress">${t("roundProgress", { current: completed + 1, total: STORY_ROUNDS_REQUIRED })}</div>
      <h1>${escapeHtml(storyRoundQuestion())}</h1>
      <p class="story-lead">${t("takeTime")}</p>
      <div class="story-question-tools"><button type="button" class="listen-button" data-story-action="listen-story-question">◖ ${t("listenAiVoice")}</button><span>${t("aiAudioAvailable")}</span></div>
      <form id="story-round-form" class="story-round-form">
        <button type="button" class="voice-button story-voice-button ${state.storyRecording ? "recording" : ""}" data-story-action="toggle-story-voice" aria-label="${state.storyRecording ? t("stopVoiceAnswer") : t("recordVoiceAnswer")}">${state.storyRecording ? "■" : "●"} ${state.storyRecording ? t("stopVoiceAnswer") : t("recordVoiceAnswer")}</button>
        <textarea id="story-answer" rows="7" placeholder="${t("answerPlaceholder")}" aria-label="${t("yourStoryAnswer")}">${escapeHtml(state.storyTranscript)}</textarea>
        <p class="composer-note">${state.storyAudioBase64 ? t("reviewTranscript") : t("typeRecordSkip")}</p>
        <button type="submit" class="button button-primary">${t("saveAnswer")} <span>↗</span></button>
      </form>`;
  } else if (isLinking) {
    body = `
      <div class="story-progress">${t("roundsComplete")}</div>
      <h1>${t("firstFiveReady")}</h1>
      <p class="story-lead">${t("createAccount")}</p>
      <div class="story-auth-actions">
        <button class="button button-primary" data-story-provider="google">${t("continueGoogle")} <span>↗</span></button>
        <button class="button button-secondary" data-story-provider="facebook">${t("continueFacebook")}</button>
      </div>
      <p class="fine-print">${t("anonymousLinked")}</p>`;
  } else if (needsFreeChapter) {
    body = `
      <div class="story-progress">${t("freeChapter")}</div>
      <h1>${t("shapeChapter")}</h1>
      <p class="story-lead">${t("savedPrivately")}</p>
      <button class="button button-primary" data-story-action="free-chapter">${t("claimFreeChapter")} <span>↗</span></button>`;
  } else if (needsPayment) {
    const redirectNotice = checkoutRedirectNotice();
    body = `
      <div class="story-progress">${t("chapterIsYours")}</div>
      <h1>${t("readyToContinue")}</h1>
      ${chapter ? `<article class="story-chapter"><div class="eyebrow">${t("roundLabel", { number: 1 })} · ${escapeHtml(chapter.title)}</div><p>${formatText(chapter.text)}</p></article>` : `<p class="story-lead">${t("freeChapterSaved")}</p>`}
      <p class="story-lead">${t("chooseFinish")}</p>
      ${redirectNotice ? `<p class="story-payment-banner">${escapeHtml(redirectNotice)}</p>` : ""}
      ${storyCheckoutForm()}`;
  } else {
    const paidPlan = (state.storyPlans.length ? state.storyPlans : FALLBACK_STORY_PLANS).find((plan) => plan.plan_key === state.story?.payment_plan);
    const paidPlanName = paidPlan ? storyPlanCopy(paidPlan).name : "";
    body = `
      <div class="story-progress">${t("memoirComplete")}</div>
      <h1>${t("memoirReady")}</h1>
      <p class="story-lead">${t("paidUnlocked", { package: paidPlan ? ` (${paidPlanName})` : "" })}</p>
      <button class="button button-primary" data-story-action="full-memoir">${t("generateMemoir")} <span>↗</span></button>`;
  }

  $("#app").innerHTML = `
    <div class="story-shell conversation-only">
      <header class="story-topbar">
        <a class="brand" href="/memoir" data-action="story-flow-home"><img class="brand-mark" src="/static/copyme2_icon_light.png" alt="" aria-hidden="true" /><span class="brand-name">${escapeHtml(translate("Memoir.story.brand"))}</span></a>
        <div class="story-topbar-actions"><div class="story-status"><span class="topbar-hint">${t("savedWithSupabase")}</span></div>${profileMenu()}</div>
      </header>
      <main class="chat-main story-flow-main" aria-label="${t("mainLabel")}">
        <div class="story-flow-card">${body}</div>
        <div class="story-answer-list">${state.storyAnswers.map((answer, index) => `<article><span>${t("roundLabel", { number: index + 1 })}</span><p>${formatText(answer)}</p></article>`).join("")}</div>
  </main>
    </div>`;
  bindStoryFlowActions();
  bindProfileMenu();
}

function bindStoryFlowActions() {
  $("[data-action='story-flow-home']")?.addEventListener("click", (event) => {
    event.preventDefault();
    state.story = null;
    state.familyEntitlement = null;
    state.familyFeaturesEnabled = false;
    state.familyContext = null;
    state.storyAnswers = [];
    state.storyChapter = null;
    state.storyRecording = false;
    state.storyAudioBase64 = "";
    state.storyTranscript = "";
    state.storyAudioFilename = "story-round.webm";
    state.storyAudioMimeType = "audio/webm";
    state.checkout = null;
    localStorage.removeItem("memory-spark-story-started");
    navigateTo(MEMOIR_ROUTES.home, true);
  });
  $("#story-round-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    submitStoryRound();
  });
  $("#story-answer")?.addEventListener("input", (event) => { state.storyTranscript = event.target.value; });
  $("#story-checkout-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    requestStoryCheckout();
  });
  document.querySelectorAll("input[name='plan_key']").forEach((input) => input.addEventListener("change", () => {
    state.selectedStoryPlan = input.value;
    render();
  }));
  $("#story-book-count")?.addEventListener("change", (event) => {
    state.storyBookCount = Number(event.target.value) || 2;
    const plan = (state.storyPlans.length ? state.storyPlans : FALLBACK_STORY_PLANS).find((item) => item.plan_key === state.selectedStoryPlan);
    const total = $("[data-story-total]");
    if (plan && total) total.textContent = formatAudMinor(storyPlanTotal(plan, state.storyBookCount));
  });
  document.querySelectorAll("[data-story-provider]").forEach((button) => {
    button.addEventListener("click", () => linkStoryIdentity(button.dataset.storyProvider));
  });
  const actions = {
    "free-chapter": claimFreeChapter,
    checkout: requestStoryCheckout,
    "full-memoir": generateFullMemoir,
    "toggle-story-voice": toggleStoryVoice,
    "listen-story-question": () => speakStoryQuestion(storyRoundQuestion()),
  };
  document.querySelectorAll("[data-story-action]").forEach((button) => {
    const action = actions[button.dataset.storyAction];
    if (action) button.addEventListener("click", action);
  });
}

async function refreshStoryState(shouldRender = true) {
  state.story = await storyApi("/v1/story/state");
  if (!state.storyPlans.length) {
    state.storyPlans = (await storyApi("/v1/story/plans")).items || [];
  }
  if (shouldRender && state.story) render();
  return state.story;
}

async function submitStoryRound() {
  if (state.loading) return;
  const input = $("#story-answer");
  const answer = input?.value.trim() || state.storyTranscript.trim() || "";
  if (!answer && !state.storyAudioBase64) return toast(translate("Memoir.storyFlow.aFewWords"));
  state.loading = true;
  try {
    const result = await storyApi("/v1/story/rounds", {
      method: "POST",
      body: JSON.stringify({ round: Number(state.story.rounds_completed) + 1, answer, audio_base64: state.storyAudioBase64 || undefined, audio_filename: state.storyAudioFilename, audio_mime_type: state.storyAudioMimeType }),
    });
    state.storyAnswers.push(result.transcript || answer);
    state.story = result;
    state.storyAudioBase64 = "";
    state.storyTranscript = "";
  } catch (error) {
    toast(error.message);
  } finally {
    state.loading = false;
    render();
  }
}

function toggleStoryVoice() {
  if (state.storyRecording && state.storyRecorder) {
    state.storyRecorder.stop();
    return;
  }
  startStoryVoiceRecorder();
}

async function startStoryVoiceRecorder() {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return toast(translate("Memoir.storyFlow.browserCannotRecord"));
  try {
    state.storyRecordingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const preferredMime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((value) => window.MediaRecorder.isTypeSupported?.(value));
    const recorder = preferredMime ? new MediaRecorder(state.storyRecordingStream, { mimeType: preferredMime }) : new MediaRecorder(state.storyRecordingStream);
    state.storyRecorder = recorder;
    state.storyRecordedChunks = [];
    recorder.addEventListener("dataavailable", (event) => { if (event.data.size) state.storyRecordedChunks.push(event.data); });
    recorder.addEventListener("stop", async () => {
      const blob = new Blob(state.storyRecordedChunks, { type: recorder.mimeType || "audio/webm" });
      state.storyRecordingStream?.getTracks().forEach((track) => track.stop());
      state.storyRecordingStream = null;
      state.storyRecording = false;
      state.storyRecorder = null;
      if (!blob.size) return render();
      try {
        state.storyAudioBase64 = await blobToBase64(blob);
        state.storyAudioFilename = `story-round-${Date.now()}.webm`;
        state.storyAudioMimeType = (blob.type || "audio/webm").split(";")[0];
        const transcript = await storyApi("/v1/story/transcriptions", { method: "POST", body: JSON.stringify({ audio_base64: state.storyAudioBase64, filename: state.storyAudioFilename, mime_type: state.storyAudioMimeType, language: conversationLanguage() }) });
        state.storyTranscript = transcript.text || "";
        toast(translate("Memoir.storyFlow.transcriptReady"));
      } catch (error) {
        state.storyAudioBase64 = "";
        toast(error.message || translate("Memoir.storyFlow.recordingFailed"));
      }
      render();
    });
    recorder.start();
    state.storyRecording = true;
    render();
  } catch {
    toast(translate("Memoir.storyFlow.microphoneUnavailable"));
  }
}

async function speakStoryQuestion(text) {
  state.storyAudioPlayer?.pause();
  try {
    const generated = await storyApi("/v1/story/question-audio", { method: "POST", body: JSON.stringify({ text, language: conversationLanguage(), voice: "marin" }) });
    const player = new Audio(URL.createObjectURL(base64ToBlob(generated.audio_base64, generated.mime_type)));
    state.storyAudioPlayer = player;
    player.onended = () => URL.revokeObjectURL(player.src);
    await player.play();
  } catch (error) {
    if (error.status !== 503) toast(error.message);
    if (!window.speechSynthesis) return toast(translate("Memoir.storyFlow.readAloudUnavailable"));
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = currentUiLocale();
    utterance.rate = 0.96;
    window.speechSynthesis.speak(utterance);
  }
}

function base64ToBlob(value, mimeType = "application/octet-stream") {
  const bytes = Uint8Array.from(atob(value), (char) => char.charCodeAt(0));
  return new Blob([bytes], { type: mimeType });
}

async function linkStoryIdentity(provider) {
  if (!state.supabase?.client) return toast(translate("Errors.supabaseNotConfigured"));
  const { error } = await linkSocialIdentity(
    state.supabase.client.auth, provider, `${window.location.origin}${MEMOIR_ROUTES.start}`,
  );
  if (error) toast(translate("Errors.identityLinkFailed"));
}

async function claimFreeChapter() {
  if (state.loading) return;
  state.loading = true;
  try {
    const result = await storyApi("/v1/story/free-chapter", { method: "POST" });
    state.story = result;
    state.storyChapter = result.chapter;
  } catch (error) {
    toast(error.message);
  } finally {
    state.loading = false;
    render();
  }
}

async function requestStoryCheckout() {
  if (state.loading) return;
  const selectedPlan = $("input[name='plan_key']:checked")?.value || state.selectedStoryPlan || "electronic_memoir_v1";
  const plan = (state.storyPlans.length ? state.storyPlans : FALLBACK_STORY_PLANS).find((item) => item.plan_key === selectedPlan);
  const bookCount = plan?.electronic_only ? 0 : (Number($("#story-book-count")?.value) || state.storyBookCount || 2);
  state.selectedStoryPlan = selectedPlan;
  state.storyBookCount = bookCount || 2;
  try {
    sessionStorage.setItem("memoir-package-choice", JSON.stringify({ plan: selectedPlan, books: state.storyBookCount }));
  } catch { /* The current selection remains usable without browser storage. */ }
  if (state.supabase?.user?.is_anonymous) {
    authReminder.open();
    return;
  }
  state.loading = true;
  try {
    state.checkout = await storyApi("/v1/story/checkout", {
      method: "POST",
      body: JSON.stringify({ plan_key: selectedPlan, book_count: bookCount }),
    });
    if (state.checkout.checkout_url) {
      window.location.assign(state.checkout.checkout_url);
      return;
    }
  } catch (error) {
    toast(error.message);
  } finally {
    state.loading = false;
    render();
  }
}

async function generateFullMemoir() {
  await reviewCollection();
}

function render() {
  if (!state.project) { conversationScroll.mount(null); disposeCesiumPlaceJourney(); return renderLanding(); }
  renderStory();
}

function renderLanding() {
  if (currentPath() === "/") return renderPlatformLanding();
  return renderMemoirLanding();
}

function renderPlatformLanding() {
  const t = (key) => escapeHtml(translate(`Platform.${key}`));
  $("#app").innerHTML = `
    <div class="platform-landing">
      <header class="landing-header platform-header">
        <a class="brand" href="/" aria-label="${t("homeAria")}"><img class="brand-mark" src="/static/copyme2_icon_light.png" alt="" aria-hidden="true" /><span class="brand-name">${t("brand")}</span></a>
        <div class="landing-language" data-language-switcher-slot></div>
      </header>
      <main class="platform-main">
        <section class="platform-hero">
          <div class="eyebrow">${t("eyebrow")}</div>
          <h1>${t("title")}</h1>
          <p class="platform-reflection">${t("reflection")}</p>
        </section>
        <section class="platform-products" aria-label="${t("products")}">
          <article class="product-card product-card-primary">
            <div class="product-kicker">${t("memoirKicker")}</div>
            <h2>${t("memoirTitle")}</h2>
            <p>${t("memoirBody")}</p>
            <div class="product-card-actions">
              <button class="button button-primary" data-action="open-memoir">${t("begin")} <span>↗</span></button>
            </div>
          </article>
          <article class="product-card product-card-muted">
            <div class="product-kicker">${t("diaryKicker")}</div>
            <h2>${t("diaryTitle")}</h2>
            <p>${t("diaryBody")}</p>
            <span class="product-status">${t("comingStatus")}</span>
          </article>
        </section>
      </main>
    </div>`;
  $("[data-action='open-memoir']")?.addEventListener("click", () => startStory("self"));
}

function renderMemoirLanding() {
  const t = (key) => escapeHtml(translate(`Memoir.landing.${key}`));
  $("#app").innerHTML = `
    <div class="landing">
      <header class="landing-header">
        <a class="brand" href="/memoir" aria-label="${t("brand")} home"><img class="brand-mark" src="/static/copyme2_icon_light.png" alt="" aria-hidden="true" /><span class="brand-name">${t("brand")}</span></a>
        <div class="landing-language" data-language-switcher-slot></div>
      </header>
      <main class="landing-main">
        <section class="hero">
          <div>
            <div class="eyebrow">${t("eyebrow")}</div>
            <h1>${t("title")}</h1>
            <p class="hero-copy">${t("description")}</p>
            <div class="hero-actions"><button class="button button-primary" data-action="start-story" data-mode="self">${t("startButton")} <span>↗</span></button><button class="button button-secondary" data-action="start-story" data-mode="family">${t("familyButton")}</button></div>
            <p class="fine-print" style="margin-top:16px">${t("freeNotice")}</p>
          </div>
          <div class="hero-art" aria-hidden="true"><div class="orb"></div><div class="memory-card"><div class="card-kicker"><span>${t("cardLabel")}</span><span>${t("cardStatus")}</span></div><blockquote>“${t("quote")}"</blockquote><div class="card-line"></div><div class="card-meta"><span>${t("cardMeta")}</span><span>♡</span></div></div></div>
        </section>
        <details class="agent-connect">
          <summary>${t("connectSummary")}</summary>
          <p>${t("connectDescription")}</p>
          <form id="agent-auth-form">
            <input id="agent-email" type="email" autocomplete="email" placeholder="${t("emailPlaceholder")}" aria-label="${t("emailLabel")}" />
            <input id="agent-password" type="password" autocomplete="current-password" placeholder="${t("passwordPlaceholder")}" aria-label="${t("passwordLabel")}" />
            <div class="agent-auth-actions"><button type="button" class="button button-primary button-small" data-auth-action="signin">${t("signIn")}</button><button type="button" class="button button-secondary button-small" data-auth-action="signup">${t("createAccount")}</button></div>
          </form>
          <small>${state.supabase?.accessToken ? t("connected") : t("required")}</small>
        </details>
        <section class="feature-row"><article class="feature"><div class="feature-icon">◌</div><h3>${t("featureTalkTitle")}</h3><p>${t("featureTalkBody")}</p></article><article class="feature"><div class="feature-icon">⌁</div><h3>${t("featureContextTitle")}</h3><p>${t("featureContextBody")}</p></article><article class="feature"><div class="feature-icon">▱</div><h3>${t("featureWorkspaceTitle")}</h3><p>${t("featureWorkspaceBody")}</p></article></section>
      </main>
    </div>`;
  document.querySelectorAll('[data-action="start-story"]').forEach((button) => button.addEventListener("click", () => startStory(button.dataset.mode || "self")));
  document.querySelectorAll("[data-auth-action]").forEach((button) => button.addEventListener("click", () => supabaseAuth(button.dataset.authAction)));
}

async function startStory(mode = "self") {
  await startMemoirStory(mode);
}

async function startMemoirStory(mode = "self") {
  try {
    stopVoiceMode({ silent: true });
    if (state.authPromise) await state.authPromise;
    if (state.loading) return;
    state.loading = true;
    const language = conversationLanguage();
    state.project = await api("/v1/projects", { method: "POST", body: JSON.stringify({ mode, language }) });
    state.recallPreview = null;
    if (state.supabase?.user && !state.supabase.user.is_anonymous) {
      const savedProfile = await storyApi("/v1/user/profile");
      state.project.profile = { ...state.project.profile, ...savedProfile };
    }
    localStorage.setItem("memory-spark-project", state.project.id);
    state.chat = [];
    state.chatHistoryCollapsed = false;
    state.freshAnonymousSession = Boolean(state.supabase?.user?.is_anonymous);
    state.codexStarting = false;
    state.codexReady = false;
    state.profileIntakePending = true;
    state.placeJourney = null;
    state.placeJourneyChange = null;
    try { localStorage.removeItem(PLACE_JOURNEY_PROJECT_STORAGE_KEY); } catch { /* private browsing */ }
    state.workspaceTab = "memoir";
    state.workspaceCollapsed = false;
    state.compositionStage = 0;
    state.lifeStage = "childhood";
    state.story = null;
    localStorage.removeItem("memory-spark-story-started");
    state.loading = false;
    navigateTo(`${MEMOIR_ROUTES.interview}/${state.project.id}`, true);

    // The opening message is fixed product copy and can stream immediately.
    // Consent and project hydration are independent setup work; keep them out
    // of the first-paint path so a slow request cannot hide the conversation.
    const backgroundSetup = Promise.all([
      api(`/v1/projects/${state.project.id}/consents`, { method: "POST", body: JSON.stringify({ purpose: "recording", granted: true, locale: currentUiLocale() }) }),
      ...(mode === "self" ? [api(`/v1/projects/${state.project.id}/consents`, { method: "POST", body: JSON.stringify({ purpose: "storyteller_assent", granted: true, locale: currentUiLocale() }) })] : []),
      refreshProject(),
      refreshFamilyEntitlement(),
    ]).catch((error) => {
      toast(error.message);
    });
    await startCodexConversation();
    await backgroundSetup;
  } catch (error) {
    state.project = null;
    setLoading(false);
    toast(error.message);
  }
}

async function refreshProject() {
  const projectId = state.project.id;
  const ownerId = state.supabase?.user?.id;
  state.stageReadiness = {};
  state.privateDraft = null;
  const base = await api(`/v1/projects/${projectId}`);
  const journey = await api(`/v1/projects/${projectId}/journey`);
  if (state.project?.id !== projectId || state.supabase?.user?.id !== ownerId) return;
  state.project = { ...base, ...journey, profile: preserveConversationLocale(base.profile, state.project.profile) };
  if (state.supabase?.accessToken) {
    const savedProfile = await storyApi("/v1/user/profile");
    if (state.project?.id !== projectId || state.supabase?.user?.id !== ownerId) return;
    state.project.profile = preserveConversationLocale({ ...state.project.profile, ...savedProfile,
      memory_places: mergePlaces([...(savedProfile.memory_places || []), ...(state.project.profile?.memory_places || [])]) }, state.project.profile);
  }
  state.session = journey.active_session;
  state.preview = state.project.preview || null;
  const parsedCompositionStage = Number(state.project.composition_stage ?? state.project.memoir_stage ?? 0);
  state.compositionStage = Math.max(state.compositionStage, Number.isFinite(parsedCompositionStage) ? parsedCompositionStage : 0);
  const workspaceReady = Boolean(state.workspaceUnlocked || state.project.workspace_unlocked || state.compositionStage >= 3);
  state.workspaceUnlocked = workspaceReady;
  if (workspaceReady) {
    const [memories, sources, chapters, people, relationships, timeline] = await Promise.all([
      api(`/v1/projects/${projectId}/memories`),
      api(`/v1/projects/${projectId}/sources`),
      loadAllChapters(projectId),
      api(`/v1/projects/${projectId}/people`),
      api(`/v1/projects/${projectId}/relationships`),
      api(`/v1/projects/${projectId}/timeline`),
    ]);
    state.memories = memories.items;
    state.sources = sources.items;
    state.chapters = chapters;
    state.people = people.items;
    state.relationships = relationships.items;
    state.timeline = timeline.items;
    if (state.familyFeaturesEnabled) await refreshFamilyContext();
  }
  void refreshStageReadiness();
  void refreshPrivateDraft();
}

function normalizeHistoryOpening(messages) {
  if (!messages.length) return messages;
  const normalize = text => text.replace(/\s+/g, " ").trim();
  const openings = new Set(openingMessages.map(normalize));
  const isOpening = message => message.role === "assistant" && openings.has(normalize(message.text));
  const opening = messages.find(isOpening) || {
    id: "history-opening", role: "assistant", text: conversationMessage("opening"),
  };
  return [opening, ...messages.filter(message => !isOpening(message))];
}

async function hydrateAccountHistory() {
  const user = state.supabase?.user;
  const projectId = state.project?.id;
  if (!user || user.is_anonymous || !projectId) return;
  const { items } = await storyApi("/v1/user/conversations");
  if (state.supabase?.user?.id !== user.id || state.project?.id !== projectId) return;
  const messages = [...items].sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""))
    .flatMap(item => item.messages.map((message, index) => ({
      id: `history-${item.id}-${index}`, role: message.role,
      text: message.role === "assistant" ? cleanAssistantText(message.text) : originalConversationText(message.text),
    })));
  // Local entries can mirror saved turns or the freshly attached guest chat.
  // Consume matching occurrences so repeated memories in server history remain.
  const signature = message => JSON.stringify([message.role, message.text]);
  const saved = new Map();
  for (const message of messages) {
    const key = signature(message);
    saved.set(key, [...(saved.get(key) || []), message]);
  }
  for (const local of state.chat) {
    const message = local.role === "user" ? { ...local, text: originalConversationText(local.text) } : local;
    const key = signature(message);
    const matching = saved.get(key)?.shift();
    if (matching && Array.isArray(message.trace)) {
      matching.trace = message.trace;
      matching.traceMode = message.traceMode;
    } else if (!matching) messages.push(message);
  }
  state.chat = normalizeHistoryOpening(messages);
  persistChatHistory();
}

function renderStory() {
  const hadRecallPrompt = Boolean($(".recall-package-prompt"));
  const previousScene = $(".place-journey-scene");
  const previousMap = previousScene?.querySelector("[data-cesium-place]");
  const previousScroll = $("#chat-scroll");
  const previousTop = previousScroll?.scrollTop || 0;
  const previousGallery = $(".place-pictures[data-photo-place]");
  const galleryTop = previousGallery?.scrollTop || 0;
  const galleryPlace = previousGallery?.dataset.photoPlace;
  const followConversation = !previousScroll || conversationScroll.following();
  const composer = $("#chat-input");
  const draft = composer?.value;
  const composerFocused = composer && document.activeElement === composer;
  const selection = composerFocused ? [composer.selectionStart, composer.selectionEnd] : null;

  const t = (key) => escapeHtml(translate(`Memoir.story.${key}`));
  const storyText = (key, values = {}) => escapeHtml(translateWith(`Memoir.story.${key}`, values));
  const unlocked = state.workspaceUnlocked || state.project.workspace_unlocked || state.compositionStage >= 3;
  const workspaceVisible = workspaceIsVisible();
  const workspaceAvailable = workspaceHasContent();
  const contextOnly = workspaceVisible && !unlocked;
  const baseShellClass = workspaceVisible ? (contextOnly ? "context-visible" : "workspace-visible") : "conversation-only";
  const shellClass = `${baseShellClass}${!workspaceVisible && workspaceAvailable ? " workspace-collapsed" : ""}`;
  const chatClass = "chat-main";
  const historyToggleLabel = t(state.chatHistoryCollapsed ? "showHistory" : "hideHistory");
  const historyToggle = !isFreshAnonymousSession() && state.chat.length
    ? `<button type="button" class="button button-secondary button-small chat-history-toggle" data-action="toggle-chat-history" aria-expanded="${!state.chatHistoryCollapsed}" aria-controls="chat-history">${historyToggleLabel}</button>`
    : "";
  const headerActions = !isFreshAnonymousSession()
    ? `<div class="chat-heading-actions"><span class="chapter-chip">${unlocked ? storyText("chapterLabel", { number: state.chapters.length || 1 }) : t("beforeChapter")}</span>${historyToggle}</div>`
    : "";
  activeWorkspaceTab();
  $("#app").innerHTML = `
    <div class="story-shell ${shellClass}">
      <header class="story-topbar">
        <a class="brand" href="#" data-action="story-home"><img class="brand-mark" src="/static/copyme2_icon_light.png" alt="" aria-hidden="true" /><span class="brand-name">${t("brand")}</span></a>
        <div class="story-topbar-actions"><div class="story-status"><span class="topbar-hint">${t("voiceAvailable")}</span></div>${profileMenu()}</div>
      </header>
      <div class="conversation-layout">
        <main class="${chatClass}" aria-label="${t("mainLabel")}">
          <div id="chat-scroll" class="chat-scroll" tabindex="0" role="region" aria-label="${t("historyRegion")}"><div class="chat-heading"><div>${unlocked ? `<div class="eyebrow">${t("workspaceEyebrow")}</div>` : ""}<h1>${t(unlocked ? "workspaceTitle" : "conversationTitle")}</h1><p>${t(unlocked ? "workspaceDescription" : "conversationDescription")}</p></div>${headerActions}</div><div id="chat-history" class="chat-history"${state.chatHistoryCollapsed ? " hidden" : ""}>${state.chat.map(renderMessage).join("")}</div>${state.loading && !state.chat.at(-1)?.streaming ? `<div class="thinking" role="status"><em>${state.supabase?.accessToken ? t("thinkingCodex") : t("thinkingSimulated")}</em></div>` : ""}${placeJourneySurface()}${recallPackagePrompt()}</div>
          ${chatComposer()}
        </main>
        ${workspaceAvailable ? workspaceDetail() : ""}
      </div>
    </div>`;
  bindViewActions();
  bindProfileMenu();
  const nextMap = $("[data-cesium-place]");
  if (previousMap && nextMap && JSON.stringify(previousMap.dataset) === JSON.stringify(nextMap.dataset)) {
    nextMap.closest(".place-journey-scene").replaceWith(previousScene);
    cesiumPlaceJourneyViewer?.resize();
  } else {
    disposeCesiumPlaceJourney();
    initCesiumPlaceJourney();
  }
  initFamilyVisualizations();
  const nextGallery = $(".place-pictures[data-photo-place]");
  if (nextGallery && nextGallery.dataset.photoPlace === galleryPlace) nextGallery.scrollTop = galleryTop;
  bindPhotoPagination();
  const scroll = $("#chat-scroll");
  if (draft !== undefined && $("#chat-input")) {
    $("#chat-input").value = draft;
  }
  authReminder.mount();
  resizeChatInput($("#chat-input"));
  if (scroll) {
    const recallPrompt = $(".recall-package-prompt");
    scroll.scrollTop = recallPrompt
      ? (hadRecallPrompt ? previousTop : recallPrompt.getBoundingClientRect().top - scroll.getBoundingClientRect().top)
      : followConversation ? scroll.scrollHeight : previousTop;
    if (recallPrompt || !followConversation) conversationScroll.pause();
    else conversationScroll.follow();
    conversationScroll.mount(scroll);
  }
  if (composerFocused && $("#chat-input")) {
    $("#chat-input").focus({ preventScroll: true });
    $("#chat-input").setSelectionRange(...selection);
  }
  persistChatHistory();
}

function workspaceContentAvailable() {
  // Public cue metadata belongs in the conversation until a current place cue
  // activates the place journey. Counting it here creates an empty Places /
  // Pictures workspace and hides the cue cards that should remain inline.
  return Boolean(workspaceTabs().length || state.privateDraft?.preview || state.privateDraft?.updating || state.privateDraft?.error || placeMapTarget(placeWorkspaceSelection() || state.placeJourney));
}

function workspaceHasContent() {
  // Async map, grouping, and photo updates can briefly make the selected
  // target unavailable. Keep the mounted workspace stable until that gap
  // persists, otherwise the Cesium flight is destroyed and restarted.
  const projectId = state.project?.id || null;
  if (workspaceVisibility.projectId !== projectId) {
    if (workspaceVisibility.timer) clearTimeout(workspaceVisibility.timer);
    workspaceVisibility.projectId = projectId;
    workspaceVisibility.stable = false;
    workspaceVisibility.pending = null;
    workspaceVisibility.timer = null;
  }
  const available = workspaceContentAvailable();
  if (available) {
    if (workspaceVisibility.timer) clearTimeout(workspaceVisibility.timer);
    workspaceVisibility.stable = true;
    workspaceVisibility.pending = null;
    workspaceVisibility.timer = null;
    return true;
  }
  if (!workspaceVisibility.stable) return false;
  if (workspaceVisibility.pending !== false) {
    if (workspaceVisibility.timer) clearTimeout(workspaceVisibility.timer);
    workspaceVisibility.pending = false;
    workspaceVisibility.timer = setTimeout(() => {
      workspaceVisibility.timer = null;
      workspaceVisibility.pending = null;
      if (workspaceVisibility.projectId !== projectId) return;
      if (workspaceContentAvailable()) return;
      workspaceVisibility.stable = false;
      render();
    }, WORKSPACE_VISIBILITY_DEBOUNCE_MS);
  }
  return true;
}

function workspaceDetail() {
  const t = (key) => escapeHtml(translate(`Memoir.workspace.${key}`));
  const expanded = workspaceIsVisible();
  const toggleLabel = t(expanded ? "collapseWorkspace" : "showWorkspace");
  const toggle = `<button type="button" class="workspace-toggle" data-action="toggle-workspace" aria-expanded="${expanded}" aria-controls="workspace-detail" aria-label="${toggleLabel}" title="${toggleLabel}"><span aria-hidden="true">${expanded ? "&gt;" : "&lt;"}</span></button>`;
  if (!expanded) return `<aside id="workspace-detail" class="workspace-detail is-collapsed" aria-label="${t("yourWorkspace")}"><div class="workspace-detail-top">${toggle}</div></aside>`;
  const tabs = workspaceTabs();
  const active = tabs.length ? activeWorkspaceTab() : null;
  const title = tabs.find(([key]) => key === active)?.[1] || t("workspace");
  const content = active === "family"
    ? familyWorkspace()
    : active === "timeline"
      ? timelineWorkspace()
      : active === "memoir"
        ? memoirWorkspace()
        : "";
  const tabsMarkup = tabs.length
    ? `<nav class="workspace-detail-tabs" aria-label="${t("workspaceViews")}">${tabs.map(([key, label]) => `<button class="workspace-detail-tab ${active === key ? "active" : ""}" aria-current="${active === key ? "page" : "false"}" data-workspace-tab="${key}">${escapeHtml(label)}</button>`).join("")}</nav>`
    : "";
  const contentMarkup = content ? `${tabsMarkup}${content}` : tabsMarkup;
  const composing = composingWorkspaceActive();
  const mediaOverview = composing ? "" : workspaceMediaOverview(toggle);
  const workspaceHeader = mediaOverview ? "" : `<div class="workspace-detail-top">${toggle}</div>`;
  const ariaLabel = tabs.length
    ? `${escapeHtml(title)} ${t("workspaceSuffix")}`
    : state.placeJourney ? `${t("places")} ${t("workspaceSuffix")}` : t("yourWorkspace");
  return `<aside id="workspace-detail" class="workspace-detail" aria-label="${ariaLabel}">${workspaceHeader}${mediaOverview}${contentMarkup}${!composing && (state.placeJourney || state.privateDraft) ? lifeStageNavigator() : ""}${active === "memoir" ? "" : privateDraftPreview()}</aside>`;
}

let privateDraftTimer = null;
async function refreshPrivateDraft() {
  if (privateDraftTimer) clearTimeout(privateDraftTimer);
  const projectId=state.project?.id, owner=state.supabase?.user?.id;
  if (!projectId || !state.supabase?.accessToken) return;
  try {
    const result=await storyApi(`/v1/story/private-draft?project_id=${encodeURIComponent(projectId)}&language=${encodeURIComponent(profile().preferred_language || currentUiLocale())}`);
    if (state.project?.id!==projectId || state.supabase?.user?.id!==owner) return;
    state.privateDraft=result;
    render();
    if (result.updating) privateDraftTimer=setTimeout(refreshPrivateDraft,15000);
  } catch (_) { /* Quiet background work never hides a saved interview. */ }
}

async function retryPrivateDraft() {
  await storyApi('/v1/story/private-draft/retry',{method:'POST',body:JSON.stringify({
    project_id:state.project.id,language:profile().preferred_language || currentUiLocale()})});
  await refreshPrivateDraft();
}

function privateDraftPreview() {
  const saved=state.privateDraft;
  if (!saved || !saved.preview && !saved.updating && !saved.error) return "";
  const t=(key,values={})=>escapeHtml(translateWith(`Memoir.workspace.${key}`,values));
  const preview=saved.preview;
  const status=[preview ? t('privateDraftSaved',{round:saved.covered_round ?? saved.milestone}) : "", saved.updating ? t('privateDraftUpdating') : saved.error ? t('privateDraftBlocked') : ""].filter(Boolean).join(" ");
  return `<section class="private-draft-status"><p>${status}</p>${preview ? `<details><summary>${t('readSavedDraft')}</summary><h3>${escapeHtml(preview.title)}</h3>${formatText(preview.text)}</details>` : ""}${saved.error && !saved.updating ? `<button type="button" class="button button-secondary button-small" data-action="retry-private-draft">${t('retryPrivateDraft')}</button>` : ""}</section>`;
}

function workspaceProgressSummary() {
  const t = (key, values = {}) => escapeHtml(translateWith(`Memoir.workspace.${key}`, values));
  const answers = state.chat.filter((message) => message.role === "user" && message.text && message.text !== "Voice answer");
  const latest = answers.at(-1)?.text || translate("Memoir.workspace.firstChapterEmpty");
  const sourceCount = state.sources.length + searchedPictures().length;
  const signals = [
    answers.length ? t(answers.length === 1 ? "memorySingular" : "memoryPlural", { count: answers.length }) : t("conversationBeginning"),
    state.placeJourney ? t("placeContextAdded") : null,
    sourceCount ? t(sourceCount === 1 ? "sourceSingular" : "sourcePlural", { count: sourceCount }) : null,
  ].filter(Boolean);
  return `<section class="workspace-progress-summary" aria-live="polite"><div><span class="eyebrow">${t("storySoFar")}</span><strong>${signals.join(" · ")}</strong></div><p>${escapeHtml(latest.length > 180 ? `${latest.slice(0, 177)}…` : latest)}</p></section>`;
}

function searchedPictures() {
  const items = [];
  const seen = new Set();
  for (const message of state.chat) {
    for (const cue of message.cues || []) {
      const key = cue.asset_id || cue.id || cue.source_url || cue.title;
      if (!key || seen.has(key)) continue;
      seen.add(key);
      items.push(cue);
    }
  }
  return items;
}


function placeHistoryChoices(places, current) {
  if (places.length < 2) return "";
  const label = escapeHtml(translate("Memoir.workspace.placeHistory"));
  return `<nav class="place-choices" aria-label="${label}">${places.map(item => {
    const context = (item.hierarchy || []).filter(part => part !== "Earth" && part !== item.place).join(" · ");
    const stage = (item.life_stages || [item.life_stage]).filter(Boolean).map(stage => lifeStageText(stage, "label")).join(" · ");
    const selected = placeHistoryKey(item) === placeHistoryKey(current) || item.group_members?.includes(placeHistoryKey(current));
    return `<button type="button" data-place-choice="${escapeHtml(placeHistoryKey(item))}" aria-pressed="${selected}"><span>${escapeHtml(item.place)}</span><small>${escapeHtml([context, stage].filter(Boolean).join(" · "))}</small></button>`;
  }).join("")}</nav>`;
}

function placeWorkspaceSelection() {
  if (!state.placeJourney) return null;
  if (state.placeJourney.preview && state.selectedPlace === placeHistoryKey(state.placeJourney)) {
    return placeMapTarget(state.placeJourney) ? state.placeJourney : null;
  }
  const places = mergePlaces(profile().memory_places || []);
  const matching = state.lifeStage === "all"
    ? places
    : places.filter(item => matchesPlaceStage(item, state.lifeStage));
  const explicitlySelected = state.selectedPlace
    ? matching.find(item => placeHistoryKey(item) === state.selectedPlace)
    : null;
  if (explicitlySelected) return placeMapTarget(explicitlySelected) ? explicitlySelected : null;
  if (state.selectedPlace) {
    const group = workspacePlaceGroups(matching).find(item => placeHistoryKey(item.city) === state.selectedPlace);
    const member = group?.members.find(item => placeMapTarget(item));
    if (member) return member;
  }
  const current = matching.find(item => placeHistoryKey(item) === placeHistoryKey(state.placeJourney));
  if (current) return placeMapTarget(current) ? current : null;
  const selected = matching.filter((item) => placeMapTarget(item));
  if (selected.length) {
    return selected.at(-1);
  }
  return placeMapTarget(state.placeJourney) ? state.placeJourney : null;
}

function placeMapTarget(journey) {
  if (!journey) return null;
  const key = placeHistoryKey(journey);
  return mapTarget(journey, [])
    || resolvedPlaceTargets.get(key)
    || mapTarget(journey, mergePlaces(profile().memory_places || []));
}

function renderablePictureItems(pictures = []) {
  return pictures.filter((picture) => picture.allowed_actions?.embed);
}

function workspacePictureItems(place, group = null) {
  const period = photoSearchPeriod(place, profile().story_focus);
  const matchesPeriod = source => !source || !Object.hasOwn(source, "photo_search_period") || source.photo_search_period === period;
  const eligible = pictures => renderablePictureItems(pictures).filter(picture => photoMatchesScope(picture, place, profile().story_focus));
  let pictures = matchesPeriod(place) ? eligible(place?.pictures || []) : [];
  if (!pictures.length && group) {
    // Grouping changes the map, while photographs remain attached to their
    // source. Keep the city's saved references visible during a child search.
    const members = group.members.filter(member => placeHistoryKey(member) !== placeHistoryKey(place));
    const cityKey = placeHistoryKey(group.city);
    const ordered = [...members.filter(member => placeHistoryKey(member) === cityKey),
      ...members.filter(member => placeHistoryKey(member) !== cityKey)];
    const samePeriod = ordered.filter(member => matchesPeriod(member) && eligible(member.pictures).length);
    pictures = (samePeriod.length ? samePeriod : ordered).flatMap(member =>
      eligible(member.pictures).map(picture => ({...picture, reference_place: member.place})));
  }
  if (!pictures.length) pictures = eligible(place?.pictures || []);
  return mergePlacePictures([], [...pictures, ...searchedPictures()])
    .filter(picture => photoMatchesScope(picture, place, profile().story_focus));
}

function workspaceMediaOverview(toggle = "") {
  const t = (key) => escapeHtml(translate(`Memoir.workspace.${key}`));
  if (!state.placeJourney) return "";
  const current = placeWorkspaceSelection();
  if (!current || !placeMapTarget(current)) return "";
  const places = mergePlaces(profile().memory_places || []);
  const matching = state.lifeStage === "all" ? places : places.filter(item => matchesPlaceStage(item, state.lifeStage));
  const groups = workspacePlaceGroups(matching);
  const activeGroup = groups.find(group => group.members.some(member => placeHistoryKey(member) === placeHistoryKey(current)));
  const photoGroup = state.lifeStage === "all" ? activeGroup : workspacePlaceGroups(places)
    .find(group => group.members.some(member => placeHistoryKey(member) === placeHistoryKey(current)));
  const choices = placeHistoryChoices(groupChoices(groups), current);
  const map = current
    ? placeJourneyMarkup(current, "workspace", activeGroup)
    : `<div class="workspace-empty"><span>◎</span><p>${t("placesEmpty")}</p></div>`;
  const pictureItems = renderablePictureItems(workspacePictureItems(current, photoGroup));
  const requestKey = photoRequestKey(current);
  const request = state.photoRequests?.get(requestKey);
  const empty = request?.loading
    ? `<p class="workspace-photo-status is-loading" role="status">${t("picturesSearching")}</p>`
    : request?.error
      ? `<div class="workspace-photo-status"><p role="status">${t(request.failures?.some(failure => ["verification_required", "robots_denied", "http_403"].includes(failure.reason)) ? "picturesSourceBlocked" : "picturesUnavailable")}</p><button class="button button-secondary button-small" data-photo-retry="${escapeHtml(placeHistoryKey(current))}">${t("picturesSearchRetry")}</button></div>`
      : `<p class="workspace-photo-status" role="status">${t(Object.hasOwn(current, "photo_next_cursor") ? "picturesNoMatch" : "picturesEmpty")}</p>`;
  const gallery = `<div class="workspace-media-gallery"><div class="workspace-media-header workspace-media-gallery-header"><h2>${t("pictures")}</h2><p>${t("picturesIntro")}</p></div>${pictureItems.length ? pictureWall(pictureItems, current) : empty}</div>`;
  return `<section class="workspace-media-overview" aria-label="${t("placeJourney")}"><div class="workspace-media-map"><div class="workspace-media-header workspace-media-map-header"><div class="workspace-media-heading">${toggle}<div class="workspace-intro"><h2>${t("places")}</h2></div></div>${current && groups.length > 1 ? `<button class="text-button" data-all-places>${t("allPlaces")}</button>` : ""}</div>${choices}${map}</div>${gallery}</section>`;
}

function composingWorkspaceActive() {
  return Boolean(state.workspaceUnlocked || state.project?.workspace_unlocked || state.compositionStage >= 3);
}

function workspaceTabs() {
  const t = (key) => translate(`Memoir.workspace.${key}`);
  const premium = state.familyFeaturesEnabled ? [["family", t("family")], ["timeline", t("timeline")]] : [];
  return composingWorkspaceActive() ? [...premium, ["memoir", t("memoir")]]
    : premium.filter(([key]) => key === "timeline" ? state.timeline.length : state.people.length);
}

function activeWorkspaceTab() {
  const tabs = workspaceTabs();
  if (!tabs.length) return state.workspaceTab;
  if (!tabs.some(([key]) => key === state.workspaceTab)) state.workspaceTab = "memoir";
  return state.workspaceTab;
}

function workspaceIsVisible() {
  return !state.workspaceCollapsed && workspaceHasContent();
}

function lifeStageText(stageId, key) {
  return translate(`Memoir.workspace.lifeStages.${stageId}.${key}`);
}

function lifeStageEvidence(stageId) {
  const matchesStage = (item = {}) => {
    const metadata = item.metadata || item.meta || {};
    return [...(item.life_stages || []), item.life_stage, item.lifeStage, item.stage_id, item.stage, metadata.life_stage, metadata.stage_id]
      .some((value) => value === stageId);
  };
  return {
    memoryCount: state.memories.filter(matchesStage).length + (profile().memory_places || []).filter(matchesStage).length,
    pictureCount: [...state.sources, ...searchedPictures()].filter(matchesStage).length,
  };
}

function lifeStageIllustration(stage) {
  const asset = { baby: "baby", toddler: "toddler", childhood: "child", adolescence: "adolescent", young_adulthood: "young_adult", midlife: "middle_aged", later_life: "senior" }[stage.id];
  // Artwork is a presentation choice, not an inferred gender identity.
  const style = profile().avatar_style === "female" ? "female" : "male";
  return `<img src="/static/timeline_avatar_${asset}_${style}.png" alt="" aria-hidden="true" />`;
}

function lifeStageNavigator() {
  const t = (key, values = {}) => escapeHtml(translateWith(`Memoir.workspace.${key}`, values));
  const activeId = state.lifeStage;
  state.lifeStage = activeId;
  const tabs = LIFE_STAGES.map((stage) => {
    const stageEvidence = lifeStageEvidence(stage.id);
    const label = lifeStageText(stage.id, "label");
    const hasMemory = stageEvidence.memoryCount > 0;
    const context = state.stageReadiness[stage.id] || { percent: 0, color: "red", word_equivalents: 0 };
    const percent = Math.min(50, Math.max(0, Number(context.percent) || 0));
    const color = ["red", "amber", "green"].includes(context.color) ? context.color : "red";
    const description = translateWith("Memoir.workspace.contextReadiness", { stage: label, percent,
      words: Number(context.word_equivalents) || 0 });
    return `<button id="life-stage-${stage.id}" type="button" class="life-stage-tab${stage.id === activeId ? " active" : ""}${hasMemory ? " has-memory" : ""}" data-life-stage-tab="${stage.id}" aria-label="${escapeHtml(description)}" aria-pressed="${stage.id === activeId}" tabindex="${stage.id === activeId ? "0" : "-1"}" title="${escapeHtml(description)}"><span class="life-stage-readiness readiness-${color}" style="--readiness:${percent}%"><span class="life-stage-figure" data-stage="${stage.id}">${lifeStageIllustration(stage)}</span></span></button>`;
  }).join("");
  return `<section class="life-stage-navigator" aria-label="${t("lifeJourneyEyebrow")}"><div class="life-stage-tabs" role="group" aria-label="${t("lifeStageTabsLabel")}">${tabs}</div></section>`;
}

async function refreshStageReadiness() {
  const projectId = state.project?.id;
  const owner = state.supabase?.user?.id;
  if (!projectId || !state.supabase?.accessToken) return;
  try {
    const result = await storyApi(`/v1/story/readiness?project_id=${encodeURIComponent(projectId)}`);
    if (state.project?.id === projectId && state.supabase?.user?.id === owner) {
      state.stageReadiness = result.stages || {};
      render();
    }
  } catch (_) { /* Readiness is optional; keep the saved conversation usable. */ }
}

function selectLifeStage(stageId, focus = false) {
  if (!LIFE_STAGES.some((stage) => stage.id === stageId)) return;
  state.lifeStage = stageId;
  state.selectedPlace = null;
  render();
  if (focus) document.querySelector(`[data-life-stage-tab="${stageId}"]`)?.focus({ preventScroll: true });
}

function chapterSourceIds(chapter) {
  return chapter.source_memory_ids || chapter.source_ids || (chapter.source_refs || []).map((item) => item.source_id).filter(Boolean);
}

function chapterBlockMarkup(block) {
  const type = block?.type || "paragraph";
  if (type === "heading") return `<h4 class="chapter-block-heading">${escapeHtml(block.text || "")}</h4>`;
  if (type === "quote") return `<blockquote class="chapter-block-quote">${formatText(block.text || "")}</blockquote>`;
  if (type === "image") {
    const label = block.alt || translate("Memoir.workspace.personalSource");
    return `<figure class="chapter-photo-slot"><div role="img" aria-label="${escapeHtml(label)}">${escapeHtml(block.caption || label)}</div>${block.credit ? `<figcaption>${escapeHtml(block.credit)}</figcaption>` : ""}</figure>`;
  }
  return block.text ? `<p class="chapter-body-block">${formatText(block.text)}</p>` : "";
}

async function loadAllChapters(projectId) {
  const chapters = [];
  let cursor = null;
  do {
    const page = await api(`/v1/projects/${projectId}/chapters?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
    chapters.push(...page.items);
    cursor = page.next_cursor;
  } while (cursor);
  return chapters;
}

function memoirChapters() {
  const chapters = state.chapters.length ? state.chapters : state.storyChapter ? [state.storyChapter] : [];
  return [...chapters].sort((a, b) => (a.chapter_number || 0) - (b.chapter_number || 0));
}

function memoirChapterKey(chapter, index) {
  return `${state.project?.id || ""}:${chapter.id || `chapter-${index + 1}`}`;
}

function selectMemoirChapter(key) {
  if (!memoirChapters().some((chapter, index) => memoirChapterKey(chapter, index) === key)) return;
  state.selectedMemoirChapter = key;
  render();
  document.querySelector(".chapter-pagination [aria-current='page']")?.focus({ preventScroll: true });
}

function memoirWorkspace() {
  const t = (key, values = {}) => escapeHtml(translateWith(`Memoir.workspace.${key}`, values));
  const chapters = memoirChapters();
  let selected = chapters.findIndex((chapter, index) => memoirChapterKey(chapter, index) === state.selectedMemoirChapter);
  if (selected < 0) selected = 0;
  const chapter = chapters[selected];
  if (!chapter) return `<div class="workspace-scroll"><div class="workspace-intro"><h2>${t("memoir")}</h2></div><div class="workspace-empty"><span>✦</span><p>${t("firstChapterEmpty")}</p></div>${privateDraftPreview()}</div>`;
  state.selectedMemoirChapter = memoirChapterKey(chapter, selected);
  const button = (index, label, disabled = false) => `<button type="button" data-memoir-chapter="${escapeHtml(memoirChapterKey(chapters[index], index))}" ${disabled ? "disabled" : ""}>${label}</button>`;
  const pagination = `<nav class="chapter-pagination" aria-label="${t("chapterPagination")}">${button(Math.max(0, selected - 1), t("previousChapter"), selected === 0)}<div class="chapter-page-numbers">${chapters.map((item, index) => `<button type="button" data-memoir-chapter="${escapeHtml(memoirChapterKey(item, index))}" aria-current="${index === selected ? "page" : "false"}" aria-label="${t("chapterPage", { number: item.chapter_number || index + 1, title: item.title || "" })}" title="${escapeHtml(item.title || "")}">${item.chapter_number || index + 1}</button>`).join("")}</div>${button(Math.min(chapters.length - 1, selected + 1), t("nextChapter"), selected === chapters.length - 1)}</nav>`;
  const sourceIds = chapterSourceIds(chapter);
  const blocks = Array.isArray(chapter.blocks) ? chapter.blocks.map(chapterBlockMarkup).join("") : "";
  const body = blocks || (chapter.text ? `<div class="chapter-body-block">${formatText(chapter.text)}</div>` : `<p>${t("chapterContentPending")}</p>`);
  return `<div class="workspace-scroll memoir-workspace"><div class="workspace-intro"><h2>${t("memoir")}</h2><p>${t("chapterPosition", { current: selected + 1, total: chapters.length })}</p></div>${pagination}<article class="workspace-card chapter-card" data-chapter-id="${escapeHtml(chapter.id || `chapter-${selected + 1}`)}"><div class="card-topline"><span class="tag">${t("chapter")} ${chapter.chapter_number || selected + 1}</span></div><h3>${escapeHtml(chapter.title || `${t("chapter")} ${selected + 1}`)}</h3><div class="chapter-body">${body}</div>${sourceIds.length ? `<div class="source-pills">${sourcePills(sourceIds)}</div>` : ""}</article>${referencesWorkspace()}${privateDraftPreview()}</div>`;
}

function familyWorkspace() {
  const t = (key) => escapeHtml(translate(`Memoir.workspace.${key}`));
  const people = state.people.filter(person => person?.id && person?.name);
  const fallback = people.length ? `<div class="family-chart-fallback">${people.map(familyPersonCard).join("")}</div>` : `<div class="workspace-empty"><span>♧</span><p>${t("peopleEmpty")}</p></div>`;
  return `<div class="workspace-scroll family-workspace"><div class="workspace-intro"><div class="workspace-heading-row"><div><h2>${t("family")}</h2><p>${t("familyIntro")}</p></div><button class="button button-secondary button-small" data-action="add-person">${t("addPerson")}</button></div></div><div class="family-chart-adapter" data-renderer="family-chart" aria-label="${t("familyChart")}"><div class="family-chart-toolbar"><span class="eyebrow">${t("familyChart")}</span><div class="family-chart-controls" role="group" aria-label="${t("familyZoomControls")}"><button type="button" data-family-zoom="out" disabled aria-label="${t("familyZoomOut")}" title="${t("familyZoomOut")}">−</button><button type="button" data-family-zoom="in" disabled aria-label="${t("familyZoomIn")}" title="${t("familyZoomIn")}">+</button><button type="button" class="family-chart-fit" data-family-zoom="fit" disabled>${t("familyZoomFit")}</button></div></div>${fallback}</div><div id="family-person-detail" aria-live="polite">${familyPersonDetail()}</div><div class="reference-note">${t("familyReferenceNote")}</div>${referencesWorkspace()}</div>`;
}

function familyAuthor() {
  const normalize = value => String(value || "").normalize("NFKC").trim().replace(/\s+/g, " ").toLocaleLowerCase();
  const name = normalize(profile().name);
  const matches = name ? state.people.filter(person => [person.name, person.chinese_name, ...(person.aliases || [])].some(alias => normalize(alias) === name)) : [];
  if (matches.length) return matches.length === 1 ? matches[0] : null;
  const self = state.people.filter(person => ["self", "me", "author", "storyteller", "我", "本人", "作者"].includes(normalize(person.family_title)));
  return self.length === 1 ? self[0] : null;
}

function familyPersonCard(person) {
  if (!person) return "";
  const author = familyAuthor()?.id === person.id;
  const selected = state.selectedFamilyPerson?.projectId === state.project?.id && state.selectedFamilyPerson?.id === String(person.id);
  const label = translateWith("Memoir.workspace.familyPersonOpen", { name: person.name });
  return `<button type="button" class="card-inner family-person-card${author ? " is-author" : ""}" data-family-person="${escapeHtml(person.id)}" aria-label="${escapeHtml(label)}" aria-controls="family-person-detail" aria-pressed="${selected}">${familyPersonPortrait(person)}<strong>${escapeHtml(person.name)}</strong>${author ? `<span class="family-author-badge">${escapeHtml(translate("Memoir.workspace.familyAuthor"))}</span>` : `<small>${escapeHtml(person.family_title || "")}</small>`}</button>`;
}

function familyPhotoUrl(person) {
  try {
    const url = new URL(person.photo_url);
    return ["https:", "http:"].includes(url.protocol) ? url.href : "";
  } catch { return ""; }
}

function familyPersonPortrait(person) {
  const url = familyPhotoUrl(person);
  return `<span class="family-person-portrait" aria-hidden="true"><span>${escapeHtml(Array.from(person.name)[0] || "?")}</span>${url ? `<img src="${escapeHtml(url)}" alt="" referrerpolicy="no-referrer" data-family-portrait>` : ""}</span>`;
}

function familyPersonDetail() {
  const selected = state.selectedFamilyPerson;
  const person = selected?.projectId === state.project?.id && state.people.find(person => String(person.id) === selected.id);
  const t = (key, values = {}) => escapeHtml(translateWith(`Memoir.workspace.${key}`, values));
  if (!person) return `<p class="family-person-prompt">${t("familyPersonHint")}</p>`;
  const facts = [["familyPersonAliases", (person.aliases || []).join(" · ")], ["familyPersonBirth", person.birth_date_expression], ["familyPersonDeath", person.death_date_expression]]
    .filter(([, value]) => value).map(([label, value]) => `<div><dt>${t(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("");
  const task = state.familyPhotoTask?.projectId === selected.projectId && state.familyPhotoTask?.id === selected.id ? state.familyPhotoTask : null;
  const busy = state.familyPhotoTask?.busy;
  const hasPhoto = Boolean(person.photo_path || familyPhotoUrl(person));
  const controls = state.familyFeaturesEnabled && state.supabase?.accessToken ? `<div class="family-photo-editor"><div class="family-photo-actions"><input type="file" id="family-person-photo" accept="image/jpeg,image/png,image/webp" hidden><button type="button" class="button button-secondary button-small" data-family-photo-upload ${busy ? "disabled" : ""}>${t(hasPhoto ? "familyPhotoReplace" : "familyPhotoAdd")}</button>${hasPhoto ? `<button type="button" class="text-button" data-family-photo-remove ${busy ? "disabled" : ""}>${t("familyPhotoRemove")}</button>` : ""}</div><p class="family-photo-hint">${t("familyPhotoHint")}</p>${task?.message ? `<p class="family-photo-status${task.error ? " is-error" : ""}" role="${task.error ? "alert" : "status"}">${t(task.message)}</p>` : ""}</div>` : "";
  return `<section class="family-person-detail" aria-labelledby="family-person-name" aria-busy="${Boolean(task?.busy)}"><div class="family-person-heading">${familyPersonPortrait(person)}<div class="family-person-heading-text"><span class="eyebrow">${t("familyPersonIntroduction")}</span><h3 id="family-person-name" tabindex="-1">${escapeHtml(person.name)}</h3>${familyAuthor()?.id === person.id ? `<span class="family-author-badge">${t("familyAuthor")}</span>` : ""}</div><button type="button" class="text-button" data-family-person-close aria-label="${t("familyPersonClose")}">×</button></div>${controls}${person.introduction ? `<p class="family-person-introduction">${formatText(person.introduction)}</p>` : `<p class="family-person-introduction">${t("familyPersonIntroductionEmpty", { name: person.name })}</p>`}${facts ? `<dl class="family-person-facts">${facts}</dl>` : ""}</section>`;
}

function updateFamilyPersonViews() {
  const focused = document.activeElement;
  const focusSelector = focused?.matches("[data-family-photo-upload]") ? "[data-family-photo-upload]" : focused?.matches("[data-family-photo-remove]") ? "[data-family-photo-remove]" : null;
  document.querySelectorAll("[data-family-person]").forEach(button => {
    const person = state.people.find(item => String(item.id) === button.dataset.familyPerson);
    if (person) button.outerHTML = familyPersonCard(person);
  });
  const detail = document.querySelector("#family-person-detail");
  if (detail) detail.innerHTML = familyPersonDetail();
  if (focusSelector) document.querySelector(focusSelector)?.focus({ preventScroll: true });
}

async function saveFamilyPersonPhoto(file = null) {
  const selected = state.selectedFamilyPerson;
  const person = selected?.projectId === state.project?.id && state.people.find(item => String(item.id) === selected.id);
  if (!person || state.familyPhotoTask?.busy || !state.supabase?.accessToken || !state.familyFeaturesEnabled) return;
  const task = { ...selected, ownerId: state.supabase.user?.id, busy: false, message: null, error: false };
  state.familyPhotoTask = task;
  if (file && !["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
    task.message = "familyPhotoInvalidType";
    task.error = true;
    updateFamilyPersonViews();
    return;
  }
  if (file && (!file.size || file.size > 10 * 1024 * 1024)) {
    task.message = "familyPhotoTooLarge";
    task.error = true;
    updateFamilyPersonViews();
    return;
  }
  task.busy = true;
  task.message = file ? "familyPhotoSaving" : "familyPhotoRemoving";
  updateFamilyPersonViews();
  try {
    const result = await supabaseApi(`/v1/agent/family-context/${encodeURIComponent(task.projectId)}/people/${encodeURIComponent(task.id)}/photo`, file ? { method: "PUT", body: file, headers: { "Content-Type": file.type } } : { method: "DELETE" });
    if (state.project?.id !== task.projectId || state.supabase?.user?.id !== task.ownerId) return;
    if (!result?.person || String(result.person.id) !== task.id) throw new Error("Missing saved person");
    if (Number.isInteger(state.familyContext?.revision) && state.familyContext.revision > result.revision) {
      await refreshFamilyContext();
    } else {
      state.people = state.people.map(item => {
        if (String(item.id) !== task.id) return item;
        const { photo_path, photo_url, ...previous } = item;
        return { ...previous, ...result.person };
      });
      if (state.familyContext) state.familyContext = { ...state.familyContext, people: state.people, revision: result.revision };
    }
    task.message = file ? "familyPhotoSaved" : "familyPhotoRemoved";
  } catch {
    if (state.project?.id !== task.projectId || state.supabase?.user?.id !== task.ownerId) return;
    // Check the persisted result before allowing a retry after an uncertain save.
    await refreshFamilyContext();
    task.message = "familyPhotoFailed";
    task.error = true;
  } finally {
    task.busy = false;
    if (state.project?.id === task.projectId && state.supabase?.user?.id === task.ownerId) {
      updateFamilyPersonViews();
      if (state.selectedFamilyPerson?.id === task.id) document.querySelector("[data-family-photo-upload]")?.focus({ preventScroll: true });
    }
  }
}

function zoomFamilyChart(action) {
  const container = document.querySelector(".family-chart-adapter");
  const renderer = familyCharts.get(container);
  if (!renderer) return;
  if (action === "fit") renderer.chart.updateTree({ transition_time: 0, tree_position: "fit" });
  else renderer.f3.handlers.manualZoom({ amount: action === "in" ? 1.25 : 0.8, svg: renderer.chart.svg, transition_time: 0 });
}

function selectFamilyPerson(id) {
  if (!state.people.some(person => String(person.id) === String(id))) return;
  state.selectedFamilyPerson = { projectId: state.project?.id, id: String(id) };
  const detail = document.querySelector("#family-person-detail");
  if (detail) detail.innerHTML = familyPersonDetail();
  document.querySelectorAll("[data-family-person]").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.familyPerson === String(id))));
  document.querySelector("#family-person-name")?.focus({ preventScroll: true });
  detail?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function closeFamilyPerson() {
  const id = state.selectedFamilyPerson?.id;
  state.selectedFamilyPerson = null;
  const detail = document.querySelector("#family-person-detail");
  if (detail) detail.innerHTML = familyPersonDetail();
  document.querySelectorAll("[data-family-person]").forEach(button => {
    button.setAttribute("aria-pressed", "false");
    if (button.dataset.familyPerson === id) button.focus({ preventScroll: true });
  });
}

function timelineWorkspace() {
  const t = (key, values = {}) => escapeHtml(translateWith(`Memoir.workspace.${key}`, values));
  const items = state.timeline.length ? state.timeline.map((item) => {
    const period = item.kind === "period";
    const date = period ? item.start_expression : item.date_expression;
    const start = formatDateExpression(date, currentUiLocale()) || translate("Memoir.workspace.dateUnknown");
    let details;
    if (period) {
      const end = formatDateExpression(item.end_expression, currentUiLocale()) || translate("Memoir.workspace.dateUnknown");
      details = `${escapeHtml(start)} → ${escapeHtml(end)}`;
    } else {
      const precisionKey = { approximate: "precision.approximate", range: "precision.range", exact: "precision.exact", year: "precision.year", decade: "precision.decade", month: "precision.month", day: "precision.day", season: "precision.season", age: "precision.age" }[item.precision];
      const precision = precisionKey ? t("datePrecision", { precision: t(precisionKey) }) : t("dateUnknown");
      const place = item.place ? ` · ${item.place}` : "";
      details = `${escapeHtml(start)} · ${precision}${escapeHtml(place)}`;
    }
    const stage = item.life_stage ? (item.life_stage === "unplaced" ? t("unplacedStage") : escapeHtml(lifeStageText(item.life_stage,"label"))) : "";
    const edit = item.canonical && state.familyFeaturesEnabled ? `<button type="button" class="text-button" data-edit-memory-event="${escapeHtml(item.id)}">${t("editEventTags")}</button>` : "";
    const evidence = item.canonical && item.source_refs?.length ? `<details><summary>${t("eventOriginalEvidence")}</summary>${item.source_refs.map(ref => `<p>${escapeHtml(ref.quote || "")}</p>`).join("")}</details>` : "";
    return `<article class="timeline-row"><span class="timeline-dot"></span><div><strong>${escapeHtml(item.title)}</strong><small>${details}${stage ? ` · ${stage}` : ""}</small>${edit}${evidence}${state.memoryEventEdit?.id === item.id ? memoryEventEditForm() : ""}</div></article>`;
  }).join("") : `<div class="workspace-empty"><span>⌁</span><p>${t("momentsEmpty")}</p></div>`;
  return `<div class="workspace-scroll"><div class="workspace-intro"><div class="workspace-heading-row"><div><h2>${t("timeline")}</h2><p>${t("timelineIntro")}</p></div><button class="button button-secondary button-small" data-action="add-timeline">${t("addMoment")}</button></div></div><div class="vis-timeline-adapter" data-renderer="vis-timeline" aria-label="${t("timelineFallback")}"><div class="timeline-list">${items}</div></div>${referencesWorkspace()}</div>`;
}

function memoryEventEditForm() {
  const edit = state.memoryEventEdit;
  const t = key => escapeHtml(translate(`Memoir.workspace.${key}`));
  const field = (name,label,type="text") => `<label>${t(label)}<input id="event-${name}" name="${name}" type="${type}" value="${escapeHtml(edit[name] ?? "")}" ${type === "number" ? 'min="1" max="9999"' : 'maxlength="500"'} /></label>`;
  const stages = [...LIFE_STAGES.map(stage => [stage.id,lifeStageText(stage.id,"label")]),["unplaced",translate("Memoir.workspace.unplacedStage")]];
  const precisions = ["unknown","day","month","year","range","approximate","age","season"];
  return `<form id="memory-event-edit-form" class="memory-event-edit-form"><label>${t("eventLifeStage")}<select id="event-life-stage" name="life-stage">${stages.map(([id,label]) => `<option value="${id}"${edit["life-stage"] === id ? " selected" : ""}>${escapeHtml(label)}</option>`).join("")}</select></label>${field("date-expression","eventDateExpression")}<label>${t("eventDatePrecision")}<select id="event-date-precision" name="date-precision">${precisions.map(id => `<option value="${id}"${edit["date-precision"] === id ? " selected" : ""}>${id === "unknown" ? t("dateUnknown") : t(`precision.${id}`)}</option>`).join("")}</select></label>${field("year-start","eventYearStart","number")}${field("year-end","eventYearEnd","number")}<label>${t("eventCorrectionStatement")}<textarea id="event-correction-statement" name="correction-statement" required maxlength="2000">${escapeHtml(edit["correction-statement"] || "")}</textarea></label><button type="submit" class="button button-primary button-small">${t("saveEventTags")}</button><button type="button" class="text-button" data-action="cancel-event-edit">${t("cancelEventEdit")}</button></form>`;
}

function openMemoryEventEdit(id) {
  const event = state.timeline.find(item => item.id === id && item.canonical);
  if (!event || !state.familyFeaturesEnabled) return;
  state.memoryEventEdit = {id,revision:event.revision,"life-stage":event.life_stage,
    original:{life_stage:event.life_stage,temporal:{...event.temporal}},
    "date-expression":event.temporal?.expression || "unknown","date-precision":event.temporal?.precision || "unknown",
    "year-start":event.temporal?.year_start ?? "","year-end":event.temporal?.year_end ?? "","correction-statement":""};
  render();
  $("#event-life-stage")?.focus();
}

async function saveMemoryEventEdit(event) {
  event.preventDefault();
  const edit = state.memoryEventEdit;
  if (!edit || !state.familyFeaturesEnabled) return;
  const temporal = {expression:edit["date-expression"] || "unknown",precision:edit["date-precision"]};
  if (edit["year-start"] !== "") temporal.year_start = Number(edit["year-start"]);
  if (edit["year-end"] !== "") temporal.year_end = Number(edit["year-end"]);
  const patch = {};
  if (edit["life-stage"] !== edit.original.life_stage) patch.life_stage = edit["life-stage"];
  if (["expression","precision","year_start","year_end"].some(key => String(temporal[key] ?? "") !== String(edit.original.temporal[key] ?? ""))) patch.temporal = temporal;
  if (!Object.keys(patch).length) { state.memoryEventEdit = null; render(); return; }
  try {
    await storyApi(`/v1/story/events/${encodeURIComponent(state.project.id)}/${encodeURIComponent(edit.id)}`,{method:"PATCH",body:JSON.stringify({expected_revision:edit.revision,patch,statement:edit["correction-statement"]})});
    state.memoryEventEdit = null;
    await refreshFamilyContext();
    await refreshPrivateDraft();
  } catch (failure) {
    if (failure.status === 409) { state.memoryEventEdit = null; await refreshFamilyContext(); }
    toast(translate(`Memoir.workspace.${failure.status === 409 ? "eventRevisionConflict" : "eventCorrectionUnavailable"}`));
  }
}

function placeMapUrl(journey) {
  if (!Number.isFinite(journey?.latitude) || !Number.isFinite(journey?.longitude)) return "";
  const query = encodeURIComponent(`${journey.latitude},${journey.longitude}`);
  return `https://www.google.com/maps/search/?api=1&query=${query}`;
}

function placeMapViewHeight(journey, target = journey) {
  const granularity = target?.granularity
    || (target?.place === journey?.place ? journey?.granularity : "city");
  return PLACE_MAP_VIEW_HEIGHTS[granularity] || PLACE_MAP_VIEW_HEIGHTS.city;
}

function placeJourneyMarkup(journey, variant = "surface", group = null) {
  if (!journey) return "";
  const t = (key) => escapeHtml(translate(`Memoir.workspace.${key}`));
  const tWith = (key, values) => escapeHtml(translateWith(`Memoir.workspace.${key}`, values));
  const title = group?.city || journey;
  const target = group ? groupMapFrame(group, placeMapTarget(group.city) || placeMapTarget(journey)) : placeMapTarget(journey);
  if (!target) return "";
  const mapUrl = placeMapUrl(target);
  const mapLink = mapUrl ? `<a class="place-map-link" href="${escapeHtml(mapUrl)}" target="_blank" rel="noreferrer">${t("exploreMap")} <span aria-hidden="true">↗</span></a>` : "";
  const latitude = Number.isFinite(target?.latitude) ? target.latitude : "";
  const longitude = Number.isFinite(target?.longitude) ? target.longitude : "";
  const duration = Number(journey.duration_ms) || 5200;
  const placeType = currentUiLocale() === "zh-CN"
    ? ({ city: "城市", town: "城镇", region: "地区", country: "国家", neighbourhood: "街区" }[journey.granularity] || "地点")
    : (journey.granularity || "place");
  const pins = target.pins || [];
  const pinData = group ? ` data-cesium-pins="${escapeHtml(JSON.stringify(pins))}" data-cesium-height="${target.height || ""}"` : "";
  const legend = group && group.members.length > 1 ? `<ul class="place-map-pins">${group.members.filter(member => placeHistoryKey(member) !== placeHistoryKey(group.city)).map(member => `<li><span class="place-pin-dot" aria-hidden="true">●</span>${escapeHtml(member.place)}${pins.some(pin => pin.key === placeHistoryKey(member)) ? "" : `<small>${t("pinUnresolved")}</small>`}</li>`).join("")}</ul>` : "";
  return `<section class="place-journey-card place-journey-${variant}" aria-label="${t("placeJourney")}"><div class="place-journey-heading"><h2>${escapeHtml(title.place)}</h2></div><div class="place-journey-scene" style="--journey-duration:${duration}ms"><div class="cesium-place-journey" data-place-key="${escapeHtml(group ? group.key : placeHistoryKey(journey))}" data-cesium-place="${escapeHtml(target.place || journey.place)}" data-cesium-latitude="${latitude}" data-cesium-longitude="${longitude}" data-cesium-duration="${duration}"${pinData}></div><div class="place-journey-fallback"><span class="journey-earth" aria-hidden="true">◒</span><span class="journey-fallback-line">${t("mapPreview")}<small>${t("placeContextShown")}</small></span></div></div>${legend}<div class="place-journey-toolbar"><span class="place-journey-status">${!group && target.place !== journey.place ? escapeHtml(translateWith("Memoir.workspace.parentMap", { place: target.place })) : tWith("approximate", { placeType: group ? (currentUiLocale() === "zh-CN" ? "地点" : "places") : placeType })}</span>${mapLink}</div></section>`;
}

function placeJourneySurface() {
  return state.placeJourney && placeMapTarget(state.placeJourney) && !workspaceHasContent() ? placeJourneyMarkup(state.placeJourney) : "";
}

function placesWorkspace() {
  const t = (key) => escapeHtml(translate(`Memoir.workspace.${key}`));
  if (!state.placeJourney) return `<div class="workspace-scroll"><div class="workspace-intro"><h2>${t("places")}</h2><p>${t("placesIntro")}</p></div><div class="workspace-empty"><span>◎</span><p>${t("placesEmpty")}</p></div></div>`;
  const places = mergePlaces(profile().memory_places || []);
  const matching = state.lifeStage === "all" ? places : places.filter(item => matchesPlaceStage(item, state.lifeStage));
  const mappedPlaces = matching.filter((item) => placeMapTarget(item));
  const current = placeWorkspaceSelection() || mappedPlaces.at(-1);
  if (!current || !placeMapTarget(current)) return "";
  const groups = workspacePlaceGroups(matching);
  const group = groups.find(item => item.members.some(member => placeHistoryKey(member) === placeHistoryKey(current)));
  const photoGroup = state.lifeStage === "all" ? group : workspacePlaceGroups(places)
    .find(item => item.members.some(member => placeHistoryKey(member) === placeHistoryKey(current)));
  const choices = placeHistoryChoices(groupChoices(groups), current);
  return `<div class="workspace-scroll workspace-places"><button class="text-button" data-all-places>${t("allPlaces")}</button>${choices}${current ? placeJourneyMarkup(current, "workspace", group) + pictureWall(workspacePictureItems(current, photoGroup), current) : `<div class="workspace-empty"><p>${t("placesEmpty")}</p></div>`}</div>`;
}

function picturesWorkspace() {
  const t = (key) => escapeHtml(translate(`Memoir.workspace.${key}`));
  const pictures = renderablePictureItems(searchedPictures());
  if (!pictures.length) return "";
  return `<div class="workspace-scroll"><div class="workspace-intro"><p>${t("picturesIntro")}</p></div>${renderCueCards(pictures)}</div>`;
}

function disposeCesiumPlaceJourney() {
  if (!cesiumPlaceJourneyViewer) return;
  try {
    if (!cesiumPlaceJourneyViewer.isDestroyed()) cesiumPlaceJourneyViewer.destroy();
  } catch {
    // A failed external Cesium load should never block the memoir conversation.
  }
  cesiumPlaceJourneyViewer = null;
}

function loadCesium() {
  if (window.Cesium) return Promise.resolve(window.Cesium);
  if (cesiumLoadPromise) return cesiumLoadPromise;
  const base = `https://cesium.com/downloads/cesiumjs/releases/${CESIUM_VERSION}/Build/Cesium`;
  if (!document.getElementById("cesium-place-journey-widgets")) {
    const stylesheet = document.createElement("link");
    stylesheet.id = "cesium-place-journey-widgets";
    stylesheet.rel = "stylesheet";
    stylesheet.href = `${base}/Widgets/widgets.css`;
    document.head.appendChild(stylesheet);
  }
  window.CESIUM_BASE_URL = `${base}/`;
  cesiumLoadPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = `${base}/Cesium.js`;
    script.async = true;
    script.addEventListener("load", () => window.Cesium ? resolve(window.Cesium) : reject(new Error("CesiumJS did not expose its global.")));
    script.addEventListener("error", () => reject(new Error("CesiumJS could not be loaded.")));
    document.head.appendChild(script);
  });
  return cesiumLoadPromise;
}

const resolvedPlaceTargets = new Map();
const pendingPlaceTargets = new Map();
const placeGroupRecords = new Map();
const placeGroupRequests = new Map();
const placeGroupLatest = new Map();

function publicPlaceFields(place) {
  return {place: place.place, hierarchy: place.hierarchy, granularity: place.granularity,
    latitude: place.latitude, longitude: place.longitude};
}

function selectPlace(key) {
  state.selectedPlace = key;
  const place = (profile().memory_places || []).find(item => placeHistoryKey(item) === key);
  if (place) void loadPlacePictures(place, state.project?.id);
  render();
}

function workspacePlaceGroups(places) {
  const entries = mergePlaces([...places, ...(state.placeJourney?.preview ? [state.placeJourney] : [])]);
  return groupPlaces(entries.map(place => {
    const record = placeGroupRecords.get(`${state.project?.id}:${placeHistoryKey(place)}`);
    return record && record.input === JSON.stringify(publicPlaceFields(place))
      ? {...place, map_city: record.city, map_city_key: record.city_key, map_pin: record.pin} : place;
  }));
}

function groupChoices(groups) {
  return groups.map(group => ({...group.city,
    group_members: group.members.map(placeHistoryKey),
    life_stages: [...new Set(group.members.flatMap(member => member.life_stages || [member.life_stage]).filter(Boolean))]}));
}

function resolvePlaceGroups(journey) {
  const projectId = state.project?.id;
  if (!projectId || !journey) return;
  const merged = mergePlaces([...(profile().memory_places || []), journey]);
  const newest = merged.find(place => placeHistoryKey(place) === placeHistoryKey(journey));
  if (!newest) return;
  // Resolve the newest mention first even when history is sorted by life stage.
  const places = [newest,
    ...merged.filter(place => placeHistoryKey(place) !== placeHistoryKey(journey))];
  // The grouping service receives only public geographic fields.
  const publicPlaces = places.map(publicPlaceFields);
  const signature = JSON.stringify([projectId, publicPlaces]);
  if (placeGroupRequests.has(signature)) return;
  placeGroupLatest.set(projectId, signature);
  const request = api(`/v1/projects/${projectId}/place-groups`, {
    method: "POST", body: JSON.stringify({places: publicPlaces}),
  }).then(result => {
    if (state.project?.id !== projectId || placeGroupLatest.get(projectId) !== signature) return;
    for (const record of result.places || []) {
      const place = places[record.index];
      if (place) placeGroupRecords.set(`${projectId}:${placeHistoryKey(place)}`,
        {...record, input: JSON.stringify(publicPlaces[record.index])});
    }
    render();
  }).catch(() => {}).finally(() => {
    // Keep a completed signature briefly; renders must not repeat failed lookups.
    setTimeout(() => {
      if (placeGroupRequests.get(signature) === request) placeGroupRequests.delete(signature);
    }, 60_000);
  });
  placeGroupRequests.set(signature, request);
  while (placeGroupRequests.size > 32) placeGroupRequests.delete(placeGroupRequests.keys().next().value);
}

function resolvePlaceMap(journey) {
  if (!journey || !state.project?.id) return;
  void resolvePlaceGroups(journey);
  const key = placeHistoryKey(journey);
  if (mapTarget(journey, []) || resolvedPlaceTargets.has(key) || pendingPlaceTargets.has(key)) return;
  const projectId = state.project.id;
  const request = api(`/v1/projects/${projectId}/place-map`, {method: "POST", body: JSON.stringify(journey)})
    .then(result => {
      if (result.target) resolvedPlaceTargets.set(key, result.target);
      // Cache no-match as well to avoid repeated searches on every render.
      else resolvedPlaceTargets.set(key, null);
      if (result.target?.place === journey.place) void loadPlacePictures(journey, projectId);
      if (state.project?.id === projectId) render();
    }).catch(() => { resolvedPlaceTargets.set(key, null); })
    .finally(() => pendingPlaceTargets.delete(key));
  pendingPlaceTargets.set(key, request);
}

function initCesiumPlaceJourney() {
  const container = $("[data-cesium-place]");
  if (container) resolvePlaceMap(placeWorkspaceSelection());
  if (!container || !container.dataset.cesiumLatitude || !container.dataset.cesiumLongitude) return;
  const latitude = Number(container.dataset.cesiumLatitude);
  const longitude = Number(container.dataset.cesiumLongitude);
  const journey = placeWorkspaceSelection() || state.placeJourney;
  const finalMapHeight = Number(container.dataset.cesiumHeight) || placeMapViewHeight(journey, placeMapTarget(journey));
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
  loadCesium().then((cesium) => {
    if (!container.isConnected) return;
    let viewer = null;
    let arrivalComplete = false;
    let roadmapReady = false;
    let finalViewStarted = false;
    try {
      viewer = new cesium.Viewer(container, {
        animation: false,
        baseLayer: false,
        baseLayerPicker: false,
        fullscreenButton: false,
        geocoder: false,
        homeButton: false,
        infoBox: false,
        navigationHelpButton: false,
        sceneModePicker: false,
        selectionIndicator: false,
        timeline: false,
        scene3DOnly: false,
        mapProjection: new cesium.WebMercatorProjection(),
        shouldAnimate: false,
      });
      cesiumPlaceJourneyViewer = viewer;
      viewer.scene.backgroundColor = cesium.Color.fromCssColorString("#173f45");
      viewer.scene.globe.enableLighting = false;
      viewer.scene.globe.maximumScreenSpaceError = 1;
      viewer.scene.skyAtmosphere.show = true;
      viewer.scene.globe.baseColor = cesium.Color.fromCssColorString("#2a756b");
      const destination = cesium.Cartesian3.fromDegrees(longitude, latitude, finalMapHeight);
      const pins = container.dataset.cesiumPins ? JSON.parse(container.dataset.cesiumPins) : [
        {place: container.dataset.cesiumPlace, latitude, longitude}];
      for (const pin of pins) viewer.entities.add({
        id: pin.key,
        position: cesium.Cartesian3.fromDegrees(pin.longitude, pin.latitude),
        point: {
          color: cesium.Color.fromCssColorString("#f3c66b"),
          outlineColor: cesium.Color.fromCssColorString("#fff8e7"),
          outlineWidth: 2,
          pixelSize: 12,
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
        label: {
          text: pin.place || "Memory place",
          fillColor: cesium.Color.WHITE,
          font: "600 14px DM Sans, sans-serif",
          style: cesium.LabelStyle.FILL_AND_OUTLINE,
          outlineColor: cesium.Color.fromCssColorString("#173f45"),
          outlineWidth: 3,
          pixelOffset: new cesium.Cartesian2(0, -24),
          disableDepthTestDistance: Number.POSITIVE_INFINITY,
        },
      });
      viewer.screenSpaceEventHandler.setInputAction(event => {
        const picked = viewer.scene.pick(event.position)?.id;
        if (!picked?.id) return;
        const member = (profile().memory_places || []).find(place => placeHistoryKey(place) === picked.id);
        if (!member) return;
        state.selectedPlace = picked.id;
        void loadPlacePictures(member, state.project?.id);
        render();
      }, cesium.ScreenSpaceEventType.LEFT_CLICK);

      const showFinalRoadMap = () => {
        if (!arrivalComplete || !roadmapReady || finalViewStarted || !container.isConnected || viewer.isDestroyed()) return;
        finalViewStarted = true;
        // The flight already arrives looking straight down. Switch projection
        // without Cesium's world-scale unfolding animation pulling us away.
        viewer.scene.morphTo2D(0);
        viewer.camera.setView({
          destination,
          orientation: { heading: 0, pitch: -Math.PI / 2, roll: 0 },
        });
        container.closest(".place-journey-scene")?.classList.add("is-cesium-map");
        viewer.scene.requestRender();
      };

      // Fit the whole Earth in the narrower dimension of this panel. Looking
      // off-nadir at orbital altitude pushes the globe below the viewport.
      viewer.resize();
      const frustum = viewer.camera.frustum;
      const halfFov = Math.min(frustum.fovy / 2, Math.atan(Math.tan(frustum.fovy / 2) * frustum.aspectRatio));
      const radius = viewer.scene.globe.ellipsoid.maximumRadius;
      const startHeight = radius * (1.15 / Math.sin(halfFov) - 1);
      viewer.camera.setView({
        destination: cesium.Cartesian3.fromDegrees(0, 18, startHeight),
        orientation: { heading: 0, pitch: -Math.PI / 2, roll: 0 },
      });
      viewer.camera.flyTo({
        destination,
        orientation: { heading: 0, pitch: -Math.PI / 2, roll: 0 },
        duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? 0 : Math.max(2.8, Math.min(9, Number(container.dataset.cesiumDuration || 5200) / 1000)),
        easingFunction: cesium.EasingFunction.QUADRATIC_IN_OUT,
        complete: () => {
          arrivalComplete = true;
          showFinalRoadMap();
        },
      });
      container.closest(".place-journey-scene")?.classList.add("is-cesium-live");
      container.parentElement.querySelector(".place-journey-fallback")?.setAttribute("aria-hidden", "true");

      const googleMapsKey = state.supabase?.google_maps_browser_api_key;
      if (!googleMapsKey || typeof cesium.Google2DImageryProvider?.fromUrl !== "function") return;
      cesium.Google2DImageryProvider.fromUrl({
        key: googleMapsKey,
        mapType: "roadmap",
        language: currentUiLocale(),
        region: currentUiLocale() === "zh-CN" ? "CN" : "AU",
      }).then((imagery) => {
        if (!container.isConnected || !viewer || viewer.isDestroyed()) return;
        viewer.imageryLayers.addImageryProvider(imagery);
        roadmapReady = true;
        showFinalRoadMap();
      }).catch((error) => {
        console.warn("Google Maps roadmap imagery unavailable; using the globe surface.", error);
      });
    } catch (error) {
      if (viewer && !viewer.isDestroyed()) viewer.destroy();
      if (cesiumPlaceJourneyViewer === viewer) cesiumPlaceJourneyViewer = null;
      console.warn("Cesium place journey unavailable; using the hierarchy fallback.", error);
    }
  }).catch((error) => console.warn("Cesium place journey unavailable; using the hierarchy fallback.", error));
}

function referencesWorkspace() {
  const t = (key) => escapeHtml(translate(`Memoir.workspace.${key}`));
  const references = state.sources.slice(0, 5);
  if (!references.length) return `<div class="reference-shelf"><div class="eyebrow">${t("references")}</div><p class="fine-print">${t("referencesEmpty")}</p></div>`;
  return `<div class="reference-shelf"><div class="eyebrow">${t("references")}</div><p class="fine-print">${t("referencesDescription")}</p>${references.map((item) => `<div class="reference-row"><span class="reference-icon">${item.kind === "photo" ? "▧" : "✎"}</span><div><strong>${escapeHtml(item.filename || item.historical_date_expression || translate("Memoir.workspace.personalSource"))}</strong><small>${escapeHtml(item.kind || translate("Memoir.workspace.source"))} · ${item.original_retained ? t("originalRetained") : t("sourceNote")}</small></div></div>`).join("")}</div>`;
}

function sourcePills(memoryIds) {
  if (!memoryIds.length) return `<span class="source-pill">${escapeHtml(translate("Memoir.workspace.noMemoryLinks"))}</span>`;
  return memoryIds.map((id) => `<span class="source-pill">${escapeHtml(id.slice(-8))}</span>`).join("");
}

function composerIcon(name) {
  const paths = {
    plus: '<path d="M12 4v16M4 12h16"/>',
    mic: '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/>',
    wave: '<path d="M4 10v4M8 6v12M12 3v18M16 7v10M20 10v4"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>',
    send: '<path d="M12 20V4m-7 7 7-7 7 7"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    muted: '<path d="m3 3 18 18M9 9v3a3 3 0 0 0 5 2M9 5a3 3 0 0 1 6 0v4M5 10v2a7 7 0 0 0 12 5M19 10v2M12 19v3"/>',
  };
  return `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]}</svg>`;
}

const ATTACHMENT_TYPES = {
  "image/jpeg": "photo", "image/png": "photo", "image/heic": "photo", "image/webp": "photo", "image/gif": "photo",
  "video/mp4": "video", "video/webm": "video", "video/quicktime": "video",
};

function attachmentPreview(item) {
  const url = escapeHtml(item.url);
  return `${item.kind === "video" ? `<video src="${url}" controls preload="metadata"></video>` : `<img src="${url}" alt="${escapeHtml(item.file.name)}" />`}<span>${escapeHtml(item.file.name)}</span>`;
}

function composerAttachments() {
  if (!state.attachments.length) return "";
  const t = key => escapeHtml(translate(`Memoir.story.${key}`));
  return `<div class="composer-attachments">${state.attachments.map((item, index) => `<div class="composer-attachment">${attachmentPreview(item)}<button type="button" data-action="remove-attachment" data-index="${index}" aria-label="${t("removeAttachment")}: ${escapeHtml(item.file.name)}" ${state.loading ? "disabled" : ""}>${composerIcon("close")}</button></div>`).join("")}</div><label class="attachment-rights"><input id="attachment-rights" type="checkbox" ${state.attachmentRights ? "checked" : ""} ${state.loading ? "disabled" : ""} />${t("attachmentRights")}</label><div class="attachment-progress" role="status">${escapeHtml(state.attachmentProgress)}</div>`;
}

function selectAttachments(files) {
  if (state.loading) return;
  for (const file of files) {
    const kind = ATTACHMENT_TYPES[file.type];
    const limit = (kind === "video" ? 100 : 25) * 1024 * 1024;
    if (!kind || !file.size || file.size > limit) {
      toast(translate("Memoir.story.attachmentInvalid"));
      continue;
    }
    state.attachments.push({ file, kind, url: URL.createObjectURL(file), upload: null, asset: null });
    state.attachmentRights = false;
  }
  render();
}

async function uploadAttachments(items) {
  for (const item of items) {
    if (item.asset) continue;
    const { file, kind } = item;
    state.attachmentProgress = translateWith("Memoir.story.uploadingAttachment", { name: file.name });
    render();
    item.upload ||= await api("/v1/uploads", { method: "POST", body: JSON.stringify({ project_id: state.project.id, kind, filename: file.name, mime_type: file.type, expected_size: file.size, rights_confirmed: state.attachmentRights }) });
    // Reuse the same upload on retry; acknowledged parts are idempotent.
    const partSize = item.upload.max_part_size || 5 * 1024 * 1024;
    const existing = await api(`/v1/uploads/${item.upload.id}`);
    if (existing.state === "READY") { item.asset = existing.asset; continue; }
    for (let offset = 0, sequence = 0; offset < file.size; offset += partSize, sequence += 1) {
      const content = await blobToBase64(file.slice(offset, offset + partSize));
      await api(`/v1/uploads/${item.upload.id}/parts`, { method: "POST", body: JSON.stringify({ sequence, content }) });
    }
    item.asset = await api(`/v1/uploads/${item.upload.id}/finalize`, { method: "POST", body: JSON.stringify({}) });
  }
}

async function ensureRecallPreview({ retry = false, poll = false } = {}) {
  const projectId = state.project?.id;
  const userId = state.supabase?.user?.id;
  if (!projectId || !state.recallStatus?.payment_required) return;
  const previous = state.recallPreview?.projectId === projectId && state.recallPreview.userId === userId
    ? state.recallPreview : null;
  if (previous?.inFlight || previous?.status === "loading") return;
  if (!retry && !poll && previous) return;
  if (previous?.timer) clearTimeout(previous.timer);
  const checking = poll || (retry && previous?.status === "paused");
  const attempt = { projectId, userId, status: checking ? "pending" : "loading", inFlight: true,
    startedAt: checking ? previous?.startedAt || Date.now() : Date.now(), job: checking ? previous?.job : null,
    pollErrors: checking ? previous?.pollErrors || 0 : 0,
    slow: checking && Date.now() - (previous?.startedAt || Date.now()) >= 30000 };
  state.recallPreview = attempt;
  render();
  const current = () => state.recallPreview === attempt && state.project?.id === projectId
    && state.supabase?.user?.id === userId;
  const slowTimer = setTimeout(() => {
    if (current()) { attempt.slow = true; render(); }
  }, 30000);
  const controller = new AbortController();
  const requestTimer = setTimeout(() => controller.abort(), 30000);
  try {
    const result = await storyApi(checking && attempt.job?.id
      ? `/v1/story/preview/${encodeURIComponent(attempt.job.id)}` : "/v1/story/preview", {
      ...(checking && attempt.job?.id ? {} : { method: "POST",
        body: JSON.stringify({ project_id: projectId, language: conversationLanguage() }) }),
      signal: controller.signal,
    });
    if (!current()) return;
    Object.assign(attempt, result, { pollErrors: 0, reconnect: false });
  } catch (error) {
    if (!current()) return;
    const pending = error.code === "AGENT_TURN_IN_PROGRESS";
    const reconnecting = checking && attempt.job && (error.name === "AbortError" || !error.status || error.status >= 500);
    attempt.pollErrors += reconnecting ? 1 : 0;
    attempt.status = pending || (reconnecting && attempt.pollErrors <= 3) ? "pending" : "error";
    attempt.reconnect = reconnecting;
    attempt.authRequired = error.status === 401 || error.status === 403;
  } finally {
    clearTimeout(slowTimer);
    clearTimeout(requestTimer);
    if (current()) {
      attempt.inFlight = false;
      attempt.slow = Date.now() - attempt.startedAt >= 30000;
      if (attempt.status === "pending") {
        if (Date.now() - attempt.startedAt >= 900000) attempt.status = "paused";
        else attempt.timer = setTimeout(() => {
          if (state.recallPreview === attempt && state.project?.id === projectId
              && state.supabase?.user?.id === userId) void ensureRecallPreview({ poll: true });
        }, attempt.job ? Math.min(15000, Math.max(3000, (attempt.retry_after || 3) * 1000)) : 15000);
      }
      render();
    }
  }
}

function recallPackagePrompt() {
  if (!state.recallStatus?.payment_required) return "";
  const t = key => escapeHtml(translate(`Memoir.recall.${key}`));
  const sample = state.recallPreview?.projectId === state.project?.id
    && state.recallPreview.userId === state.supabase?.user?.id ? state.recallPreview : null;
  if (!sample || sample.status === "loading" || sample.status === "pending") {
    const message = sample?.reconnect ? "previewReconnecting" : sample?.slow ? "previewSlow" : "previewPreparing";
    return `<section class="recall-preview" aria-busy="true"><h2>${t("previewTitle")}</h2><p role="status" aria-live="polite"><span class="preview-spinner" aria-hidden="true"></span>${t(message)}</p><button type="button" class="button button-secondary" disabled>${t("previewWorking")}</button></section>`;
  }
  if (sample.status !== "ready" || !sample.preview) {
    return `<section class="recall-preview"><h2>${t("previewTitle")}</h2><p role="status" aria-live="polite">${t(sample.authRequired ? "previewSignIn" : sample.status === "paused" ? "previewPaused" : sample.status === "stale" ? "previewStale" : sample.status === "insufficient_context" ? "previewInsufficient" : "previewFailed")}</p><button type="button" class="button button-secondary" data-retry-recall-preview>${t(sample.status === "paused" ? "previewCheck" : "previewRetry")}</button></section>`;
  }
  const preview = sample.preview;
  const excerpt = `<article class="recall-preview"><div class="eyebrow">${t(preview.kind === "sample_storyline" ? "sampleStoryline" : "sampleChapter")}</div><h2>${escapeHtml(preview.title)}</h2><div class="recall-preview-text">${formatText(preview.text)}</div>${preview.kind === "sample_storyline" && preview.outline?.length ? `<ol>${preview.outline.map(title => `<li>${escapeHtml(title)}</li>`).join("")}</ol>` : ""}<p class="fine-print">${t("previewNote")}</p></article>`;
  const pending = new URLSearchParams(window.location.search).get("checkout") === "success";
  return `${excerpt}<section class="recall-package-prompt" aria-labelledby="recall-package-title"><h2 id="recall-package-title">${t("title")}</h2><p>${t("description")}</p>${state.supabase?.user?.is_anonymous ? `<p class="fine-print">${t("signIn")}</p>` : ""}${pending ? `<p role="status">${escapeHtml(translate("Memoir.storyFlow.paymentConfirming"))}</p>` : ""}<button type="button" class="text-button" data-check-recall-payment ${state.loading ? "disabled" : ""}>${t("checkPayment")}</button>${storyCheckoutForm()}</section>`;
}

function chatComposer() {
  if (state.recallStatus?.payment_required) return "";
  const t = (key) => escapeHtml(translate(`Memoir.story.${key}`));
  const button = (action, label, icon, extra = "") => `<button type="button" class="voice-button ${extra}" data-action="${action}" aria-label="${t(label)}" title="${t(label)}">${composerIcon(icon)}</button>`;
  if (state.dictationStatus !== "off") {
    const processing = ["starting", "processing"].includes(state.dictationStatus);
    return `<div class="composer-wrap"><div class="chat-composer dictation-composer">${button("cancel-dictation", "cancelDictation", "close")}<div class="dictation-visual"><div class="dictation-wave ${state.recording ? "is-recording" : ""}" aria-hidden="true">${"<i></i>".repeat(40)}</div><span role="status">${t(processing ? (state.dictationStatus === "starting" ? "connectingMic" : "transcribing") : state.recording ? "dictating" : "dictationStopped")}</span></div>${!processing ? `${state.recording ? button("stop-dictation", "stopDictation", "stop") : ""}${button("accept-dictation", "send", "send", "voice-mode-button")}` : ""}</div><div class="composer-note">${t("dictationNote")}</div></div>`;
  }
  const status = state.voiceMuted ? "muted" : state.voiceModeStatus;
  const voiceStatus = state.voiceMode ? `<div class="voice-session"><div class="voice-orb ${status}" aria-hidden="true"><div class="voice-orb-water"><i></i><i></i><i></i></div></div><div class="voice-mode-status" role="status"><strong class="voice-mode-title">${t("voiceConversation")}</strong><span>${t(state.voiceMuted ? "micMuted" : status === "speaking" ? "miraSpeaking" : status === "processing" ? "listeningBack" : "listening")}</span></div></div>` : "";
  const controls = state.voiceMode
    ? `${button("mute-voice", state.voiceMuted ? "unmuteMic" : "muteMic", state.voiceMuted ? "muted" : "mic")}${button("voice-input", "endVoice", "close", "voice-mode-end")}`
    : `${button("dictate", "dictate", "mic", "dictation-button")}${button("voice-input", "startVoice", "wave", "voice-mode-button voice-mode-launcher")}`;
  return `<div class="composer-wrap ${state.voiceMode ? "has-voice-orb" : ""}">${voiceStatus}${composerAttachments()}<form id="chat-form" class="chat-composer" data-voice-mode="${state.voiceMode ? "on" : "off"}"><button type="button" class="voice-button" data-action="attach-media" aria-label="${t("attachMedia")}" title="${t("attachMedia")}" ${state.loading ? "disabled" : ""}>${composerIcon("plus")}</button><input id="chat-attachments" type="file" accept="${Object.keys(ATTACHMENT_TYPES).join(",")}" multiple hidden /><textarea id="chat-input" rows="1" placeholder="${t(state.voiceMode ? "voicePlaceholder" : "textPlaceholder")}" aria-label="${t("yourMessage")}">${escapeHtml(state.audioTranscript)}</textarea>${controls}<button type="submit" class="send-button" aria-label="${t("send")}" ${state.loading ? "disabled" : ""}>${composerIcon("send")}</button></form><div class="composer-note"><span>${t(state.voiceMode ? "voiceNote" : "sourceNote")}</span><span>${t("shortcutNote")}</span></div></div>`;
}

function renderMessage(message) {
  if (message.role === "user") {
    const you = escapeHtml(translate("Common.you"));
    return `<article class="chat-row user-message"><div class="chat-bubble"><div class="message-label">${you}</div><div class="message-text">${formatText(message.text)}</div>${message.attachments?.length ? `<div class="composer-attachments">${message.attachments.map(item => `<div class="composer-attachment">${attachmentPreview(item)}</div>`).join("")}</div>` : ""}</div></article>`;
  }
  const streaming = Boolean(message.streaming);
  const visibleText = cleanAssistantText(message.text);
  const action = !streaming && message.action ? `<button class="button button-primary button-small message-action" data-action="${message.action.name}">${escapeHtml(message.action.label)} <span>↗</span></button>` : "";
  const trace = renderAgentTrace(message.trace || [], message.traceMode, streaming && !visibleText);
  const listen = streaming ? "" : `<button class="listen-button" data-action="speak" data-text="${escapeHtml(visibleText)}" aria-label="${escapeHtml(translate("Memoir.story.listen"))}">◖ ${escapeHtml(translate("Memoir.story.listenButton"))}</button>`;
  return `<article class="chat-row assistant-message ${streaming ? "message-streaming" : ""}" data-message-id="${escapeHtml(message.id || "")}"><div class="chat-bubble"><div class="message-meta"><span class="message-label">${CHATBOT_NAME}</span>${listen}</div><div class="message-thinking" role="status" ${streaming && !visibleText ? "" : "hidden"}>${escapeHtml(translate("Memoir.story.thinkingCodex"))}</div><div class="message-trace" aria-live="polite">${trace}</div><div class="message-text" aria-live="polite" ${visibleText ? "" : "hidden"}>${formatText(visibleText)}</div>${message.error ? `<p role="alert">${escapeHtml(message.error)}</p>` : ""}${action}</div></article>`;
}

function renderAgentTrace(trace, mode = "simulated", expanded = false) {
  if (!state.showThinkingSteps || mode === "simulated") return "";
  // Routine transport and persistence events are not useful conversation steps.
  const visibleSteps = trace.filter(step => !["context", "reply"].includes(step.id)
    && (step.id !== "workspace" || ["completed", "failed"].includes(step.status)));
  if (!visibleSteps.length) return "";
  const title = escapeHtml(translate("Memoir.trace.title"));
  const steps = visibleSteps.map((step) => `<li class="agent-loop-step agent-loop-${escapeHtml(step.kind || "analysis")}" data-step-id="${escapeHtml(step.id || "")}" data-step-status="${escapeHtml(step.status || "completed")}"><span class="agent-loop-detail">${step.skill ? `${escapeHtml(step.skill)} · ${escapeHtml(translate(`Memoir.trace.status.${step.status || "triggered"}`))} — ` : ""}${escapeHtml(step.detail || step.label || "")}</span></li>`).join("");
  return `<details class="agent-loop" ${expanded ? "open" : ""}><summary><span>${title}</span></summary><ol class="agent-loop-list">${steps}</ol></details>`;
}

function renderCueCards(cues) {
  const t = (key) => escapeHtml(translate(`Memoir.workspace.${key}`));
  return `<div class="cue-section"><div class="cue-section-label">${t("publicReferenceCues")}</div><div class="cue-grid">${cues.map((cue) => `<article class="photo-card"><div class="photo-art ${cue.kind === "video" ? "video-art" : "image-art"}"><span>${cue.kind === "video" ? "▶" : "✦"}</span></div><div class="photo-card-body"><strong>${escapeHtml(cue.title)}</strong><small>${escapeHtml(cue.location || t("historicalReference"))} · ${escapeHtml(cue.scene_date_range?.start || t("dateUnknown"))}–${escapeHtml(cue.scene_date_range?.end || "")}</small><p>${escapeHtml(cue.label)}</p><div class="photo-actions"><a href="${escapeHtml(cue.source_url || "#")}" target="_blank" rel="noreferrer">${t("viewSource")}</a><button class="text-button" data-action="cue-reaction" data-asset="${escapeHtml(cue.asset_id)}" data-reaction="familiar">${t("familiar")}</button><button class="text-button" data-action="cue-reaction" data-asset="${escapeHtml(cue.asset_id)}" data-reaction="different">${t("different")}</button></div></div></article>`).join("")}</div></div>`;
}

function bindViewActions() {
  $(".family-workspace")?.addEventListener("error", event => {
    if (event.target.matches("[data-family-portrait]")) event.target.remove();
  }, true);
  document.querySelectorAll("[data-family-zoom]").forEach(button => button.addEventListener("click", () => zoomFamilyChart(button.dataset.familyZoom)));
  $(".family-chart-fallback")?.addEventListener("click", event => {
    const button = event.target.closest("[data-family-person]");
    if (button) selectFamilyPerson(button.dataset.familyPerson);
  });
  $("#family-person-detail")?.addEventListener("click", event => {
    if (event.target.closest("[data-family-person-close]")) closeFamilyPerson();
    if (event.target.closest("[data-family-photo-upload]")) $("#family-person-photo")?.click();
    if (event.target.closest("[data-family-photo-remove]")) void saveFamilyPersonPhoto();
  });
  $("#family-person-detail")?.addEventListener("change", event => {
    if (event.target.id === "family-person-photo" && event.target.files?.[0]) void saveFamilyPersonPhoto(event.target.files[0]);
  });
  $("#family-person-detail")?.addEventListener("keydown", event => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); closeFamilyPerson(); }
  });
  $("[data-retry-recall-preview]")?.addEventListener("click", () => ensureRecallPreview({ retry: true }));
  $("[data-check-recall-payment]")?.addEventListener("click", async () => {
    state.loading = true;
    render();
    await refreshFamilyEntitlement();
    state.loading = false;
    render();
  });
  $("#story-checkout-form")?.addEventListener("submit", event => {
    event.preventDefault();
    requestStoryCheckout();
  });
  document.querySelectorAll("input[name='plan_key']").forEach(input => input.addEventListener("change", () => {
    state.selectedStoryPlan = input.value;
    render();
  }));
  $("#story-book-count")?.addEventListener("change", event => {
    state.storyBookCount = Number(event.target.value) || 2;
    render();
  });
  $("[data-all-places]")?.addEventListener("click", () => { state.lifeStage = "all"; state.selectedPlace = null; render(); });
  document.querySelectorAll("[data-place-choice]").forEach(button => button.addEventListener("click", () => selectPlace(button.dataset.placeChoice)));
  $("[data-action='toggle-workspace']")?.addEventListener("click", () => {
    state.workspaceCollapsed = !state.workspaceCollapsed;
    render();
    $("[data-action='toggle-workspace']")?.focus({ preventScroll: true });
  });
  $("[data-action='toggle-chat-history']")?.addEventListener("click", () => {
    state.chatHistoryCollapsed = !state.chatHistoryCollapsed;
    render();
    if (!state.chatHistoryCollapsed && $("#chat-scroll")) {
      conversationScroll.pause();
      $("#chat-scroll").scrollTop = 0;
    }
    $("[data-action='toggle-chat-history']")?.focus({ preventScroll: true });
  });
  $("#chat-attachments")?.addEventListener("change", event => selectAttachments(Array.from(event.target.files || [])));
  $("#attachment-rights")?.addEventListener("change", event => { state.attachmentRights = event.target.checked; });
  $("[data-action='story-home']")?.addEventListener("click", (event) => { event.preventDefault(); stopVoiceMode({ silent: true }); state.chat = []; state.chatHistoryCollapsed = false; state.workspaceTab = "memoir"; cancelDictation(); render(); });
  $("#chat-form")?.addEventListener("submit", (event) => { event.preventDefault(); sendChatMessage(); });
  $("#chat-input")?.addEventListener("input", (event) => {
    if (!state.audioTranscript) state.audioTranscriptKind = "narrator_chat";
    state.audioTranscript = event.target.value;
    resizeChatInput(event.target);
  });
  resizeChatInput($("#chat-input"));
  $("#chat-input")?.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendChatMessage(); } });
  const lifeStageTabs = Array.from(document.querySelectorAll("[data-life-stage-tab]"));
  lifeStageTabs.forEach((button) => {
    button.addEventListener("click", () => selectLifeStage(button.dataset.lifeStageTab, true));
    button.addEventListener("keydown", (event) => {
      const currentIndex = lifeStageTabs.indexOf(button);
      const nextIndex = event.key === "ArrowRight" ? (currentIndex + 1) % lifeStageTabs.length
        : event.key === "ArrowLeft" ? (currentIndex - 1 + lifeStageTabs.length) % lifeStageTabs.length
          : event.key === "Home" ? 0
            : event.key === "End" ? lifeStageTabs.length - 1
              : -1;
      if (nextIndex < 0) return;
      event.preventDefault();
      selectLifeStage(lifeStageTabs[nextIndex].dataset.lifeStageTab, true);
    });
  });
  document.querySelectorAll("[data-memoir-chapter]").forEach((button) => button.addEventListener("click", () => selectMemoirChapter(button.dataset.memoirChapter)));
  document.querySelectorAll("[data-workspace-tab]").forEach((button) => button.addEventListener("click", () => { state.workspaceTab = button.dataset.workspaceTab; render(); document.querySelector(`.workspace-detail-tab[data-workspace-tab="${state.workspaceTab}"]`)?.focus({ preventScroll: true }); }));
  document.querySelectorAll("[data-edit-memory-event]").forEach(button => button.addEventListener("click",() => openMemoryEventEdit(button.dataset.editMemoryEvent)));
  $("#memory-event-edit-form")?.addEventListener("input",event => { Object.assign(state.memoryEventEdit,Object.fromEntries(new FormData(event.currentTarget))); });
  $("#memory-event-edit-form")?.addEventListener("submit",saveMemoryEventEdit);
  const actions = {
    "start-memory": startMemory,
    "save-memory": completeMemory,
    "finish-chapter": finishChapter,
    "continue-memory": startMemory,
    "voice-input": toggleVoiceInput,
    "attach-media": () => $("#chat-attachments")?.click(),
    "remove-attachment": button => {
      if (state.loading) return;
      const [item] = state.attachments.splice(Number(button.dataset.index), 1);
      if (item) URL.revokeObjectURL(item.url);
      if (!state.attachments.length) state.attachmentRights = false;
      render();
    },
    "dictate": startAudioRecorder,
    "cancel-dictation": cancelDictation,
    "stop-dictation": () => finishDictation(false),
    "accept-dictation": () => finishDictation(true),
    "mute-voice": () => {
      state.voiceMuted = !state.voiceMuted;
      state.voiceModeStream?.getTracks().forEach((track) => { track.enabled = !state.voiceMuted; });
      if (!state.voiceMuted) queueVoiceModeTurn();
      render();
    },
    "speak": (button) => speakText(button.dataset.text),
    "cue-reaction": (button) => reactCue(button.dataset.asset, button.dataset.reaction),
    "add-person": addPerson,
    "add-timeline": addTimeline,
    "retry-private-draft": retryPrivateDraft,
    "cancel-event-edit": () => { state.memoryEventEdit = null; render(); },
  };
  document.querySelectorAll("[data-action]").forEach((button) => {
    const action = actions[button.dataset.action];
    if (action) button.addEventListener("click", () => action(button));
  });
}

async function ensureMemorySession() {
  if (state.session) return state.session;
  try {
    state.session = await api(`/v1/projects/${state.project.id}/memory-sessions`, {
      method: "POST",
      headers: { "Idempotency-Key": `browser-first-memory-${state.project.id}` },
      body: JSON.stringify({ topic_id: "childhood_home" }),
    });
    return state.session;
  } catch {
    // Codex remains usable when the chapter/session adapter is unavailable.
    return null;
  }
}

async function beginMemoryConversation(renderNow = true) {
  if (state.recallStatus?.payment_required) return;
  await ensureMemorySession();
  const fallback = conversationMessage("fallback");
  const result = await agentTurn("The storyteller wants to begin exploring a memory. Invite them to share whatever comes to mind, without using a fixed onboarding question.", fallback, ["memory.start", "memory.search"], conversationLanguage(), false, undefined, "begin");
  await streamAssistantMessage(result.reply || fallback, { streamedMessage: result.streamedMessage, trace: result.trace, traceMode: result.traceMode });
  try {
  const context = await api(`/v1/projects/${state.project.id}/context-search`, { method: "POST", body: JSON.stringify({ coarse_place: profile().birth_place || profile().childhood_place || null, approximate_year_start: profile().birth_year ? profile().birth_year + 5 : null, approximate_year_end: profile().birth_year ? profile().birth_year + 16 : null, topic_id: "childhood_home", language: conversationLanguage(), requested_media: ["image"] }) });
    if (context.items?.length) {
      await streamAssistantMessage(conversationMessage("publicContext"), { cues: context.items });
    }
  } catch {
    // A context provider can be unavailable; the conversation continues without it.
  }
  if (renderNow) render();
}

async function startMemory() {
  if (state.recallStatus?.payment_required) return;
  if (state.loading) return;
  try {
    state.loading = true;
    render();
    await ensureMemorySession();
    const fallback = conversationMessage("fallback");
    const result = await agentTurn("The storyteller wants to continue with another memory. Ask one open-ended question based on the conversation, without restarting onboarding.", fallback, ["memory.start", "memory.search"], conversationLanguage(), false, undefined, "continue");
    await streamAssistantMessage(result.reply || fallback, { streamedMessage: result.streamedMessage, trace: result.trace, traceMode: result.traceMode });
  } catch (error) { toast(error.message); }
  state.loading = false;
  render();
}

async function sendChatMessage({ voiceTurn = false } = {}) {
  if (state.recallStatus?.payment_required) return;
  if (state.loading || state.dictationStatus !== "off") return;
  if (state.voiceMode && state.voiceModeStatus !== "listening" && !voiceTurn) return;
  if (state.voiceMode && state.voiceModeRecorder && !voiceTurn) {
    if (state.voiceModeRecorder.state !== "inactive") {
      state.voiceModeStatus = "processing";
      state.voiceModeRecorder.stop();
      render();
    }
    return;
  }
  const input = $("#chat-input");
  const text = voiceTurn ? state.audioTranscript.trim() : (input?.value.trim() || state.audioTranscript.trim() || "");
  const sourceKind = voiceTurn ? "narrator_transcript" : state.audioTranscriptKind;
  const uploadId = state.audioUploadId;
  const attachments = voiceTurn ? [] : [...state.attachments];
  if (attachments.length && !state.attachmentRights) return toast(translate("Memoir.story.attachmentRightsRequired"));
  if (!text && !uploadId && !attachments.length) return toast(translate("Memoir.storyFlow.aFewWords"));
  if (state.voiceModeRecorder) {
    state.voiceModeTurnId += 1;
    state.voiceModeRecorder.stop();
  }
  if (state.voiceMode) state.voiceModeStatus = "processing";
  state.loading = true;
  state.freshAnonymousSession = false;
  if (attachments.length) {
    try { await uploadAttachments(attachments); }
    catch (error) {
      state.loading = false;
      state.attachmentProgress = error.message;
      if (state.voiceMode) { state.voiceModeStatus = "listening"; queueVoiceModeTurn(); }
      render();
      return;
    }
    state.attachments = [];
    state.attachmentRights = false;
    state.attachmentProgress = "";
  }
  const profileIntake = state.profileIntakePending;
  const messageText = text || (attachments.length ? translate("Memoir.story.sharedAttachments") : conversationMessage("voiceAnswer"));
  const firstReply = !profile().conversation_language?.initialized && !state.chat.some((message) => message.role === "user");
  const configuredConversationLanguage = conversationLanguage();
  const detectedFirstReplyLanguage = firstReply && !configuredConversationLanguage
    ? firstReplyLanguage(messageText)
    : undefined;
  if ($("#chat-input")) $("#chat-input").value = "";
  state.chatHistoryCollapsed = false;
  state.chat.push({ role: "user", text: messageText, attachments });
  conversationScroll.follow();
  state.audioUploadId = null;
  state.audioTranscript = "";
  render();
  try {
    if (detectedFirstReplyLanguage) await applyFirstReplyLocalization(detectedFirstReplyLanguage);
    const session = await ensureMemorySession();
    let cues = [];
    let action = null;
    let fallback = conversationMessage("fallback");
    let instruction = profileIntake
      ? PROFILE_INTAKE_PROMPT
      : "Acknowledge the storyteller naturally, then ask one gentle open-ended follow-up question. Do not restart onboarding or request profile fields.";
    if (session) {
      try {
        const turnType = session.turns?.length ? "follow_up" : "initial";
        const answerOptions = { method: "POST", body: JSON.stringify({ text: messageText, upload_id: uploadId, turn_type: turnType }) };
        try {
          state.session = await api(`/v1/memory-sessions/${session.id}/answers`, answerOptions);
        } catch (error) {
          if (error.code !== "POLICY_EPOCH_CONFLICT") throw error;
          // Consent/project setup is allowed to complete in parallel with the
          // first paint. Resync this still-open session once, then retry the
          // same answer; the Codex conversation remains the primary path.
          await api(`/v1/memory-sessions/${session.id}/resume`, { method: "POST" });
          state.session = await api(`/v1/memory-sessions/${session.id}/answers`, answerOptions);
        }
        cues = state.session.context_cues || [];
        const remaining = memoryFollowUpsRemaining(state.session);
        fallback = memoryFollowUpPrompt(state.session);
        const memoryInstruction = "Acknowledge the storyteller briefly, then ask one gentle follow-up question about their memory. Keep the conversation open unless they ask to pause, stop, or shape a chapter.";
        instruction = profileIntake ? `${PROFILE_INTAKE_PROMPT}\n${memoryInstruction}` : memoryInstruction;
        if (remaining === 0 && !profileIntake) action = { name: "save-memory", label: conversationMessage("saveMemory") };
      } catch {
        // The open Codex conversation is the primary path; session state is optional.
        state.session = null;
      }
    }
    const mediaContext = attachments.length ? `\nThe storyteller attached these saved sources: ${JSON.stringify(attachments.map(item => ({ asset_id: item.asset.id, filename: item.file.name, kind: item.kind })))}. Only attachment metadata is provided here; do not claim to have viewed their contents. Ask the storyteller about the people, place, or moment shown.` : "";
    const result = await agentTurn(
      `The storyteller said: ${messageText}\n${instruction}${mediaContext}`,
      fallback,
      ["memory.save", "memory.search"],
      detectedFirstReplyLanguage || configuredConversationLanguage || (firstReply ? currentUiLocale() : undefined),
      Boolean(detectedFirstReplyLanguage),
      messageText,
      null,
      sourceKind,
    );
    if (result.blocked) {
      // Another tab may have used the final free reply. Keep the unsent draft.
      state.chat.pop();
      state.audioTranscript = messageText;
      state.loading = false;
      render();
      return;
    }
    const cuesAlreadyShown = state.chat.some((message) => message.cues?.length);
    await streamAssistantMessage(result.reply || fallback, { streamedMessage: result.streamedMessage, trace: result.trace, traceMode: result.traceMode, cues: cues.length && !cuesAlreadyShown ? cues : undefined, action: result.streamedMessage?.failed ? null : action });
    if (state.voiceMode) await speakVoiceReply(result.reply || fallback);
  } catch (error) {
    toast(error.message);
  }
  state.loading = false;
  render();
  void refreshFamilyContext();
  if (state.voiceMode) window.setTimeout(() => startVoiceModeTurn(), 260);
}

async function completeMemory() {
  if (!state.session || state.loading) return;
  try {
    state.loading = true;
    render();
    const result = await api(`/v1/memory-sessions/${state.session.id}/complete`, { method: "POST", headers: { "Idempotency-Key": `browser-complete-${state.session.id}` }, body: JSON.stringify({ visibility: "private" }) });
    const decisionResponse = await api(`/v1/projects/${state.project.id}/chapter-decisions`, { method: "POST", body: JSON.stringify({ memory_id: result.memory.id, topic_id: result.memory.topic_id }) });
    state.chapterDecision = decisionResponse;
    state.session = null;
    const decisionText = decisionResponse.free ? conversationMessage("chapterDecisionFree") : decisionResponse.should_start_new_chapter ? translateWith("Memoir.conversation.chapterDecisionNew", { title: decisionResponse.title }) : conversationMessage("chapterDecisionCurrent");
    await streamAssistantMessage(decisionText, { trace: simulatedLoopTrace(["memory.complete", "chapter.decide"], translate("Memoir.trace.final")), traceMode: "simulated", action: decisionResponse.should_start_new_chapter ? { name: "finish-chapter", label: decisionResponse.free ? conversationMessage("finishFreeChapter") : translateWith("Memoir.conversation.finishChapter", { number: decisionResponse.chapter_number }) } : { name: "start-memory", label: conversationMessage("continueConversation") } });
    await refreshProject();
  } catch (error) { toast(error.message); }
  state.loading = false;
  render();
}

async function finishChapter() {
  if (!state.chapterDecision || state.loading) return;
  try {
    state.loading = true;
    render();
    const decision = state.chapterDecision;
    const built = await api(`/v1/projects/${state.project.id}/chapter-builds`, { method: "POST", body: JSON.stringify({ title: decision.title, memory_ids: decision.memory_ids, chapter_number: decision.chapter_number, free: decision.free }) });
    await api(`/v1/chapters/${built.chapter.id}/approvals`, { method: "POST", body: JSON.stringify({ expected_revision: built.chapter.revision }) });
    state.workspaceUnlocked = true;
    state.chapterDecision = null;
    const chapterText = decision.free ? conversationMessage("chapterFreeFinished") : translateWith("Memoir.conversation.chapterFinished", { number: decision.chapter_number });
    await streamAssistantMessage(chapterText, { trace: simulatedLoopTrace(["chapter.build", "chapter.approve"], translate("Memoir.trace.final")), traceMode: "simulated" });
    await refreshProject();
  } catch (error) { toast(error.message); }
  state.loading = false;
  render();
}

async function reactCue(assetId, reaction) {
  if (!state.session) return;
  try { await api(`/v1/memory-sessions/${state.session.id}/cue-reactions`, { method: "POST", body: JSON.stringify({ asset_id: assetId, reaction }) }); toast(reaction === "different" ? conversationMessage("cueDifferent") : conversationMessage("cueSaved")); } catch (error) { toast(error.message); }
}

async function speakText(text) {
  state.audioPlayer?.pause();
  if (state.session) {
    try {
      const generated = await api(`/v1/memory-sessions/${state.session.id}/question-audio`, {
        method: "POST",
        body: JSON.stringify({ language: conversationLanguage(), voice: "marin" }),
      });
      const response = await fetch(memoirApiPath(generated.audio_url));
      if (!response.ok) throw new Error("Generated audio could not be loaded.");
      const player = new Audio(URL.createObjectURL(await response.blob()));
      state.audioPlayer = player;
      player.onended = () => URL.revokeObjectURL(player.src);
      await player.play();
      return;
    } catch (error) {
      if (error.status !== 503) toast(error.message);
    }
  }
  if (!window.speechSynthesis) return toast(translate("Memoir.storyFlow.readAloudUnavailable"));
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = currentUiLocale();
  utterance.rate = 0.96;
  utterance.onend = () => { state.speaking = false; };
  state.speaking = true;
  window.speechSynthesis.speak(utterance);
}

function speakBrowserText(text) {
  if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) return Promise.resolve();
  window.speechSynthesis.cancel();
  return new Promise((resolve) => {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = currentUiLocale();
    utterance.rate = 0.96;
    const finish = () => {
      if (state.voiceModeSpeechResolve === finish) state.voiceModeSpeechResolve = null;
      resolve();
    };
    state.voiceModeSpeechResolve = finish;
    utterance.onend = finish;
    utterance.onerror = finish;
    window.speechSynthesis.speak(utterance);
  });
}

function setVoiceOrbLevel(level) {
  const orb = document.querySelector(".voice-orb");
  if (!orb) return;
  const value = Math.min(1, Math.max(0, level));
  orb.style.setProperty("--voice-level", value.toFixed(3));
}

// Keep playback analysis local to the player so ending voice mode releases it too.
function monitorVoicePlayback(player) {
  const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
  if (!state.voiceMode || !AudioContextCtor) return () => {};
  let context;
  let frame;
  try {
    context = new AudioContextCtor();
    const source = context.createMediaElementSource(player);
    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    analyser.connect(context.destination);
    const samples = new Uint8Array(analyser.fftSize);
    const tick = () => {
      analyser.getByteTimeDomainData(samples);
      const energy = samples.reduce((sum, sample) => sum + ((sample - 128) / 128) ** 2, 0);
      setVoiceOrbLevel(Math.sqrt(energy / samples.length) * 5);
      frame = window.requestAnimationFrame(tick);
    };
    context.resume().catch(() => {});
    frame = window.requestAnimationFrame(tick);
  } catch {
    context?.close().catch(() => {});
    return () => {};
  }
  return () => {
    window.cancelAnimationFrame(frame);
    context.close().catch(() => {});
    setVoiceOrbLevel(0);
  };
}

function playGeneratedAudio(generated) {
  if (!generated?.audio_base64) return Promise.reject(new Error("Generated audio was empty."));
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(base64ToBlob(generated.audio_base64, generated.mime_type || "audio/mpeg"));
    const player = new Audio(url);
    let settled = false;
    const stopMonitor = monitorVoicePlayback(player);
    const finish = (error) => {
      if (settled) return;
      settled = true;
      stopMonitor();
      URL.revokeObjectURL(url);
      player.onended = null;
      player.onerror = null;
      if (state.audioPlayer === player) state.audioPlayer = null;
      if (state.voiceModePlaybackFinish === finish) state.voiceModePlaybackFinish = null;
      if (error) reject(error);
      else resolve();
    };
    state.audioPlayer = player;
    state.voiceModePlaybackFinish = finish;
    player.onended = () => finish();
    player.onerror = () => finish(new Error("Generated audio could not be played."));
    player.play().catch(finish);
  });
}

async function speakVoiceReply(text) {
  if (!state.voiceMode || !text) return;
  const turnId = state.voiceModeTurnId;
  state.voiceModeStatus = "speaking";
  render();
  try {
    const generated = await storyApi("/v1/story/question-audio", {
      method: "POST",
      body: JSON.stringify({
        text,
        language: conversationLanguage(),
        voice: "marin",
        instructions: "Speak slowly, warmly and clearly with natural pauses, as a patient oral-history journalist.",
      }),
    });
    if (state.voiceMode && state.voiceModeTurnId === turnId) await playGeneratedAudio(generated);
  } catch (error) {
    if (!state.voiceMode || state.voiceModeTurnId !== turnId) return;
    if (window.speechSynthesis) {
      await speakBrowserText(text);
    } else if (error.status !== 503) {
      toast(error.message || conversationMessage("voicePlaybackUnavailable"));
    }
  }
}

function clearVoiceModeCapture() {
  if (state.voiceModeMonitor) window.cancelAnimationFrame(state.voiceModeMonitor);
  state.voiceModeMonitor = null;
  if (state.voiceModeAudioContext) state.voiceModeAudioContext.close().catch(() => {});
  state.voiceModeAudioContext = null;
  state.voiceModeAnalyser = null;
}

function stopVoiceMode({ silent = false } = {}) {
  const active = Boolean(state.voiceMode || state.voiceModeRecorder || state.voiceModeStream);
  state.voiceMode = false;
  state.voiceModeStatus = "off";
  state.voiceMuted = false;
  state.voiceModeCancelTurn = true;
  state.voiceModeTurnId += 1;
  clearVoiceModeCapture();
  if (state.voiceModeRecorder && state.voiceModeRecorder.state !== "inactive") {
    try { state.voiceModeRecorder.stop(); } catch { /* recorder is already closing */ }
  }
  state.voiceModeStream?.getTracks().forEach((track) => track.stop());
  state.voiceModeStream = null;
  state.voiceModeRecorder = null;
  state.audioPlayer?.pause();
  state.voiceModePlaybackFinish?.();
  state.voiceModePlaybackFinish = null;
  if (state.voiceModeSpeechResolve) state.voiceModeSpeechResolve();
  state.voiceModeSpeechResolve = null;
  window.speechSynthesis?.cancel();
  if (active && !silent) toast(translate("Memoir.storyFlow.voiceEnded"));
  if (active) render();
}

function queueVoiceModeTurn(delay = 260) {
  window.setTimeout(() => {
    if (state.voiceMode && !state.loading && !state.voiceModeRecorder) startVoiceModeTurn();
  }, delay);
}

function monitorVoiceActivity(stream, recorder, turnId) {
  const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextCtor) return;
  try {
    const context = new AudioContextCtor();
    const source = context.createMediaStreamSource(stream);
    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    source.connect(analyser);
    const samples = new Uint8Array(analyser.fftSize);
    const startedAt = performance.now();
    let speechDetected = false;
    let quietSince = 0;
    state.voiceModeAudioContext = context;
    state.voiceModeAnalyser = analyser;
    context.resume().catch(() => {});

    const tick = () => {
      if (!state.voiceMode || state.voiceModeTurnId !== turnId || state.voiceModeRecorder !== recorder || recorder.state === "inactive") return;
      if (state.voiceMuted) {
        setVoiceOrbLevel(0);
        quietSince = 0;
        state.voiceModeMonitor = window.requestAnimationFrame(tick);
        return;
      }
      analyser.getByteTimeDomainData(samples);
      let energy = 0;
      for (const sample of samples) {
        const normalized = (sample - 128) / 128;
        energy += normalized * normalized;
      }
      const rms = Math.sqrt(energy / samples.length);
      setVoiceOrbLevel(rms * 5);
      const now = performance.now();
      if (rms > 0.035) {
        speechDetected = true;
        quietSince = 0;
      } else if (speechDetected && now - startedAt > 700) {
        quietSince ||= now;
        if (now - quietSince > 1200) {
          recorder.stop();
          return;
        }
      }
      if (now - startedAt > 60_000) {
        recorder.stop();
        return;
      }
      state.voiceModeMonitor = window.requestAnimationFrame(tick);
    };
    state.voiceModeMonitor = window.requestAnimationFrame(tick);
  } catch {
    // MediaRecorder still works without activity detection; the user can end the mode manually.
  }
}

async function startVoiceModeTurn() {
  if (!state.voiceMode || state.voiceMuted || state.loading || state.voiceModeRecorder) return;
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    state.voiceMode = false;
    state.voiceModeStatus = "off";
    render();
    return toast(translate("Memoir.storyFlow.voiceConversationUnavailable"));
  }
  const turnId = state.voiceModeTurnId += 1;
  state.voiceModeCancelTurn = false;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (!state.voiceMode || state.voiceModeTurnId !== turnId) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    state.voiceModeStream = stream;
    stream.getTracks().forEach((track) => { track.enabled = !state.voiceMuted; });
    const preferredMime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((value) => window.MediaRecorder.isTypeSupported?.(value));
    const recorder = preferredMime ? new MediaRecorder(stream, { mimeType: preferredMime }) : new MediaRecorder(stream);
    state.voiceModeRecorder = recorder;
    const chunks = [];
    state.voiceModeStatus = "listening";
    recorder.addEventListener("dataavailable", (event) => { if (event.data.size) chunks.push(event.data); });
    recorder.addEventListener("stop", async () => {
      const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      if (state.voiceModeTurnId === turnId) clearVoiceModeCapture();
      stream.getTracks().forEach((track) => track.stop());
      if (state.voiceModeRecorder === recorder) state.voiceModeRecorder = null;
      if (state.voiceModeStream === stream) state.voiceModeStream = null;
      const cancelled = state.voiceModeCancelTurn || !state.voiceMode || state.voiceModeTurnId !== turnId;
      state.voiceModeCancelTurn = false;
      if (cancelled || !blob.size) {
        if (state.voiceMode) render();
        return;
      }
      state.voiceModeStatus = "processing";
      render();
      try {
        const saved = await transcribeRecordedAudio(blob, `voice-${Date.now()}`);
        if (!state.voiceMode || state.voiceModeTurnId !== turnId) return;
        if (!state.voiceMode || state.voiceModeTurnId !== turnId || !saved.text) {
          if (state.voiceMode) {
            state.voiceModeStatus = "listening";
            render();
            queueVoiceModeTurn();
          }
          return;
        }
        state.audioUploadId = saved.uploadId;
        state.audioTranscript = saved.text;
        state.audioTranscriptKind = "narrator_transcript";
        await sendChatMessage({ voiceTurn: true });
      } catch (error) {
        if (state.voiceMode) {
          toast(error.message || conversationMessage("voiceAnswerFailed"));
          state.voiceModeStatus = "listening";
          render();
          queueVoiceModeTurn();
        }
      }
    });
    recorder.start();
    render();
    monitorVoiceActivity(stream, recorder, turnId);
  } catch {
    state.voiceMode = false;
    state.voiceModeStatus = "off";
    state.voiceModeRecorder = null;
    state.voiceModeStream = null;
    render();
    toast(translate("Memoir.storyFlow.microphoneUnavailable"));
  }
}

function toggleVoiceInput() {
  if (state.voiceMode) {
    stopVoiceMode();
    return;
  }
  if (state.loading || state.dictationStatus !== "off") return;
  state.voiceMode = true;
  state.voiceModeStatus = "listening";
  state.voiceModeCancelTurn = false;
  render();
  startVoiceModeTurn();
}

function clearDictationMonitor() {
  if (state.dictationMonitor !== null) window.cancelAnimationFrame(state.dictationMonitor);
  state.dictationMonitor = null;
  state.dictationAudioContext?.close().catch(() => {});
  state.dictationAudioContext = null;
}

function monitorDictation(stream, id) {
  const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextCtor) return;
  try {
    const context = new AudioContextCtor();
    state.dictationAudioContext = context;
    const analyser = context.createAnalyser();
    analyser.fftSize = 512;
    context.createMediaStreamSource(stream).connect(analyser);
    const samples = new Uint8Array(analyser.fftSize);
    const levels = Array(40).fill(0);
    const tick = () => {
      if (state.dictationId !== id || !state.recording) return;
      analyser.getByteTimeDomainData(samples);
      const energy = samples.reduce((sum, sample) => sum + ((sample - 128) / 128) ** 2, 0);
      levels.push(Math.min(1, Math.sqrt(energy / samples.length) * 5));
      levels.shift();
      document.querySelectorAll(".dictation-wave i").forEach((bar, i) => {
        bar.style.height = `${3 + levels[i] * 23}px`;
      });
      state.dictationMonitor = window.requestAnimationFrame(tick);
    };
    context.resume().catch(() => {});
    state.dictationMonitor = window.requestAnimationFrame(tick);
  } catch {
    clearDictationMonitor();
  }
}

function cancelDictation() {
  clearDictationMonitor();
  state.dictationId += 1;
  state.dictationStatus = "off";
  state.recording = false;
  if (state.recorder?.state !== "inactive") state.recorder?.stop();
  state.recordingStream?.getTracks().forEach((track) => track.stop());
  state.recordingStream = null;
  state.recorder = null;
  state.recordedChunks = [];
  render();
}

async function finishDictation(send) {
  if (state.dictationStatus !== "recording" && state.dictationStatus !== "stopped") return;
  state.dictationSend = send;
  state.dictationStatus = "processing";
  clearDictationMonitor();
  if (state.recording) {
    state.recorder.stop();
    render();
    return;
  }
  await transcribeDictation(state.dictationId);
}

async function transcribeDictation(id) {
  render();
  let shouldSend = false;
  try {
    const blob = new Blob(state.recordedChunks, { type: state.recorder?.mimeType || "audio/webm" });
    if (!blob.size) return;
    const saved = await transcribeRecordedAudio(blob, `dictation-${Date.now()}`);
    if (state.dictationId !== id) return;
    if (state.dictationId !== id) return;
    state.audioTranscript = [state.audioTranscript.trim(), saved.text].filter(Boolean).join(" ");
    state.audioTranscriptKind = "narrator_transcript";
    shouldSend = state.dictationSend && Boolean(saved.text);
  } catch (error) { if (state.dictationId === id) toast(error.message); }
  finally {
    if (state.dictationId === id) {
      state.dictationStatus = "off";
      state.recorder = null;
      state.recordedChunks = [];
      render();
      $("#chat-input")?.focus();
    }
  }
  if (shouldSend && state.dictationId === id) await sendChatMessage();
}

async function startAudioRecorder() {
  if (state.loading || state.voiceMode || state.dictationStatus !== "off") return;
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return toast(translate("Memoir.storyFlow.browserCannotRecord"));
  const id = ++state.dictationId;
  state.dictationStatus = "starting";
  render();
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    if (state.dictationId !== id) { stream.getTracks().forEach((track) => track.stop()); return; }
    state.recordingStream = stream;
    const preferredMime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((value) => window.MediaRecorder.isTypeSupported?.(value));
    const recorder = preferredMime ? new MediaRecorder(stream, { mimeType: preferredMime }) : new MediaRecorder(stream);
    state.recorder = recorder;
    state.recordedChunks = [];
    recorder.addEventListener("dataavailable", (event) => { if (state.dictationId === id && event.data.size) state.recordedChunks.push(event.data); });
    recorder.addEventListener("stop", () => {
      stream.getTracks().forEach((track) => track.stop());
      if (state.dictationId !== id) return;
      clearDictationMonitor();
      state.recordingStream = null;
      state.recording = false;
      if (state.dictationStatus === "processing") transcribeDictation(id);
      else render();
    });
    recorder.start();
    state.recording = true;
    state.dictationStatus = "recording";
    render();
    monitorDictation(stream, id);
  } catch {
    stream?.getTracks().forEach((track) => track.stop());
    if (state.dictationId !== id) return;
    state.dictationStatus = "off";
    state.recorder = null;
    state.recordingStream = null;
    render();
    toast(translate("Memoir.storyFlow.microphoneUnavailable"));
  }
}

async function transcribeRecordedAudio(blob, filenamePrefix) {
  const encoded = await blobToBase64(blob);
  const mimeType = (blob.type || "audio/webm").split(";")[0];
  const extension = mimeType === "audio/mp4" ? "mp4" : "webm";
  const transcript = await storyApi("/v1/story/transcriptions", {
    method: "POST",
    body: JSON.stringify({ audio_base64: encoded, filename: `${filenamePrefix}.${extension}`, mime_type: mimeType, language: conversationLanguage() }),
  });
  return {
    uploadId: null,
    text: String(transcript.text || "").trim(),
    language: transcript.source?.language || "",
  };
}

function blobToBase64(blob) { return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1] || ""); reader.onerror = reject; reader.readAsDataURL(blob); }); }

async function addPerson() {
  const olderBrother = translate("Memoir.storyFlow.olderBrother");
  const name = prompt(translate("Memoir.storyFlow.whoIsThis"), olderBrother);
  if (!name) return;
  try { await api(`/v1/projects/${state.project.id}/people`, { method: "POST", body: JSON.stringify({ name, family_title: name === olderBrother ? olderBrother : null }) }); await refreshProject(); render(); } catch (error) { toast(error.message); }
}

async function addTimeline() {
  const title = prompt(translate("Memoir.storyFlow.whatHappened"), translate("Memoir.storyFlow.startedSchool"));
  if (!title) return;
  try { await api(`/v1/projects/${state.project.id}/timeline`, { method: "POST", body: JSON.stringify({ title, date_expression: "unknown", precision: "unknown" }) }); await refreshProject(); render(); } catch (error) { toast(error.message); }
}

async function boot() {
  try {
    const choice = JSON.parse(sessionStorage.getItem("memoir-package-choice") || "null");
    if (FALLBACK_STORY_PLANS.some(plan => plan.plan_key === choice?.plan)) {
      state.selectedStoryPlan = choice.plan;
      state.storyBookCount = Math.max(2, Math.min(20, Number(choice.books) || 2));
    }
  } catch { /* Ignore unavailable storage or an invalid saved selection. */ }
  state.authPromise = ensureAuth();
  try {
    await state.authPromise;
    try {
      if (await guestTransfer.complete()) toast(translate("AuthReminder.mergeSuccess"));
    } catch {
      retryConversationTransfer(() => guestTransfer.complete(), async () => {
        await guestTransfer.restoreGuest();
        window.location.reload();
      });
    }
    await syncProfileUiLocale();
    // The old five-round entry point was client-only state. Clear it so a
    // refresh always returns to the persistent Codex conversation instead of
    // reopening a fixed question card.
    localStorage.removeItem("memory-spark-story-started");
    // The interview URL identifies this page's project. The shared cache can
    // point at an older project or one opened in another tab.
    const interviewPrefix = `${MEMOIR_ROUTES.interview}/`;
    const routeProject = currentPath().startsWith(interviewPrefix)
      ? currentPath().slice(interviewPrefix.length).split("/")[0] : null;
    const saved = routeProject || localStorage.getItem("memory-spark-project");
    if (saved) {
      try {
        state.project = { id: saved };
        state.freshAnonymousSession = false;
        state.chat = restoreChatHistory(saved);
        state.chatHistoryCollapsed = true;
        await refreshProject();
        localStorage.setItem("memory-spark-project", saved);
        try { await hydrateAccountHistory(); }
        catch { toast(translate("AuthReminder.historyError")); }
        await syncProfileUiLocale();
        await hydratePlaceJourney();
        await refreshFamilyEntitlement();
        state.profileIntakePending = !profileHasContext(state.project.profile);
        if (currentPath() === MEMOIR_ROUTES.start) window.history.replaceState({}, "", `${MEMOIR_ROUTES.interview}/${saved}`);
        render();
        await startCodexConversation({ resume: true });
        return;
      }
      catch { localStorage.removeItem("memory-spark-project"); state.project = null; }
    }
    if (currentPath() === MEMOIR_ROUTES.start) window.history.replaceState({}, "", MEMOIR_ROUTES.home);
    renderLanding();
  } catch (error) {
    $("#app").innerHTML = `<div class="loading">${escapeHtml(error.message)}</div>`;
  } finally {
    state.authPromise = null;
  }
}

window.addEventListener("popstate", () => render());
window.addEventListener("copyme2:ui-locale-change", () => {
  closeProfileMenu();
  render();
});
window.addEventListener("click", (event) => {
  const menu = $("[data-profile-menu]");
  if (menu && !menu.contains(event.target)) closeProfileMenu();
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeProfileMenu(true);
});
installConversationViewport(() => {
  resizeChatInput();
  conversationScroll.refresh();
});
installUiLocaleBridge();
// Keep the shell's loading view until boot resolves the saved project.
// Rendering the landing page here flashes it before the interview is restored.
boot();
