import { $, escapeHtml, formatText } from "./dom.mjs";
import { blobToBase64 } from "./audio-utils.mjs";
import { createPhotoWorkspace } from "./photo-workspace.mjs";
import { createPlaceWorkspace, PLACE_JOURNEY_PROJECT_STORAGE_KEY } from "./place-workspace.mjs";
import { createFamilyWorkspace } from "./family-workspace.mjs";
import { createPrivateDraft } from "./private-draft.mjs";
import { createStoryCheckout, FALLBACK_STORY_PLANS } from "./story-checkout.mjs";
import { createConversationAudio } from "./conversation-audio.mjs";
import { createConversationHistory } from "./conversation-history.mjs";
import { createUiLocale, UI_LOCALES } from "./ui-locale.mjs";
import { restoreLegacyBrowserSession, signOutBrowserSession } from "../../auth/browser.mjs";
import { createBrowserClient } from "@supabase/ssr";
import { historicalContext, historicalContextMarkup, bindHistoricalControls } from "./historical-news.mjs";
import { createAuthReminder } from "./auth-reminder.js";
import { createGuestConversationTransfer } from "./guest-conversation-transfer.mjs";
import { openAttachedConversations, retryConversationTransfer } from "./conversation-attachments.js";
import {applyDerivedWorkspace} from "./derived-workspace.mjs";
import { mergePlaces, placeHistoryKey } from "./places.mjs";
import { MEMOIR_ROUTES } from "../routes.js";
import { currentUiLocale, translate, translateWith } from "../i18n.js";
import { openCollectionReview } from "./collection.js";
import { openProfileSettings } from "./profile.js";
import { createConversationScroll, installConversationViewport } from "./conversation-scroll.mjs";
import { createInterviewPhotoState } from "./interview-photo-turns.mjs";
import englishMessages from "../../messages/en-AU.json";
import chineseMessages from "../../messages/zh-CN.json";

const openingMessages = [englishMessages, chineseMessages].map(messages => messages.Memoir.conversation.opening);

const state = {
  accountId: null,
  csrfToken: "",
  project: null,
  projectPrincipalId: null,
  projectRecoveryBlocked: null,
  projectRecovery: null,
  storyStart: null,
  profileMenuScope: null,
  navigationGeneration: 0,
  navigationPath: null,
  session: null,
  memories: [],
  sources: [],
  chapters: [],
  people: [],
  relationships: [],
  timeline: [],
  stageReadiness: {},
  privateDraft: null,
  privateDraftLocale: null,
  memoryEventPage: null,
  pendingConversationTurn: null,
  preview: null,
  chat: [],
  chatHistoryCollapsed: false,
  freshAnonymousSession: false,
  codexStarting: false,
  codexReady: false,
  showThinkingSteps: false,
  showDraftUpdates: false,
  privateDraftExpanded: false,
  profileIntakePending: true,
  placeJourney: null,
  placeJourneyChange: null,
  workspaceTab: "memoir",
  selectedMemoirChapter: null,
  selectedFamilyPerson: null,
  familyPhotoTask: null,
  photoMemoryTask: null,
  photoMemoryRevision: 0,
  photoFavoritesOpen: false,
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
  audioRecordings: [],
  pendingAudioUpload: null,
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

state.photoTurns = createInterviewPhotoState({state, scope:captureProjectScope, render, api,
  onRecovered: async (turn, receipt) => {
    markWorkspaceFocusStarted(turn);
    const saved = {role:"assistant", text:receipt.reply, clientTurnId:turn.id,
      historicalContext:receipt.historical_context ? historicalContext(receipt.historical_context) : null, responsePhotos:receipt.response_photos, streaming:false, error:"", failed:false};
    const existing = state.chat.find(message => message.clientTurnId === turn.id && message.role === "assistant");
    if (existing) Object.assign(existing, saved);
    else state.chat.push({id:nextAssistantMessageId(), ...saved});
    state.pendingConversationTurn = null;
    persistChatHistory();
  },
});

const guestTransfer = createGuestConversationTransfer({
  getAuth: () => state.supabase,
  getConversation: () => ({
    project_id: state.project?.id || savedProjectId() || "guest-conversation",
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
  getRedirectTo: () => window.location.origin + window.location.pathname,
  onMerged: async result => {
    const scope = uiPreferenceSession.capture();
    const { data, error } = await state.supabase.client.auth.getUser();
    if (error) throw error;
    if (!uiPreferenceSession.current(scope) || data?.user?.id !== scope.viewer) return;
    if (data?.user) state.supabase.user = data.user;
    uiPreferenceSession.setSession(state.supabase.client, state.supabase.user);
    await syncAccountUiLocale();
    const transferredLocale = result.ui_locale || result.profile?.preferred_language;
    if (uiPreferenceSession.current(scope) && !uiPreferenceSession.preference && UI_LOCALES.has(transferredLocale)) {
      await globalThis.__copyme2SetUiLocale?.(transferredLocale, {persistAccount:true, persistCookie:true, source:"first_reply"});
    }
  },
});

const authReminder = createAuthReminder({
  getAuth: () => state.supabase,
  getConversation: () => ({ id: state.project?.id, messages: state.chat }),
  busy: () => state.loading || state.recording || state.storyRecording || state.voiceMode || state.dictationStatus !== "off",
  signInExisting: provider => guestTransfer.signIn(provider),
  cancelTransfer: () => guestTransfer.cancel(),
  onUserChanged: () => refreshProfileMenu(),
});

const MEMOIR_API_PREFIX = "/api/v1/memoir";
let workspaceUpdateQueue = Promise.resolve();
const appliedWorkspaceSequences = new Map();
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

const {
  nextAssistantMessageId, persistChatHistory, rememberProject, restoreChatHistory, savedProjectId
} = createConversationHistory({
  cleanAssistantText, state
});

const {
  applyFirstReplyLocalization, applyProfileUiLocale, clearDerivedUiPreference, currentUiPreference, firstReplyLanguage,
  installUiLocaleBridge, persistCommittedFirstReplyUiLocale, readCookie, syncAccountUiLocale,
  settleUiLocale, syncProfileUiLocale, uiPreferenceSession
} = createUiLocale({
  captureProjectScope, isCurrentProjectScope, preserveConversationLocale, profile, state, storyApi, toast
});

// Resolve the map lazily: photos and maps share the same place state.
const photos = createPhotoWorkspace({
  state, api, profile, render, toast, captureProjectScope, isCurrentProjectScope, loadPlacePictures,
  placeMapTarget: journey => placeMapTarget(journey),
});

const {
  bindPhotoMemoryActions, bindPhotoPagination, mergePlacePictures, photoMatchesScope, photoRequestKey,
  photoSearchPeriod, placePhotoCenter, responsePhotoMarkup, searchedPictures, selectedPhotoCue
} = photos;

const {
  disposeCesiumPlaceJourney, hydratePlaceJourney, initCesiumPlaceJourney, loadCesium, mapPhotoAlbums,
  placeJourneySurface, placeMapTarget, placeWorkspaceSelection, rememberPlaceJourneyProject, resolvePlaceMap,
  selectPlace, workspaceMediaOverview, resizeCesiumPlaceJourney
} = createPlaceWorkspace({
  api, captureProjectScope, isCurrentProjectScope, lifeStageText, loadPlacePictures, persistChatHistory,
  profile, recordWorkspaceSkillProgress, render, saveProfileUpdates, state, supabaseApi, workspaceHasContent,
  photos
});

const {
  currentSectionRework, decidePrivateDraftProposal, loadMorePrivateDraft, openSectionRework,
  privateDraftPreview, refreshPrivateDraft, retryPrivateDraft, selectPrivateDraftLocale, submitSectionRework
} = createPrivateDraft({
  captureProjectScope, freeRecallFinished, isCurrentProjectScope, memoirApiPath, persistChatHistory, profile,
  render, state, storyApi, updateStreamingAssistantMessage
});

const {
  addPerson, applyPersistedFamilyContext, closeFamilyPerson, familyWorkspace, initFamilyVisualizations,
  loadMoreEventDetails, loadMoreEventEvidence, loadMoreMemoryEvents, openMemoryEventEdit, refreshFamilyContext,
  saveFamilyPersonPhoto, saveMemoryEventEdit, selectFamilyPerson, timelineWorkspace, zoomFamilyChart
} = createFamilyWorkspace({
  LIFE_STAGES, api, captureProjectScope, isCurrentProjectScope, lifeStageText, profile, referencesWorkspace,
  refreshPrivateDraft, refreshProject, render, state, storyApi, supabaseApi, toast
});

const {
  refreshStoryState, requestStoryCheckout, storyCheckoutForm
} = createStoryCheckout({
  authReminder, render, state, storyApi, toast
});

const {
  cancelDictation, discardAudioDraft, finishDictation, queueVoiceModeTurn, speakText, speakVoiceReply, startAudioRecorder,
  startVoiceModeTurn, stopVoiceMode, toggleVoiceInput
} = createConversationAudio({
  captureProjectScope, cleanAssistantText, conversationLanguage, conversationMessage, isCurrentProjectScope,
  render, sendChatMessage, state, storyApi, toast
});

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
  ORIGINAL_RECORDINGS_DISABLED:'recordingRetentionDisabled',
  RECORDING_AUTHORITY_REQUIRED:'recordingAuthorityRequired',
  RECORDING_PRESERVATION_FAILED:'recordingNotSavedRetry',
  RECORDING_TRANSCRIPTION_FAILED:'recordingSavedRetry',
  RECORDING_TRANSCRIPTION_UNCERTAIN:'recordingSavedRetry',
  INVALID_AUDIO_MEDIA:'invalidAudio',
  UNSUPPORTED_AUDIO:'invalidAudio',
  AUDIO_DURATION_EXCEEDED:'recordingLimit',
  AUDIO_TOO_LARGE:'recordingLimit',
  PAYMENT_REQUIRED: "paymentRequired",
  ENTITLEMENT_REQUIRED: "entitlementRequired",
  INVALID_AUDIO_PAYLOAD: "invalidAudio",
  ALREADY_PAID: "alreadyPaid",
  INVALID_STRIPE_ORDER: "invalidCheckout",
  STRIPE_ORDER_MISMATCH: "stripeMismatch",
  SESSION_EXPIRED: "sessionExpired",
  WORKSPACE_MEMORY_FOCUS_STALE: "WORKSPACE_MEMORY_FOCUS_STALE",
  WORKSPACE_SECTION_REWORK_STALE: "WORKSPACE_SECTION_REWORK_STALE",
};

function localizedErrorMessage(code) {
  const key = ERROR_MESSAGE_KEYS[code] || "generic";
  return translate(`Errors.${key}`);
}

function currentPath() {
  return window.location.pathname.replace(/\/$/, "") || "/";
}

function navigateTo(path, replace = false) {
  invalidateProjectNavigation();
  window.history[replace ? "replaceState" : "pushState"]({}, "", path);
  state.navigationPath = currentPath();
  render();
}

function captureProjectScope() {
  return { projectId: state.project?.id, ownerId: state.supabase?.user?.id,
    generation: state.navigationGeneration || 0 };
}

function isCurrentProjectScope(scope) {
  return scope.generation === (state.navigationGeneration || 0)
    && scope.projectId === state.project?.id && scope.ownerId === state.supabase?.user?.id;
}

function invalidateProjectNavigation() {
  // Save accepted text before detaching the transport. Aborting a browser
  // request does not undo a turn already accepted by the server.
  for (const message of state.chat) if (message.streaming) message.streaming = false;
  persistChatHistory();
  state.navigationGeneration = (state.navigationGeneration || 0) + 1;
  state.projectRecovery?.finish();
  state.profileMenuScope = null;
  for (const stream of state.conversationStreams || []) stream.abort();
  state.conversationStreams?.clear();
  state.privateDraftStream?.controller.abort();
  state.privateDraftStream = null;
  state.stageReadinessRefresh?.controller.abort();
  state.privateDraftExpanded = false;
  state.photoRequests?.clear();
  state.pendingConversationTurn = null;
  state.photoTurns?.clearDisplay();
  state.photoMemoryTask = null;
  state.photoFavoritesOpen = false;
  state.loading = false;
  state.codexStarting = false;
  if (state.voiceMode || state.voiceModeRecorder || state.voiceModeStream) stopVoiceMode({ silent: true });
  if (state.dictationStatus && state.dictationStatus !== "off") cancelDictation();
  return state.navigationGeneration;
}

async function api(path, options = {}) {
  const { onPhotoPage, ...requestOptions } = options;
  const method = (options.method || "GET").toUpperCase();
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.supabase?.accessToken && !headers.Authorization
      && path !== '/v1/projects' && !path.startsWith('/v1/auth/')) {
    headers.Authorization = `Bearer ${state.supabase.accessToken}`;
  }
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
    error.detail = body.detail;
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

async function ensureAuth() {
  await loadSupabaseConfig();
  if (state.supabase?.auth_mode === "test") {
    syncSupabaseSession({ access_token: "browser-test-token", refresh_token: null, user: { is_anonymous: true } });
    return;
  }
  if (!state.supabase?.client) throw new Error(translate("Errors.supabaseNotConfigured"));
  const authScope = uiPreferenceSession.capture();
  let session;
  try { session = await restoreLegacyBrowserSession(state.supabase.client, state.supabase.supabase_url, globalThis.localStorage); }
  catch { throw new Error(translate("Errors.sessionUnavailable")); }
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
  if (!uiPreferenceSession.current(authScope) && uiPreferenceSession.viewer !== (session?.user?.id || null)) return;
  syncSupabaseSession(session);
  await syncAccountUiLocale();
}

async function loadSupabaseConfig() {
  const response = await fetch(memoirApiPath("/v1/agent/config"));
  const config = await response.json();
  state.showThinkingSteps = config.show_thinking_steps === true &&
    ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);
  state.showDraftUpdates = config.show_draft_updates === true &&
    ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);
  if (config.auth_mode === "test") {
    state.supabase = config;
    return;
  }
  if (!config.supabase_url || !config.supabase_publishable_key) {
    state.supabase = config;
    return;
  }
  const client = createBrowserClient(config.supabase_url, config.supabase_publishable_key, {
    cookieOptions: { path: "/", sameSite: "lax", secure: window.location.protocol === "https:" },
  });
  state.supabase = { ...config, client };
  client.auth.onAuthStateChange((_event, session) => {
    syncSupabaseSession(session);
    // Do not await another Auth call inside its locked callback.
    setTimeout(() => { syncAccountUiLocale().catch(() => {}); }, 0);
    if (state.story && session) refreshStoryState().catch(() => {});
  });
}

function syncSupabaseSession(session) {
  state.supabaseSession = session || null;
  if (!state.supabase) return;
  const previousUser = state.supabase.user;
  const principalChanged = Boolean(previousUser?.id && previousUser.id !== session?.user?.id);
  if (principalChanged) { clearDerivedUiPreference(); invalidateProjectNavigation(); }
  state.supabase.accessToken = session?.access_token || null;
  state.supabase.refreshToken = session?.refresh_token || null;
  state.supabase.user = session?.user || null;
  uiPreferenceSession.setSession(state.supabase.client, state.supabase.user);
  if (principalChanged) {
    // Keep the previous principal's durable cache, and let boot authorize the
    // next principal before any project or transcript can be shown again.
    state.project = null;
    state.projectPrincipalId = null;
    state.chat = [];
    globalThis.document?.querySelector("#app")?.replaceChildren();
    if (!state.explicitSignOutInProgress) globalThis.location?.reload();
  }
  authReminder.tick();
  const user = state.supabase.user;
  if (previousUser?.id !== user?.id || previousUser?.is_anonymous !== user?.is_anonymous
      || previousUser?.email !== user?.email
      || previousUser?.user_metadata?.full_name !== user?.user_metadata?.full_name
      || previousUser?.user_metadata?.name !== user?.user_metadata?.name) refreshProfileMenu();

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

async function supabaseOAuthSignIn(provider) {
  try {
    if (state.authPromise) await state.authPromise;
    if (state.loading) return;
    if (!state.supabase?.client) return toast(translate("Errors.supabaseNotConfigured"));
    if (state.supabase.user?.is_anonymous && state.project) {
      await guestTransfer.signIn(provider);
      return;
    }
    const { error } = await state.supabase.client.auth.signInWithOAuth({
      provider,
      options: {
        redirectTo: `${window.location.origin}${MEMOIR_ROUTES.start}`,
        ...(provider === "google" ? { queryParams: { prompt: "consent select_account" } } : {}),
      },
    });
    if (error) throw error;
  } catch {
    toast(translate("Errors.authFailed"));
  }
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

async function agentTurn(text, fallback = "", toolNames = ["memory.search"], language = conversationLanguage(), firstReplyLocalization = false, conversationText = undefined, serverAction = null, sourceKind = "narrator_chat", photoOptions = {}) {
  if (!photoOptions.retry && state.photoTurns?.pending()?.accepted) throw new Error(translate("Memoir.story.retryTurn"));
  const scope = captureProjectScope();
  const controller = globalThis.AbortController ? new AbortController() : null;
  const current = () => isCurrentProjectScope(scope) && !controller?.signal.aborted;
  const detached = () => ({ detached: true });
  let replyFinished = false;
  const simulated = simulatedLoopTrace(toolNames);
  if (!state.supabase?.accessToken) return { reply: fallback || null, trace: simulated, traceMode: "simulated" };
  let streamedMessage = null;
  const liveTrace = [];
  const streamProjectId = state.project?.id || null;
  const ownerId = state.supabase?.user?.id;
  const previousTurn = state.pendingConversationTurn;
  const requestTurn = state.photoTurns?.prepare({text, conversationText, sourceKind, language,
    firstReplyLocalization, serverAction, workspaceFocus: serverAction ? null : workspaceTurnFocus(), ...photoOptions}) || (previousTurn?.projectId === streamProjectId && previousTurn?.ownerId === ownerId
      && previousTurn?.text === text ? previousTurn : {projectId:streamProjectId,ownerId,text,
      id:globalThis.crypto?.randomUUID?.() || null});
  state.pendingConversationTurn = requestTurn;
  if (photoOptions.retry) {
    streamedMessage = state.chat.find(message => message.clientTurnId === requestTurn.id && message.role === "assistant") || null;
    if (streamedMessage) Object.assign(streamedMessage, {text:"", streaming:true, error:"", failed:false});
  }
  const previousJourney = state.placeJourney;
  const previousSelection = state.selectedPlace;
  let previewJourney = null;
  const recordProgress = (step) => {
    if (!current() || !step?.id) return;
    const index = liveTrace.findIndex(item => item.id === step.id);
    if (index < 0) liveTrace.push(step);
    else if (step.status === "completed" || step.status === "failed") {
      liveTrace.splice(index, 1);
      liveTrace.push(step);
    } else liveTrace[index] = step;
    if (!streamedMessage) {
      streamedMessage = { id: nextAssistantMessageId(), clientTurnId:requestTurn.id, role: "assistant", text: "", streaming: true };
      state.chat.push(streamedMessage);
    }
    streamedMessage.trace = liveTrace;
    streamedMessage.traceMode = "live";
    updateStreamingAssistantMessage(streamedMessage);
  };
  if (state.supabase.google_maps_browser_api_key) void loadCesium().catch(() => {});
  try {
    const applyWorkspace = async (update) => {
      if (!current()) return;
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
        resolvePlaceMap(previewJourney, {onProgress: recordProgress});
        render();
        return;
      }
      if (update.profile_updates && markCurrent("profile")) {
        await saveProfileUpdates(update.profile_updates, streamProjectId);
        if (!current()) return;
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
          // Keep explicit place stages, plus profile chronology, ahead of
          // mention order when a turn contains several places.
          const candidates = (update.place_journeys?.length ? update.place_journeys : [update.place_journey])
            .map(journey => ({ period: "", life_stage: null, ...journey }));
          const places = mergePlaces([...(profile().memory_places || []), ...candidates], profile(), [{role: 'user', text}]);
          const entries = candidates.map(candidate => places.find(item => placeHistoryKey(item) === placeHistoryKey(candidate)));
          const entry = entries.at(-1);
          await saveProfileUpdates({ memory_places: places }, streamProjectId);
          if (!current()) return;
          if (entry) state.placeJourney = entry;
          state.lifeStage = "all";
          state.selectedPlace = placeHistoryKey(entry);
          rememberPlaceJourneyProject(streamProjectId);
          // Discovery can take much longer than the saved place update.
          // Render the map and loading panel while it runs independently.
          for (const place of entries) {
            resolvePlaceMap(place, {onProgress: recordProgress});
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
      if (!current() || replyFinished) return;
      if (!streamedMessage) {
        streamedMessage = { id: nextAssistantMessageId(), clientTurnId:requestTurn.id, role: "assistant", text: "", streaming: true };
        state.chat.push(streamedMessage);
        render();
      }
      streamedMessage.text += delta;
      updateStreamingAssistantMessage(streamedMessage);
    }, async (event) => {
      if (!current()) return;
      if (event.type === "progress") {
        recordProgress(event.data);
      } else if (event.type === "source_accepted") {
        state.photoTurns?.accept(requestTurn, {...event.data, state:"source_accepted"});
        markWorkspaceFocusStarted(requestTurn);
      } else if (event.type === "conversation_saved") {
        state.photoTurns?.accept(requestTurn, {...event.data, state:"conversation_saved"});
        void refreshStageReadiness();
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
          .catch((error) => { if (current()) toast(error.message); });
      }
    }, language, firstReplyLocalization, conversationText, requestTurn.id, serverAction, sourceKind, {scope, controller, turn:requestTurn});
    if (!current()) return detached();
    replyFinished = true;
    // A saved reply is ready even when an earlier workspace write is pending.
    // Legacy responses still need their bundled workspace applied here.
    if (!body.conversation_saved) {
      workspaceUpdateQueue = workspaceUpdateQueue.then(() => applyWorkspace(body));
      await workspaceUpdateQueue;
      if (!current()) return detached();
    }
    if (body.profile_updates?.conversation_language && state.project?.id === streamProjectId && state.supabase?.user?.id === ownerId) {
      await applyCommittedConversationLocale(body.profile_updates);
      if (!current()) return detached();
    }
    if (body.recall_status) state.recallStatus = body.recall_status;
    if (body.conversation_saved) markWorkspaceFocusStarted(requestTurn);
    if (body.reply && state.pendingConversationTurn === requestTurn) state.pendingConversationTurn = null;
    if (body.conversation_saved) {
      state.backgroundDraftTurn = requestTurn.id;
      void refreshStageReadiness();
      void refreshPrivateDraft();
    }
    if (state.recallStatus && freeRecallFinished()) void ensureRecallPreview();
    if (state.recallStatus?.payment_required && state.voiceMode) stopVoiceMode({ silent: true });
    if (!streamedMessage && body.reply) {
      // Compatibility responses may contain the entire reply in one event.
      // They are already complete; do not replay them as simulated typing.
      streamedMessage = { id: nextAssistantMessageId(), clientTurnId:requestTurn.id, role: "assistant", text: body.reply, streaming: false };
      state.chat.push(streamedMessage);
      render();
    }
    if (streamedMessage) {
      streamedMessage.clientTurnId = requestTurn.id;
      streamedMessage.responsePhotos = state.photoTurns?.cards(body.response_photos);
      streamedMessage.historicalContext = body.historical_context ? historicalContext(body.historical_context) : null;
      if (body.reply) streamedMessage.text = body.reply;
    }
    // Persist the final visible reply and its cards before dropping the receipt
    // recovery key. Optional locale/workspace calls above may be interrupted.
    state.photoTurns?.finish(requestTurn, body);
    return { historicalContext:body.historical_context ? historicalContext(body.historical_context) : null, responsePhotos:state.photoTurns?.cards(body.response_photos), clientTurnId:requestTurn.id, blocked: body.recall_status?.payment_required && !body.reply, streamedMessage, reply: body.reply || fallback || null, trace: liveTrace.length ? liveTrace : (body.trace || []), traceMode: liveTrace.length ? "live" : (body.trace_mode || "codex"), placeJourney: body.place_journey || null, placeJourneyChange: body.place_journey_change || null, familyContextUpdate: body.family_context_update || null };
  } catch (error) {
    if (!current()) return detached();
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
    return { failed:true, streamedMessage, reply: streamedMessage?.text || error.message, trace: liveTrace.map(step => ({ ...step, status: step.status === "running" ? "failed" : step.status })), traceMode: "error" };
  }
}

async function streamAgentTurn(text, onDelta, onEvent = async () => {}, language = conversationLanguage(), firstReplyLocalization = false, conversationText = undefined, clientTurnId = undefined, serverAction = null, sourceKind = "narrator_chat", request = {}) {
  const scope = request.scope || captureProjectScope();
  const controller = request.controller || (globalThis.AbortController ? new AbortController() : null);
  const current = () => isCurrentProjectScope(scope) && !controller?.signal.aborted;
  if (controller) (state.conversationStreams ||= new Set()).add(controller);
  let responseHasStream = false;
  try {
  const isGreeting = serverAction === "begin" || serverAction === "continue";
  const body = isGreeting
    ? { action: serverAction, client_turn_id: clientTurnId || undefined, project_id: scope.projectId || null, language, first_reply_localization: firstReplyLocalization }
    : { text, conversation_text: conversationText, source_kind: sourceKind, client_turn_id: clientTurnId || undefined, project_id: scope.projectId || null, language, first_reply_localization: firstReplyLocalization };
  if (!isGreeting && request.turn) {
    Object.assign(body, {text:request.turn.text, conversation_text:request.turn.conversationText,
      source_kind:request.turn.sourceKind, recording_ids:request.turn.recordingIds || [], uploaded_photo_ids:request.turn.uploadedPhotoIds || [],
      photo_selection:request.turn.photoSelection || null, workspace_focus:request.turn.workspaceFocus || null});
  }
  const response = await fetch(memoirApiPath(isGreeting ? "/v1/agent/greeting" : "/v1/agent/turn"), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/x-ndjson",
      Authorization: `Bearer ${state.supabase.accessToken}`,
      "X-CSRF-Token": state.csrfToken || readCookie("memory_spark_csrf") },
    body: JSON.stringify(body),
    signal: controller?.signal,
  });
  if (!current()) throw new Error("Conversation navigation changed");
  if (response.status === 401) {
    state.supabase.accessToken = null;
    throw new Error(translate("Errors.sessionExpired"));
  }
  if (!response.ok) throw new Error(localizedErrorMessage(response.headers.get("X-Error-Code")));
  if (!response.body) return await response.json();
  const reader = response.body.getReader();
  responseHasStream = true;
  const cancelReader = () => { void reader.cancel().catch(() => {}); };
  controller?.signal.addEventListener("abort", cancelReader, { once: true });
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
      if (!current()) throw new Error("Conversation navigation changed");
      const end = jsonObjectEnd(buffer);
      if (end === null) {
        if (final) throw new Error("Incomplete streaming response");
        return;
      }
      const value = buffer.slice(0, end);
      buffer = buffer.slice(end);
      const event = JSON.parse(value);
      if (event.type === "text_delta" && !ready) await onDelta(event.text || "");
      else if (event.type === "source_accepted") await onEvent(event);
      else if (event.type === "reply_complete") result = { ...(result || {}), ...(event.data || {}) };
      else if (event.type === "conversation_saved") {
        if (event.data?.photo_cue || event.data?.response_photos || event.data?.conversation_phase) await onEvent(event);
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
      if (!current()) throw new Error("Conversation navigation changed");
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
        if (current()) await onEvent({ type: "workspace_error", message: error.message });
      }
    } finally {
      controller?.signal.removeEventListener("abort", cancelReader);
      await reader.cancel().catch(() => {});
      reader.releaseLock();
      if (controller) state.conversationStreams?.delete(controller);
    }
  };
  void consumeStream();
  // Keep the controller registered until the background workspace tail ends.
  return await readyPromise;
  } finally {
    // The reader owns cleanup once it exists; failed fetches and JSON replies
    // have no background tail to detach.
    if (controller && !responseHasStream) state.conversationStreams?.delete(controller);
  }
}

function recordWorkspaceSkillProgress(step, onProgress = null) {
  if (onProgress) onProgress(step);
  else {
    const message = (state.chat || []).findLast(item => item.role === "assistant"
      && item.trace?.some(previous => previous.id === step.id));
    if (!message) return;
    message.trace[message.trace.findIndex(previous => previous.id === step.id)] = step;
    message.traceMode = "live";
    updateStreamingAssistantMessage(message);
  }
  // Background work often finishes after the reply's normal history save.
  persistChatHistory();
}

async function loadPlacePictures(entry, projectId, { more = false, force = false, onProgress = null } = {}) {
  const requestScope = captureProjectScope();
  if (!projectId || !entry?.place) return;
  if (requestScope.projectId !== projectId) return;
  const key = placeHistoryKey(entry);
  entry = (profile().memory_places || []).find(item => placeHistoryKey(item) === key) || entry;
  const period = photoSearchPeriod(entry, profile().story_focus);
  const parents = (entry.hierarchy || []).filter(label => label && label !== entry.place && label !== "Earth");
  const parent = ["suburb", "landmark"].includes(entry.granularity) ? parents.at(-1) : "";
  const searchPlace = parent && !entry.place.includes(parent) ? `${entry.place}, ${parent}` : entry.place;
  const center = placePhotoCenter(entry);
  const samePlace = placeHistoryKey({place: entry.photo_search_place || entry.place}) === placeHistoryKey({place: searchPlace});
  const sameCenter = !center || (entry.photo_search_latitude === center.latitude && entry.photo_search_longitude === center.longitude);
  const sameSearch = entry.photo_search_period === period && samePlace && sameCenter
    && entry.photo_search_policy === "place-fallback-gps-time-v9";
  const requestKey = photoRequestKey(entry, projectId);
  const reportProgress = (status, label, failures = []) => {
    const safeFailures = (Array.isArray(failures) ? failures : []).filter(item => item
      && ["flickr", "google", "loc", "commons", "llm"].includes(item.provider)
      && /^(?:robots_denied|verification_required|timeout|network_error|invalid_response|unavailable|http_\d{3})$/.test(item.reason))
      .map(({provider, reason}) => ({provider, reason}));
    recordWorkspaceSkillProgress({id: `photos:${requestKey}`, kind: "skill", skill: "place-photo-research",
      label: "place-photo-research", status, place: entry.place, period, failures: safeFailures,
      detail: `${translate(`Memoir.workspace.${label}`)} · ${entry.place}${period ? ` · ${period}` : ""}`
        + (safeFailures.length ? ` · ${safeFailures.map(item => `${item.provider}: ${item.reason}`).join("; ")}` : "")}, onProgress);
  };
  if (more && (!sameSearch || !entry.photo_next_cursor)) return;
  if (!more && !force && sameSearch && ((entry.pictures || []).length
      || entry.photo_search_complete || (Object.hasOwn(entry, "photo_next_cursor")
        && entry.photo_search_policy === "place-fallback-gps-time-v9" && entry.photo_search_at > 0))) {
    reportProgress("completed", (entry.pictures || []).length ? "picturesCached" : "picturesNoMatch");
    return;
  }
  state.photoRequests ||= new Map();
  if (state.photoRequests.get(requestKey)?.loading) return;
  state.photoRequests.set(requestKey, { loading: true });
  let photoStatus = "SEARCHING";
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
      if (!isCurrentProjectScope(requestScope)) return;
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
        if (!isCurrentProjectScope(requestScope)) return;
        const places = [...(profile().memory_places || [])];
        const index = places.findIndex(item => placeHistoryKey(item) === key);
        const latest = index >= 0 ? places[index] : entry;
        if (photoSearchPeriod(latest, profile().story_focus) !== period) return;
        if (photoRequestKey(latest, projectId) !== requestKey) return;
        const latestCenter = placePhotoCenter(latest);
        if (center && latestCenter && (center.latitude !== latestCenter.latitude || center.longitude !== latestCenter.longitude)) return;
        const resultCenter = result.search_center || center;
        const scope = {...latest, photo_search_place: searchPlace, ...(resultCenter ? {photo_search_latitude: resultCenter.latitude,
          photo_search_longitude: resultCenter.longitude} : {})};
        const pictures = mergePlacePictures(latest.photo_search_period === period
          && placeHistoryKey({place: latest.photo_search_place || latest.place}) === placeHistoryKey({place: searchPlace})
          && latest.photo_search_policy === "place-fallback-gps-time-v9" ? latest.pictures || [] : [], result.items)
          .filter(picture => photoMatchesScope(picture, scope, profile().story_focus));
        const updatedEntry = { ...latest, pictures, photo_search_period: period,
          ...(resultCenter ? {photo_search_latitude: resultCenter.latitude, photo_search_longitude: resultCenter.longitude} : {}),
          photo_search_place: searchPlace,
          photo_next_cursor: result.next_cursor || null,
          photo_search_at: result.searching ? 0 : Date.now(),
          photo_search_status: result.status || ((result.items || []).length ? "PARTIAL" : "NO_MATCH"),
          photo_search_complete: !result.searching,
          photo_search_policy: "place-fallback-gps-time-v9" };
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
      if (!isCurrentProjectScope(requestScope)) return;
      if (!more || error.status !== 410) throw error;
      query.delete("cursor");
      result = await api(`/v1/projects/${projectId}/place-photos?${query}`, options);
    }
    // JSON-only servers and cached responses retain the existing contract.
    if (!deliveredFinal) await acceptPage(result);
  } catch { /* Pictures are optional; retry explicitly without erasing them. */
    if (!isCurrentProjectScope(requestScope)) return;
    state.photoRequests.set(requestKey, { error: true });
  } finally {
    if (!isCurrentProjectScope(requestScope)) return;
    state.photoRequests.set(requestKey, {...state.photoRequests.get(requestKey), loading: false});
    const failed = state.photoRequests.get(requestKey)?.error;
    reportProgress(failed ? "failed" : "completed",
      failed ? "picturesUnavailable" : photoStatus === "NO_MATCH" ? "picturesNoMatch" : "pictures",
      state.photoRequests.get(requestKey)?.failures || []);
    if (state.project?.id === projectId) render();
  }
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
  const scope = metadata.scope || captureProjectScope();
  const current = () => isCurrentProjectScope(scope);
  if (!current()) return null;
  const { scope: _scope, ...messageMetadata } = metadata;
  if (messageMetadata.streamedMessage) {
    const { streamedMessage, ...details } = messageMetadata;
    if (!state.chat.includes(streamedMessage)) return null;
    Object.assign(streamedMessage, details, { text: cleanAssistantText(String(text || streamedMessage.text)), streaming: false });
    render();
    return streamedMessage;
  }
  const value = cleanAssistantText(String(text || ""));
  if (!value) return null;
  const message = {
    ...messageMetadata,
    id: nextAssistantMessageId(),
    role: "assistant",
    text: "",
    streaming: true,
  };
  state.chat.push(message);
  render();

  const characters = Array.from(value);
  for (let index = 0; index < characters.length; index += ASSISTANT_STREAM_CHUNK_SIZE) {
    if (!current()) return null;
    message.text = characters.slice(0, index + ASSISTANT_STREAM_CHUNK_SIZE).join("");
    updateStreamingAssistantMessage(message);
    if (index + ASSISTANT_STREAM_CHUNK_SIZE < characters.length) await waitForAssistantStream();
  }
  if (!current()) return null;
  message.text = value;
  message.streaming = false;
  render();
  return message;
}

async function refreshFamilyEntitlement() {
  const scope = captureProjectScope();
  try {
    const entitlement = await storyApi("/v1/story/state");
    if (!isCurrentProjectScope(scope)) return false;
    const features = new Set(entitlement.payment_features || []);
    state.familyEntitlement = entitlement;
    state.recallStatus = entitlement.recall_status || null;
    // Project hydration can finish its draft read before restored allowance is
    // known. Recheck once eligibility arrives, without delaying the interview.
    if (freeRecallFinished() && !state.showDraftUpdates) void refreshPrivateDraft();
    if (freeRecallFinished()) void ensureRecallPreview();
    state.familyFeaturesEnabled = entitlement.family_features_enabled === true
      && features.has("family_tree")
      && features.has("timeline");
    if (!state.familyFeaturesEnabled) {
      state.familyContext = null;
    } else {
      await refreshFamilyContext();
    }
  } catch {
    if (!isCurrentProjectScope(scope)) return false;
    state.familyEntitlement = null;
    state.familyFeaturesEnabled = false;
    state.familyContext = null;
  }
  return state.familyFeaturesEnabled;
}

async function startCodexConversation({ resume = false } = {}) {
  const scope = captureProjectScope();
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
        scope,
        trace: simulatedLoopTrace(
          ["conversation.start", "memory.search"],
          translate("Memoir.trace.opening"),
        ),
        traceMode: "simulated",
      });
    } finally {
      if (!isCurrentProjectScope(scope)) return;
      state.codexStarting = false;
      state.codexReady = true;
      // The first answer can start while this fixed opening is painting.
      // Its generated turn owns loading until save or controlled failure.
      render();
    }
    return;
  }

  state.loading = true;
  render();
  const fallback = conversationMessage("resume");
  try {
    // Returning to saved memories is navigation, not a new recall round.
    const message = await streamAssistantMessage(fallback, { scope, traceMode: "simulated" });
    if (!isCurrentProjectScope(scope)) return;
    if (message) render();
  } finally {
    if (!isCurrentProjectScope(scope)) return;
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
  updates = preserveConversationLocale(updates, current);
  const next = { ...current };
  if (updates.profile_automation) next.profile_automation = updates.profile_automation;
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
  const scope = captureProjectScope();
  if (!updates || !state.project || (expectedProjectId && state.project.id !== expectedProjectId)) return;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    if (!isCurrentProjectScope(scope)) return;
    if (!state.project || (expectedProjectId && state.project.id !== expectedProjectId)) return;
    const project = state.project;
    const merged = mergeProfileUpdates(updates) || (force ? { ...profile(), ...updates } : null);
    if (!merged) return;
    state.project = { ...project, profile: merged };
    state.profileIntakePending = false;
    try {
      const persistedProfile = { ...merged };
      delete persistedProfile.profile_automation;
      const saved = await api(`/v1/projects/${project.id}`, {
        method: "PATCH",
        body: JSON.stringify({ profile: persistedProfile, expected_revision: project.revision }),
      });
      if (!isCurrentProjectScope(scope)) return;
      if (state.project?.id === project.id) state.project = { ...state.project, ...saved,
        profile: { ...preserveConversationLocale(saved.profile, state.project.profile), ...(state.project.profile?.photo_memories ? {
          photo_memories:state.project.profile.photo_memories} : {}), ...(state.project.profile?.conversation_language ? {
          preferred_language:state.project.profile.preferred_language, conversation_language:state.project.profile.conversation_language} : {}) } };
      return;
    } catch (error) {
      if (!isCurrentProjectScope(scope)) return;
      if (error.status === 409 && attempt === 0 && state.project?.id === project.id) {
        // Another serialized workspace update may have advanced the project
        // revision. Reload the base profile and retry the same explicit fields.
        const latest = await api(`/v1/projects/${project.id}`);
        if (!isCurrentProjectScope(scope)) return;
        if (state.project?.id === project.id) state.project = { ...state.project, ...latest,
          profile: { ...preserveConversationLocale(latest.profile, state.project.profile),
            ...(state.project.profile?.photo_memories ? {photo_memories:state.project.profile.photo_memories} : {}) } };
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
  await persistCommittedFirstReplyUiLocale(profile());
  await applyProfileUiLocale(conversationLanguage());
}

function preserveConversationLocale(incoming = {}, current = {}) {
  const authority = current.profile_automation;
  if (Number(authority?.revision || 0) > Number(incoming.profile_automation?.revision || 0)) {
    incoming = { ...incoming, profile_automation: authority };
    for (const key of ['name', 'birth_year', 'birth_date_expression', 'birth_place', 'childhood_place', 'avatar_style']) {
      if (Object.hasOwn(current, key)) incoming[key] = current[key];
      else delete incoming[key];
    }
  }
  const saved = current.conversation_language;
  const candidate = incoming.conversation_language;
  if (saved?.initialized && (!candidate?.initialized || Number(candidate.revision || 0) < Number(saved.revision || 0))) {
    return { ...incoming, preferred_language: current.preferred_language, conversation_language: saved };
  }
  return incoming;
}

function mergePrivateProfile(saved = {}, current = {}) {
  const incoming = {...current, ...saved};
  for (const key of ['name', 'birth_year', 'birth_date_expression', 'birth_place', 'childhood_place', 'avatar_style']) {
    if (!Object.hasOwn(saved, key)) delete incoming[key];
  }
  return preserveConversationLocale(incoming, current);
}

async function hydrateConversationProfile({photoMemoryRevision = state.photoMemoryRevision || 0} = {}) {
  const scope = captureProjectScope();
  const active = state.conversationLocaleHydration;
  if (active?.pending && isCurrentProjectScope(active.scope)) return active.promise;
  const hydration = {scope, pending:true, failed:false, retry:hydrateConversationProfile};
  state.conversationLocaleHydration = hydration;
  hydration.promise = (async () => {
    try {
      const saved = await storyApi("/v1/user/profile");
      if (!isCurrentProjectScope(scope) || state.conversationLocaleHydration !== hydration) return;
      const current = profile();
      const incoming = mergePrivateProfile(saved, current);
      incoming.memory_places = mergePlaces([...(saved.memory_places || []), ...(current.memory_places || [])], incoming);
      if ((state.photoMemoryRevision || 0) !== photoMemoryRevision) incoming.photo_memories = current.photo_memories;
      state.project = {...state.project, profile:incoming};
      return saved;
    } catch (error) {
      hydration.failed = true;
      throw error;
    } finally {
      hydration.pending = false;
    }
  })();
  return hydration.promise;
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
  state.profileMenuScope = null;
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
  const open = state.profileMenuScope && isCurrentProjectScope(state.profileMenuScope)
    && menu.querySelector("[data-profile-trigger]")?.getAttribute("aria-expanded") === "true";
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
    state.profileMenuScope = captureProjectScope();
    menu.classList.add("is-open");
    trigger.setAttribute("aria-expanded", "true");
    dropdown.hidden = false;
  });
  menu.querySelector("[data-profile-action='settings']")?.addEventListener("click", () => {
    closeProfileMenu();
    const scope = captureProjectScope();
    openProfileSettings({
      api: storyApi,
      isCurrent: () => isCurrentProjectScope(scope),
      onLanguageChange: applyProfileUiLocale,
      onSave: async (settings, { closeAfterSave = true } = {}) => {
        if (!isCurrentProjectScope(scope)) return;
        if (state.project) {
          const projectId = state.project.id;
          const ownerId = state.supabase?.user?.id;
          const updated = preserveConversationLocale({ ...profile(), ...settings }, profile());
          state.project = {...state.project, profile:updated};
          if (!settings.profile_automation) {
            const persistedProfile = { ...updated };
            delete persistedProfile.profile_automation;
            const saved = await api(`/v1/projects/${projectId}`, {
              method: "PATCH",
              body: JSON.stringify({ profile: persistedProfile, expected_revision: state.project.revision }),
            });
            if (!isCurrentProjectScope(scope) || state.project?.id !== projectId || state.supabase?.user?.id !== ownerId) return;
            state.project = { ...state.project, ...saved,
              profile:preserveConversationLocale({...saved.profile, ...settings}, profile()) };
          }
        }
        await persistCommittedFirstReplyUiLocale(profile());
        if (!isCurrentProjectScope(scope)) return;
        await applyProfileUiLocale(conversationLanguage());
        if (!isCurrentProjectScope(scope)) return;
        if (!closeAfterSave || state.recording || state.voiceMode || state.storyRecording) refreshProfileMenu();
        else render();
      },
      onClose: () => { if (isCurrentProjectScope(scope)) $("[data-profile-trigger]")?.focus(); },
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
  state.explicitSignOutInProgress = true;
  let legacyRetired = true;
  closeProfileMenu();
  clearDerivedUiPreference();
  try {
    persistChatHistory();
    if (state.supabase?.client) {
      let storage;
      try { storage = globalThis.localStorage; } catch { /* revocation still runs */ }
      const result = await signOutBrowserSession(state.supabase.client, state.supabase.supabase_url, storage);
      legacyRetired = result.legacyRetired;
      const { error } = result;
      if (error) throw new Error(translate("Errors.logoutFailed"));
    }
    state.recordingStream?.getTracks().forEach((track) => track.stop());
    state.supabase = null;
    uiPreferenceSession.setSession(null, null);
    state.supabaseSession = null;
    state.accountId = null;
    state.csrfToken = "";
    state.project = null;
    state.projectPrincipalId = null;
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
    state.audioRecordings = [];
    state.pendingAudioUpload = null;
    state.audioTranscript = "";
    state.audioPlayer = null;
    state.recognition = null;
    try {
      localStorage.removeItem(PLACE_JOURNEY_PROJECT_STORAGE_KEY);
      localStorage.removeItem("memory-spark-story-started");
      sessionStorage.removeItem("memory-spark-supabase-session");
    } catch { /* private browsing or storage restrictions */ }
    navigateTo(MEMOIR_ROUTES.home, true);
    if (!legacyRetired) {
      renderLanding();
      toast(translate("Errors.logoutStorageWarning"));
      return;
    }
    await boot();
  } catch (error) {
    toast(error.message || translate("Errors.logoutFailed"));
  } finally {
    state.explicitSignOutInProgress = false;
  }
}

function memoryFollowUpPrompt(session = state.session) {
  if (session?.context_cues?.length) return conversationMessage("publicCueFollowUp");
  return conversationMessage("memoryFollowUp");
}

function render() {
  if (!state.project || currentPath() === "/" || currentPath() === MEMOIR_ROUTES.home) {
    conversationScroll.mount(null); disposeCesiumPlaceJourney(); return renderLanding();
  }
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
        <div class="brand"><a href="/" aria-label="${escapeHtml(translate("Platform.homeAria"))}"><img class="brand-mark" src="/static/copyme2_icon_light.png" alt="" aria-hidden="true" /></a><a class="brand brand-name" href="${MEMOIR_ROUTES.home}">${t("brand")}</a></div>
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
            <div class="agent-auth-actions">
              <button type="button" class="button button-secondary button-small" data-auth-provider="google">${escapeHtml(translate("AuthReminder.google"))}</button>
              <button type="button" class="button button-secondary button-small" data-auth-provider="facebook">${escapeHtml(translate("AuthReminder.facebook"))}</button>
            </div>
            <input id="agent-email" type="email" autocomplete="email" placeholder="${t("emailPlaceholder")}" aria-label="${t("emailLabel")}" />
            <input id="agent-password" type="password" autocomplete="current-password" placeholder="${t("passwordPlaceholder")}" aria-label="${t("passwordLabel")}" />
            <div class="agent-auth-actions"><button type="button" class="button button-primary button-small" data-auth-action="signin">${t("signIn")}</button><button type="button" class="button button-secondary button-small" data-auth-action="signup">${t("createAccount")}</button></div>
          </form>
          <small>${state.supabase?.accessToken && state.supabase.user && !state.supabase.user.is_anonymous ? t("connected") : t("required")}</small>
        </details>
        <section class="feature-row"><article class="feature"><div class="feature-icon">◌</div><h3>${t("featureTalkTitle")}</h3><p>${t("featureTalkBody")}</p></article><article class="feature"><div class="feature-icon">⌁</div><h3>${t("featureContextTitle")}</h3><p>${t("featureContextBody")}</p></article><article class="feature"><div class="feature-icon">▱</div><h3>${t("featureWorkspaceTitle")}</h3><p>${t("featureWorkspaceBody")}</p></article></section>
      </main>
    </div>`;
  document.querySelectorAll('[data-action="start-story"]').forEach((button) => button.addEventListener("click", () => startStory(button.dataset.mode || "self")));
  document.querySelectorAll("[data-auth-action]").forEach((button) => button.addEventListener("click", () => supabaseAuth(button.dataset.authAction)));
  document.querySelectorAll("[data-auth-provider]").forEach((button) => button.addEventListener("click", () => supabaseOAuthSignIn(button.dataset.authProvider)));
}

async function startStory(mode = "self") {
  const ownerId = state.supabase?.user?.id;
  const token = state.supabase?.accessToken;
  const generation = state.navigationGeneration || 0;
  const pending = state.storyStart;
  if (pending && pending.mode === mode && pending.ownerId === ownerId
      && pending.token === token && pending.generation === generation) return pending.promise;
  const operation = {mode, ownerId, token, generation};
  state.storyStart = operation;
  try {
    operation.promise = startMemoirStory(mode);
    return await operation.promise;
  } finally {
    if (state.storyStart === operation) state.storyStart = null;
  }
}

async function startMemoirStory(mode = "self") {
  let generation = state.navigationGeneration || 0;
  let ownerId = state.supabase?.user?.id;
  let token = state.supabase?.accessToken;
  const current = () => generation === (state.navigationGeneration || 0) && ownerId === state.supabase?.user?.id
    && !state.explicitSignOutInProgress;
  try {
    stopVoiceMode({ silent: true });
    if (state.authPromise) await state.authPromise;
    if (generation !== (state.navigationGeneration || 0)) return;
    ownerId = state.supabase?.user?.id;
    token = state.supabase?.accessToken;
    // Auth readiness is earlier than saved-project authorization/history. A
    // locale repaint may already have exposed Begin while boot is recovering.
    const recovery = state.projectRecovery;
    if (recovery?.generation === generation) {
      await recovery.promise;
      if (!current() || token !== state.supabase?.accessToken) return;
      if (recovery.failed && mode === "self") {
        toast(translate("AuthReminder.historyError"));
        return;
      }
    }
    if (!current() || state.loading) return;
    if (mode === "self" && state.projectRecoveryBlocked) {
      toast(translate("AuthReminder.historyError"));
      return;
    }
    if (mode === "self" && state.supabase?.user
        && state.project?.mode === "self" && state.projectPrincipalId === state.supabase.user.id) {
      persistChatHistory();
      state.chat = restoreChatHistory(state.project.id);
      await hydrateAccountHistory();
      if (!current()) return;
      state.freshAnonymousSession = false;
      state.chatHistoryCollapsed = false;
      navigateTo(`${MEMOIR_ROUTES.interview}/${state.project.id}`);
      // Navigation cancels the landing poll. Resume in the new scope without
      // coupling extraction recovery to the optional greeting.
      void refreshStageReadiness();
      await startCodexConversation({ resume: true });
      return;
    }
    state.loading = true;
    const language = conversationLanguage();
    const accountHistory = state.supabase?.user && !state.supabase.user.is_anonymous
      ? await storyApi("/v1/user/conversations") : null;
    if (!current()) return;
    const restoreProjectId = mode === "self" ? accountHistory?.resume_project_id : null;
    const project = await api("/v1/projects", { method: "POST",
      ...(state.supabase?.accessToken ? { headers: { Authorization: `Bearer ${state.supabase.accessToken}` } } : {}),
      body: JSON.stringify({ mode, language, ...(restoreProjectId ? { restore_project_id: restoreProjectId } : {}) }) });
    if (!current()) return;
    state.project = project;
    state.projectPrincipalId = ownerId;
    state.recallPreview = null;
    if (state.supabase?.user && !state.supabase.user.is_anonymous) {
      await hydrateConversationProfile();
      if (!current() || state.project?.id !== project.id) return;
    }
    rememberProject(state.project.id);
    state.chat = [];
    if (accountHistory) await hydrateAccountHistory(accountHistory);
    if (!current() || state.project?.id !== project.id) return;
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
    try { localStorage.removeItem("memory-spark-story-started"); } catch { /* Browser storage is optional. */ }
    state.loading = false;
    navigateTo(`${MEMOIR_ROUTES.interview}/${state.project.id}`, true);
    generation = state.navigationGeneration;

    // The opening message is fixed product copy and can stream immediately.
    // Consent and project hydration are independent setup work; keep them out
    // of the first-paint path so a slow request cannot hide the conversation.
    const backgroundSetup = Promise.all([
      api(`/v1/projects/${state.project.id}/consents`, { method: "POST", body: JSON.stringify({ purpose: "recording", granted: true, locale: currentUiLocale() }) }),
      ...(mode === "self" ? [api(`/v1/projects/${state.project.id}/consents`, { method: "POST", body: JSON.stringify({ purpose: "storyteller_assent", granted: true, locale: currentUiLocale() }) })] : []),
      refreshProject(),
      refreshFamilyEntitlement(),
    ]).catch((error) => {
      if (current()) toast(error.message);
    });
    await startCodexConversation();
    await backgroundSetup;
  } catch (error) {
    if (!current()) return;
    state.project = null;
    setLoading(false);
    toast(error.message);
  }
}

async function refreshProject() {
  const scope = captureProjectScope();
  const photoMemoryRevision = state.photoMemoryRevision || 0;
  // Both reads can begin before a successful photo command. Scope checks below
  // reject other projects/principals; within this scope only a newer committed
  // command wins over those snapshots. Failed saves leave refreshes eligible.
  const preservePhotoMemory = incoming => (state.photoMemoryRevision || 0) !== photoMemoryRevision
    ? {...incoming, photo_memories:state.project.profile.photo_memories} : incoming;
  const projectId = state.project.id;
  state.stageReadiness = {};
  state.privateDraft = null;
  state.memoryEventPage = null;
  let base;
  try {
    base = await api(`/v1/projects/${projectId}`);
  } catch (error) {
    if (!isCurrentProjectScope(scope)) return;
    // A committed guest attachment can still have an adapter under the old
    // principal. Recovery verifies durable ownership before repairing it.
    if (![401, 403, 404].includes(error.status) || !state.supabase?.accessToken) throw error;
    base = await api("/v1/projects", { method: "POST",
      headers: { Authorization: `Bearer ${state.supabase.accessToken}` },
      body: JSON.stringify({ mode: "self", restore_project_id: projectId }) });
  }
  if (!isCurrentProjectScope(scope)) return;
  const journey = await api(`/v1/projects/${projectId}/journey`, base.requires_supabase_auth ? {
    headers: { Authorization: `Bearer ${state.supabase.accessToken}` },
  } : {});
  if (!isCurrentProjectScope(scope)) return;
  state.project = { ...base, ...journey, profile: preservePhotoMemory(preserveConversationLocale(base.profile, state.project.profile)) };
  if (state.supabase?.accessToken) {
    await hydrateConversationProfile({photoMemoryRevision});
    if (!isCurrentProjectScope(scope)) return;
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
    if (!isCurrentProjectScope(scope)) return;
    state.memories = memories.items;
    state.sources = sources.items;
    state.chapters = chapters;
    state.people = people.items;
    state.relationships = relationships.items;
    state.timeline = timeline.items;
    if (state.familyFeaturesEnabled) await refreshFamilyContext();
  }
  if (!isCurrentProjectScope(scope)) return;
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

async function hydrateAccountHistory(history = null) {
  const scope = captureProjectScope();
  const user = state.supabase?.user;
  const projectId = state.project?.id;
  if (!user || !projectId) return;
  const exchanges = [];
  const cursors = new Set();
  let cursor = null, epoch;
  try {
    do {
      const page = await storyApi(`/v1/user/projects/${encodeURIComponent(projectId)}/history?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`);
      if (!isCurrentProjectScope(scope)) return;
      if (page.project_id !== projectId || !Array.isArray(page.items)
          || epoch !== undefined && page.policy_epoch !== epoch) throw new Error("Project history changed. Please reload.");
      epoch = page.policy_epoch;
      // Each page is chronological, but its cursor walks toward older turns.
      exchanges.unshift(...page.items);
      cursor = page.next_cursor || null;
      if (cursor && cursors.has(cursor)) throw new Error("Project history could not be loaded. Please reload.");
      if (cursor) cursors.add(cursor);
    } while (cursor);
  } catch (error) {
    // An unavailable or denied canonical snapshot is not permission to expose
    // older raw replies, withdrawn evidence, or cached photo descriptions.
    if (isCurrentProjectScope(scope)) state.chat = [];
    throw error;
  }
  let imported = history;
  if (!user.is_anonymous && !imported) {
    try { imported = await storyApi("/v1/user/conversations"); }
    catch { imported = {items:[]}; } // Canonical history remains independently usable.
  }
  if (!isCurrentProjectScope(scope)) return;
  const canonicalIds = new Set(exchanges.flatMap(item => [item.client_turn_id, item.server_turn_id]).filter(Boolean));
  const maskedEvidence = exchanges.some(item => item.source_status === "withdrawn" || Number(item.source_version || 1) > 1);
  const messages = exchanges.flatMap(item => {
    const clientTurnId = item.client_turn_id || item.server_turn_id;
    const shared = {clientTurnId, sourceSequence:item.source_sequence};
    return [
      ...(typeof item.narrator_text === "string" && item.narrator_text ? [{...shared,
        id:`history-${item.server_turn_id}-user`, role:"user", text:item.narrator_text}] : []),
      ...(typeof item.reply === "string" && item.reply ? [{...shared,
        id:`history-${item.server_turn_id}-assistant`, role:"assistant", text:cleanAssistantText(item.reply),
        historicalContext:item.historical_context ? historicalContext(item.historical_context) : null, responsePhotos:state.photoTurns?.cards(item.response_photos)}] : []),
    ];
  });
  const canonicalMessages = new Set(messages);
  const signature = message => JSON.stringify([message.role, message.text]);
  const bySignature = () => {
    const saved = new Map();
    for (const message of messages) {
      const key = signature(message);
      saved.set(key, [...(saved.get(key) || []), message]);
    }
    return saved;
  };
  // Preserve authorized older guest transcripts, not the unscoped flattened
  // account-conversation feed. Canonical versions supersede imported mirrors.
  const canonicalCopies = bySignature();
  const legacy = !maskedEvidence ? (imported?.items || [])
    .filter(item => item.project_id === projectId
      && !Object.values(item.workspace?.memory_id_map || {}).some(id => canonicalIds.has(id)))
    .sort((a, b) => (a.created_at || "").localeCompare(b.created_at || ""))
    .flatMap(item => (item.messages || []).filter(message => ["user", "assistant"].includes(message.role)
      && typeof message.text === "string").map((message, index) => ({
        id:`history-${item.id}-${index}`, role:message.role,
        text:message.role === "assistant" ? cleanAssistantText(message.text) : originalConversationText(message.text),
      }))) : [];
  const importedOnly = legacy.filter(message => !canonicalCopies.get(signature(message))?.shift());
  messages.unshift(...importedOnly);
  const saved = bySignature();
  for (const local of state.chat) {
    const message = local.role === "user" ? {...local, text:originalConversationText(local.text)} : local;
    if (maskedEvidence && !message.clientTurnId) continue;
    // Identity, not matching wording, decides whether a cached turn has been
    // corrected/withdrawn. A canonical empty photo list also remains final.
    const authoritative = message.clientTurnId && canonicalIds.has(message.clientTurnId);
    const matching = authoritative
      ? messages.find(item => item.clientTurnId === message.clientTurnId && item.role === message.role)
      : !message.clientTurnId ? saved.get(signature(message))?.shift() : undefined;
    if (!matching && !authoritative) messages.push(message);
    if (!matching) continue;
    if (Array.isArray(message.trace)) { matching.trace = message.trace; matching.traceMode = message.traceMode; }
    if (!canonicalMessages.has(matching) && !matching.responsePhotos?.length && message.responsePhotos?.length) matching.responsePhotos = message.responsePhotos;
    if (message.cacheId) matching.cacheId = message.cacheId;
  }
  state.chat = normalizeHistoryOpening(messages);
  persistChatHistory();
}

function renderStory() {
  const profileFocus = document.activeElement?.dataset?.profileAction;
  const profileTriggerFocused = document.activeElement?.hasAttribute?.("data-profile-trigger");
  const hadRecallPrompt = Boolean($(".recall-package-prompt"));
  const albumFocus = document.activeElement?.dataset?.photoAlbum || document.activeElement?.dataset?.photoMarker;
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
  const unlocked = composingWorkspaceActive() || freeRecallFinished();
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
        <div class="brand"><a href="/" data-action="story-home" aria-label="${escapeHtml(translate("Platform.homeAria"))}"><img class="brand-mark" src="/static/copyme2_icon_light.png" alt="" aria-hidden="true" /></a><a class="brand brand-name" href="${MEMOIR_ROUTES.home}">${t("brand")}</a></div>
        <div class="story-topbar-actions"><div class="story-status"><span class="topbar-hint">${t("voiceAvailable")}</span></div>${profileMenu()}</div>
      </header>
      <div class="conversation-layout">
        <main class="${chatClass}" aria-label="${t("mainLabel")}">
          <div id="chat-scroll" class="chat-scroll" tabindex="0" role="region" aria-label="${t("historyRegion")}"><div class="chat-heading"><div>${unlocked ? `<div class="eyebrow">${t("workspaceEyebrow")}</div>` : ""}<h1>${t(unlocked ? "workspaceTitle" : "conversationTitle")}</h1><p>${t(unlocked ? "workspaceDescription" : "conversationDescription")}</p></div>${headerActions}</div><div id="chat-history" class="chat-history"${state.chatHistoryCollapsed ? " hidden" : ""}>${state.chat.map(renderMessage).join("")}</div>${state.loading && !state.chat.at(-1)?.streaming ? `<div class="thinking" role="status"><em>${state.supabase?.accessToken ? t("thinkingCodex") : t("thinkingSimulated")}</em></div>` : ""}${placeJourneySurface()}${recallPackagePrompt()}</div>
          ${chatComposer()}
          ${!workspaceVisible && state.showDraftUpdates ? privateDraftPreview() : ""}
        </main>
        ${workspaceAvailable ? workspaceDetail() : ""}
      </div>
    </div>`;
  bindViewActions();
  bindProfileMenu();
  if (state.profileMenuScope && isCurrentProjectScope(state.profileMenuScope)) {
    // Background greeting/readiness/draft paints must not dismiss an in-flight
    // menu choice. Navigation, owner changes and explicit close discard intent.
    $("[data-profile-trigger]")?.click();
    const focus = profileTriggerFocused ? $("[data-profile-trigger]")
      : ["settings", "collection", "attached-history", "login", "logout"].includes(profileFocus)
        ? $(`[data-profile-action="${profileFocus}"]`) : null;
    focus?.focus({preventScroll: true});
  } else state.profileMenuScope = null;
  const nextMap = $("[data-cesium-place]");
  if (previousMap && nextMap && JSON.stringify(previousMap.dataset) === JSON.stringify(nextMap.dataset)) {
    nextMap.closest(".place-journey-scene").replaceWith(previousScene);
    resizeCesiumPlaceJourney();
  } else {
    disposeCesiumPlaceJourney();
    initCesiumPlaceJourney();
  }
  mapPhotoAlbums.sync($(".place-journey-scene"), albumFocus);
  initFamilyVisualizations();
  const nextGallery = $(".place-pictures[data-photo-place]");
  if (nextGallery && nextGallery.dataset.photoPlace === galleryPlace) nextGallery.scrollTop = galleryTop;
  bindPhotoPagination();
  bindPhotoMemoryActions();
  void state.photoTurns?.bindImages(document, {path:memoirApiPath, errorText:translate("Memoir.story.photoUnavailable")});
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
  // Place/photo context needs a resolved map target for the selected place.
  // Completed free recall also opens Chapters; early draft status does not.
  return Boolean(composingWorkspaceActive() || freeRecallFinished() || placeMapTarget(placeWorkspaceSelection()));
}

function workspaceHasContent() {
  return workspaceContentAvailable();
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
  const mediaOverview = composing || (tabs.length && !state.placeJourney) ? "" : workspaceMediaOverview(toggle);
  const workspaceHeader = mediaOverview ? "" : `<div class="workspace-detail-top">${toggle}</div>`;
  const ariaLabel = tabs.length
    ? `${escapeHtml(title)} ${t("workspaceSuffix")}`
    : state.placeJourney ? `${t("places")} ${t("workspaceSuffix")}` : t("yourWorkspace");
  return `<aside id="workspace-detail" class="workspace-detail${mediaOverview && tabs.length ? " has-recall-views" : ""}" aria-label="${ariaLabel}">${workspaceHeader}${mediaOverview}${contentMarkup}${tabs.length || mediaOverview ? lifeStageNavigator() : ""}${active === "memoir" ? "" : privateDraftPreview()}</aside>`;
}

function currentWorkspaceMemoryFocus() {
  return state.workspaceMemoryFocus && isCurrentProjectScope(state.workspaceMemoryFocus) ? state.workspaceMemoryFocus : null;
}

function workspaceTurnFocus() {
  const focus = currentWorkspaceMemoryFocus();
  return focus?.started ? null : focus?.value;
}

function markWorkspaceFocusStarted(turn) {
  const focus = currentWorkspaceMemoryFocus();
  if (focus && JSON.stringify(focus.value) === JSON.stringify(turn.workspaceFocus)) focus.started = true;
}

function focusWorkspaceMemory(eventId = null) {
  if (state.loading || state.recallStatus?.payment_required || !state.project?.id) return;
  const event = eventId && state.timeline.find(item => item.id === eventId && item.canonical && item.status === "active");
  if (eventId && !event) return;
  const stage = LIFE_STAGES.some(item => item.id === state.lifeStage) ? state.lifeStage : "unplaced";
  const value = event ? {kind:"explore_memory", event_id:event.id, event_revision:event.revision}
    : {kind:"add_memory", life_stage:stage};
  state.workspaceMemoryFocus = {...captureProjectScope(), value,
    title:event?.title || (stage === "unplaced" ? translate("Memoir.workspace.unplacedStage") : lifeStageText(stage, "label"))};
  state.workspaceCollapsed = false;
  render();
  $("#chat-input")?.focus();
}

function workspaceMemoryFocusMarkup() {
  const focus = currentWorkspaceMemoryFocus();
  if (!focus) return "";
  const label = translateWith(`Memoir.workspace.${focus.value.kind === "add_memory" ? "addingMemory" : "exploringMemory"}`, {title:focus.title});
  return `<div class="workspace-memory-focus" role="status"><span>${escapeHtml(label)}</span><button type="button" class="text-button" data-finish-workspace-memory ${state.loading ? "disabled" : ""}>${escapeHtml(translate("Memoir.workspace.finishMemoryFocus"))}</button></div>`;
}

function freeRecallFinished() {
  const completed = state.recallStatus?.rounds_completed;
  const limit = state.recallStatus?.sample_rounds ?? state.recallStatus?.free_rounds;
  return Number.isInteger(completed) && Number.isInteger(limit) && limit > 0 && completed >= limit;
}

function composingWorkspaceActive() {
  return Boolean(state.workspaceUnlocked || state.project?.workspace_unlocked || state.compositionStage >= 3);
}

function workspaceTabs() {
  const t = (key) => translate(`Memoir.workspace.${key}`);
  const premium = state.familyFeaturesEnabled ? [["family", t("family")], ["timeline", t("timeline")]] : [];
  return composingWorkspaceActive() || freeRecallFinished()
    ? [...premium, ["memoir", t("chapters")]]
    : [];
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
    return `<button id="life-stage-${stage.id}" type="button" class="life-stage-tab${stage.id === activeId ? " active" : ""}${hasMemory ? " has-memory" : ""}" data-life-stage-tab="${stage.id}" aria-label="${escapeHtml(description)}" aria-pressed="${stage.id === activeId}" tabindex="${stage.id === activeId ? "0" : "-1"}" title="${escapeHtml(description)}"><span class="life-stage-readiness readiness-${color}" style="--readiness:${percent}%"><span class="life-stage-figure" data-stage="${stage.id}">${lifeStageIllustration(stage)}</span></span><span class="life-stage-label life-stage-mobile-label">${escapeHtml(label)}</span></button>`;
  }).join("");
  return `<section class="life-stage-navigator" aria-label="${t("lifeJourneyEyebrow")}"><div class="life-stage-tabs" role="group" aria-label="${t("lifeStageTabsLabel")}">${tabs}</div><button type="button" class="button button-secondary button-small workspace-add-memory" data-add-workspace-memory ${state.loading || state.recallStatus?.payment_required ? "disabled" : ""}>${activeId === "all" ? t("addMemory") : t("addMemoryToStage", {stage: lifeStageText(activeId, "label")})}</button></section>`;
}

async function refreshStageReadiness() {
  const scope = captureProjectScope();
  const projectId = state.project?.id;
  if (!projectId || !state.supabase?.accessToken) return;
  const active = state.stageReadinessRefresh;
  if (active && !active.controller.signal.aborted && isCurrentProjectScope(active.scope)) {
    // Streamed/final saves share recovery. A failed later read cannot cancel
    // the healthy pending poll, and another save gets a full recovery window.
    active.renew();
    active.requested = true;
    active.wake?.();
    return active.ready;
  }
  active?.controller.abort();
  const job = {scope, controller:new AbortController(), requested:false};
  state.stageReadinessRefresh = job;
  const current = () => state.stageReadinessRefresh === job && isCurrentProjectScope(scope)
    && Boolean(state.supabase?.accessToken) && !job.controller.signal.aborted && Date.now() < job.deadline;
  job.renew = () => {
    clearTimeout(job.expiry);
    // The supported extractor call can take 240s. Allow five minutes after
    // the latest explicit save/reload, with 2/4/8/16s backoff between reads.
    job.deadline = Date.now() + 300_000;
    job.expiry = setTimeout(() => job.controller.abort(), 300_000);
  };
  const wait = delay => new Promise(resolve => {
    const finish = () => {
      clearTimeout(timer);
      job.controller.signal.removeEventListener('abort', finish);
      if (job.wake === finish) job.wake = null;
      resolve();
    };
    const timer = setTimeout(finish, Math.min(delay, job.deadline - Date.now()));
    job.wake = finish;
    job.controller.signal.addEventListener('abort', finish, {once:true});
  });
  const read = async () => {
    const request = new AbortController();
    const cancel = () => request.abort();
    job.controller.signal.addEventListener('abort', cancel, {once:true});
    const timer = setTimeout(cancel, 10_000);
    let rejectRead;
    const interrupted = new Promise((_resolve, reject) => {
      rejectRead = () => reject(request.signal.reason);
      request.signal.addEventListener('abort', rejectRead, {once:true});
    });
    try {
      // Race cancellation as well as aborting fetch: an optional auth/session
      // operation must not hold the recovery loop after its request deadline.
      return await Promise.race([interrupted,
        storyApi(`/v1/story/readiness?project_id=${encodeURIComponent(projectId)}`, {signal:request.signal})]);
    } finally {
      clearTimeout(timer);
      request.signal.removeEventListener('abort', rejectRead);
      job.controller.signal.removeEventListener('abort', cancel);
    }
  };
  job.renew();
  job.ready = (async () => {
    let delay = 2000;
    try {
      while (current()) {
        job.requested = false;
        try {
          const result = await read();
          if (!current()) return;
          // Coalesce refreshes during a read into the next serialized read.
          // A snapshot predating that save cannot repaint newer client state.
          if (!job.requested) {
            state.stageReadiness = result.stages || {};
            if (result.profile) state.project = {...state.project, profile:mergePrivateProfile(result.profile, profile())};
            if (result.derived_workspace && applyDerivedWorkspace(state, result.derived_workspace)) {
              // The existing bounded recovery poll owns workspace catch-up too.
              // Do not persist background hints as profile/language authority.
              if (state.placeJourney) {
                rememberPlaceJourneyProject(projectId);
                resolvePlaceMap(state.placeJourney);
                void loadPlacePictures(state.placeJourney, projectId);
              }
            }
            if (state.recording || state.storyRecording || state.voiceMode) refreshProfileMenu();
            else render();
            if (!result.pending) return;
          }
        } catch (error) {
          if (!current() || [400,401,403,404,422].includes(error?.status)) return;
          // Network errors and legitimate 409/503 revision-fence failures
          // preserve the last good ring and retry within the same budget.
        }
        if (!current()) return;
        if (!job.requested) await wait(delay);
        delay = Math.min(delay * 2, 16_000);
      }
    } finally {
      clearTimeout(job.expiry);
      job.wake?.();
      if (state.stageReadinessRefresh === job) state.stageReadinessRefresh = null;
    }
  })();
  return job.ready;
}

function selectLifeStage(stageId, focus = false) {
  if (!LIFE_STAGES.some((stage) => stage.id === stageId)) return;
  state.lifeStage = stageId;
  state.selectedPlace = null;
  conversationScroll.pause();
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
  const draftPreview = privateDraftPreview({ inChapters: true });
  if (!chapter) return `<div class="workspace-scroll"><div class="workspace-intro"><h2>${t("memoir")}</h2></div>${draftPreview || `<div class="workspace-empty"><span>✦</span><p>${t("firstChapterEmpty")}</p></div>`}</div>`;
  state.selectedMemoirChapter = memoirChapterKey(chapter, selected);
  const button = (index, label, disabled = false) => `<button type="button" data-memoir-chapter="${escapeHtml(memoirChapterKey(chapters[index], index))}" ${disabled ? "disabled" : ""}>${label}</button>`;
  const pagination = `<nav class="chapter-pagination" aria-label="${t("chapterPagination")}">${button(Math.max(0, selected - 1), t("previousChapter"), selected === 0)}<div class="chapter-page-numbers">${chapters.map((item, index) => `<button type="button" data-memoir-chapter="${escapeHtml(memoirChapterKey(item, index))}" aria-current="${index === selected ? "page" : "false"}" aria-label="${t("chapterPage", { number: item.chapter_number || index + 1, title: item.title || "" })}" title="${escapeHtml(item.title || "")}">${item.chapter_number || index + 1}</button>`).join("")}</div>${button(Math.min(chapters.length - 1, selected + 1), t("nextChapter"), selected === chapters.length - 1)}</nav>`;
  const sourceIds = chapterSourceIds(chapter);
  const blocks = Array.isArray(chapter.blocks) ? chapter.blocks.map(chapterBlockMarkup).join("") : "";
  const body = blocks || (chapter.text ? `<div class="chapter-body-block">${formatText(chapter.text)}</div>` : `<p>${t("chapterContentPending")}</p>`);
  return `<div class="workspace-scroll memoir-workspace"><div class="workspace-intro"><h2>${t("memoir")}</h2><p>${t("chapterPosition", { current: selected + 1, total: chapters.length })}</p></div>${pagination}<article class="workspace-card chapter-card" data-chapter-id="${escapeHtml(chapter.id || `chapter-${selected + 1}`)}"><div class="card-topline"><span class="tag">${t("chapter")} ${chapter.chapter_number || selected + 1}</span></div><h3>${escapeHtml(chapter.title || `${t("chapter")} ${selected + 1}`)}</h3><div class="chapter-body">${body}</div>${sourceIds.length ? `<div class="source-pills">${sourcePills(sourceIds)}</div>` : ""}</article>${referencesWorkspace()}${draftPreview}</div>`;
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
  "image/jpeg": "photo", "image/png": "photo", "image/webp": "photo",
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
    const limit = (kind === "video" ? 100 : 10) * 1024 * 1024;
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
    if (item.asset || item.privatePhoto) continue;
    const { file, kind } = item;
    state.attachmentProgress = translateWith("Memoir.story.uploadingAttachment", { name: file.name });
    render();
    if (kind === "photo") {
      const scope = captureProjectScope();
      item.uploadKey ||= globalThis.crypto.randomUUID();
      const response = await fetch(memoirApiPath(`/v1/agent/projects/${encodeURIComponent(scope.projectId)}/photos`), {
        method:"POST", headers:{"Content-Type":file.type, Authorization:`Bearer ${state.supabase.accessToken}`,
          "X-Upload-Idempotency-Key":item.uploadKey, "X-CSRF-Token":state.csrfToken || readCookie("memory_spark_csrf")}, body:file,
      });
      if (!response.ok) throw new Error(translate("Memoir.story.photoUploadFailed"));
      const saved = await response.json();
      if (!isCurrentProjectScope(scope)) return;
      if (!saved.id) throw new Error(translate("Memoir.story.photoUploadFailed"));
      item.privatePhoto = {id:saved.id};
      continue;
    }
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
  if (!projectId || !freeRecallFinished()) return;
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
        body: JSON.stringify({ project_id: projectId, language: conversationLanguage(), retry }) }),
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
  if (!freeRecallFinished()) return "";
  const t = key => escapeHtml(translate(`Memoir.recall.${key}`));
  const sample = state.recallPreview?.projectId === state.project?.id
    && state.recallPreview.userId === state.supabase?.user?.id ? state.recallPreview : null;
  if (!sample || sample.status === "loading" || sample.status === "pending") {
    const retrying = Object.values(sample?.progress || {}).some(lane => lane?.error);
    const message = sample?.reconnect ? "previewReconnecting" : retrying ? "previewRetrying" : sample?.slow ? "previewSlow" : "previewPreparing";
    return `<section class="recall-preview" aria-busy="true"><h2>${t("previewTitle")}</h2><p role="status" aria-live="polite"><span class="preview-spinner" aria-hidden="true"></span>${t(message)}</p><button type="button" class="button button-secondary" disabled>${t("previewWorking")}</button></section>`;
  }
  if (sample.status !== "ready" || !sample.preview) {
    return `<section class="recall-preview"><h2>${t("previewTitle")}</h2><p role="status" aria-live="polite">${t(sample.authRequired ? "previewSignIn" : sample.status === "paused" ? "previewPaused" : sample.status === "stale" ? "previewStale" : sample.status === "insufficient_context" ? "previewInsufficient" : "previewFailed")}</p><button type="button" class="button button-secondary" data-retry-recall-preview>${t(sample.status === "paused" ? "previewCheck" : "previewRetry")}</button></section>`;
  }
  const preview = sample.preview;
  const excerpt = `<article class="recall-preview"><div class="eyebrow">${t(preview.kind === "sample_storyline" ? "sampleStoryline" : "sampleChapter")}</div><h2>${escapeHtml(preview.title)}</h2><div class="recall-preview-text">${formatText(preview.text)}</div>${preview.kind === "sample_storyline" && preview.outline?.length ? `<ol>${preview.outline.map(title => `<li>${escapeHtml(title)}</li>`).join("")}</ol>` : ""}<p class="fine-print">${t("previewNote")}</p></article>`;
  if (!state.recallStatus?.payment_required) return excerpt;
  const pending = new URLSearchParams(window.location.search).get("checkout") === "success";
  return `${excerpt}<section class="recall-package-prompt" aria-labelledby="recall-package-title"><h2 id="recall-package-title">${t("title")}</h2><p>${t("description")}</p>${state.supabase?.user?.is_anonymous ? `<p class="fine-print">${t("signIn")}</p>` : ""}${pending ? `<p role="status">${escapeHtml(translate("Memoir.storyFlow.paymentConfirming"))}</p>` : ""}<button type="button" class="text-button" data-check-recall-payment ${state.loading ? "disabled" : ""}>${t("checkPayment")}</button>${storyCheckoutForm()}</section>`;
}

function chatComposer() {
  const focusControls = workspaceMemoryFocusMarkup();
  if (state.recallStatus?.payment_required) return "";
  const t = (key) => escapeHtml(translate(`Memoir.story.${key}`));
  const button = (action, label, icon, extra = "") => `<button type="button" class="voice-button ${extra}" data-action="${action}" aria-label="${t(label)}" title="${t(label)}">${composerIcon(icon)}</button>`;
  if (state.dictationStatus !== "off") {
    const processing = ["starting", "processing"].includes(state.dictationStatus);
    return `<div class="composer-wrap">${focusControls}<div class="chat-composer dictation-composer">${button("cancel-dictation", "cancelDictation", "close")}<div class="dictation-visual"><div class="dictation-wave ${state.recording ? "is-recording" : ""}" aria-hidden="true">${"<i></i>".repeat(40)}</div><span role="status">${t(processing ? (state.dictationStatus === "starting" ? "connectingMic" : "transcribing") : state.recording ? "dictating" : "dictationStopped")}</span></div>${!processing ? `${state.recording ? button("stop-dictation", "stopDictation", "stop") : ""}${button("accept-dictation", "send", "send", "voice-mode-button")}` : ""}</div><div class="composer-note">${t("dictationNote")}</div></div>`;
  }
  const status = state.voiceMuted ? "muted" : state.voiceModeStatus;
  const voiceStatus = state.voiceMode ? `<div class="voice-session"><div class="voice-orb ${status}" aria-hidden="true"><div class="voice-orb-water"><i></i><i></i><i></i></div></div><div class="voice-mode-status" role="status"><strong class="voice-mode-title">${t("voiceConversation")}</strong><span>${t(state.voiceMuted ? "micMuted" : status === "speaking" ? "miraSpeaking" : status === "processing" ? "listeningBack" : "listening")}</span></div></div>` : "";
  const controls = state.voiceMode
    ? `${button("mute-voice", state.voiceMuted ? "unmuteMic" : "muteMic", state.voiceMuted ? "muted" : "mic")}${button("voice-input", "endVoice", "close", "voice-mode-end")}`
    : `${button("dictate", "dictate", "mic", "dictation-button")}${button("voice-input", "startVoice", "wave", "voice-mode-button voice-mode-launcher")}`;
  return `<div class="composer-wrap ${state.voiceMode ? "has-voice-orb" : ""}">${focusControls}${voiceStatus}${selectedPhotoCue()}${composerAttachments()}${!state.loading && !state.photoTurns?.pending() && (state.audioRecordings?.length || state.pendingAudioUpload) ? `<button type="button" class="text-button" data-action="discard-audio-draft">${t("discardAudio")}</button>` : ""}${state.photoTurns?.pending() && !state.loading ? `<button type="button" class="text-button retry-interview-turn" data-action="retry-interview-turn">${t("retryTurn")}</button>` : ""}<form id="chat-form" class="chat-composer" data-voice-mode="${state.voiceMode ? "on" : "off"}"><button type="button" class="voice-button" data-action="attach-media" aria-label="${t("attachMedia")}" title="${t("attachMedia")}" ${state.loading ? "disabled" : ""}>${composerIcon("plus")}</button><input id="chat-attachments" type="file" accept="${Object.keys(ATTACHMENT_TYPES).join(",")}" multiple hidden /><textarea id="chat-input" rows="1" placeholder="${t(state.voiceMode ? "voicePlaceholder" : "textPlaceholder")}" aria-label="${t("yourMessage")}">${escapeHtml(state.audioTranscript)}</textarea>${controls}<button type="submit" class="send-button" aria-label="${t("send")}" ${state.loading || state.photoMemoryTask ? "disabled" : ""}>${composerIcon("send")}</button></form><div class="composer-note"><span>${t(state.voiceMode ? "voiceNote" : "sourceNote")}</span><span>${t("shortcutNote")}</span></div></div>`;
}

async function retryInterviewTurn() {
  const turn = state.photoTurns?.pending();
  if (!turn || state.loading) return;
  state.audioTranscript = $("#chat-input")?.value || state.audioTranscript;
  const scope = captureProjectScope();
  const current = () => isCurrentProjectScope(scope);
  state.loading = true;
  state.chatHistoryCollapsed = false;
  render();
  try {
    const result = await agentTurn(turn.text, conversationMessage("fallback"), ["memory.save", "memory.search"],
      turn.language, turn.firstReplyLocalization, turn.conversationText, turn.serverAction, turn.sourceKind, {retry:turn});
    if (result.detached || !current()) return;
    await streamAssistantMessage(result.reply, {scope, streamedMessage:result.streamedMessage,
      trace:result.trace, traceMode:result.traceMode, historicalContext:result.historicalContext, responsePhotos:result.responsePhotos, clientTurnId:result.clientTurnId});
    if (state.voiceMode && !result.failed) await speakVoiceReply(result.reply);
  } finally {
    if (current()) { state.loading = false; render(); }
  }
}

function renderMessage(message) {
  if (message.role === "user") {
    const you = escapeHtml(translate("Common.you"));
    return `<article class="chat-row user-message"><div class="chat-bubble"><div class="message-label">${you}</div><div class="message-text">${formatText(message.text)}</div>${message.attachments?.length ? `<div class="composer-attachments">${message.attachments.map(item => `<div class="composer-attachment">${attachmentPreview(item)}</div>`).join("")}</div>` : ""}</div></article>`;
  }
  const streaming = Boolean(message.streaming);
  const visibleText = cleanAssistantText(message.text);
  // Older saved conversations may still contain the retired manual-save action.
  const action = !streaming && message.action && message.action.name !== "save-memory" ? `<button class="button button-primary button-small message-action" data-action="${message.action.name}">${escapeHtml(message.action.label)} <span>↗</span></button>` : "";
  const trace = renderAgentTrace(message.trace || [], message.traceMode, streaming && !visibleText);
  const listen = streaming || state.voiceMode ? "" : `<button class="listen-button" data-action="speak" data-text="${escapeHtml(visibleText)}" aria-label="${escapeHtml(translate("Memoir.story.listen"))}">◖ ${escapeHtml(translate("Memoir.story.listenButton"))}</button>`;
  return `<article class="chat-row assistant-message ${streaming ? "message-streaming" : ""}" data-message-id="${escapeHtml(message.id || "")}"><div class="chat-bubble"><div class="message-meta"><span class="message-label">${CHATBOT_NAME}</span>${listen}</div><div class="message-thinking" role="status" ${streaming && !visibleText ? "" : "hidden"}>${escapeHtml(translate("Memoir.story.thinkingCodex"))}</div><div class="message-trace" aria-live="polite">${trace}</div><div class="message-text" aria-live="polite" ${visibleText ? "" : "hidden"}>${formatText(visibleText)}</div>${message.historicalContext ? historicalContextMarkup(message.historicalContext, currentUiLocale()) : ""}${message.responsePhotos?.length ? responsePhotoMarkup(message.responsePhotos) : ""}${message.error ? `<p role="alert">${escapeHtml(message.error)}</p>` : ""}${action}</div></article>`;
}

function renderAgentTrace(trace, mode = "simulated", expanded = false) {
  if (!state.showThinkingSteps || mode === "simulated") return "";
  // Routine transport and persistence events are not useful conversation steps.
  const visibleSteps = trace.filter(step => step.skill || (!["context", "reply"].includes(step.id)
    && (step.id !== "workspace" || ["completed", "failed"].includes(step.status))));
  if (!visibleSteps.length) return "";
  const title = escapeHtml(translate("Memoir.trace.title"));
  const steps = visibleSteps.map((step) => {
    const pool = step.question_pool;
    const questions = Array.isArray(pool?.candidates) && pool.candidates.length
      ? `<ol class="agent-question-pool">${pool.candidates.map(candidate => {
        const selected = candidate.id === pool.chosen_id;
        return `<li class="agent-question-candidate" data-candidate-id="${escapeHtml(candidate.id)}" data-selected="${selected}">${selected ? `<span class="agent-question-selected">${escapeHtml(translate("Memoir.trace.selectedQuestion"))}</span>` : ""}${candidate.bridge ? `<span class="agent-question-bridge">${escapeHtml(candidate.bridge)}</span> ` : ""}<span>${escapeHtml(candidate.question)}</span></li>`;
      }).join("")}</ol>` : "";
    return `<li class="agent-loop-step agent-loop-${escapeHtml(step.kind || "analysis")}" data-step-id="${escapeHtml(step.id || "")}" data-step-status="${escapeHtml(step.status || "completed")}"><span class="agent-loop-detail">${step.skill ? `${escapeHtml(step.skill)} · ${escapeHtml(translate(`Memoir.trace.status.${step.status || "triggered"}`))} — ` : ""}${escapeHtml(step.detail || step.label || "")}</span>${questions}</li>`;
  }).join("");
  return `<details class="agent-loop" ${expanded ? "open" : ""}><summary><span>${title}</span></summary><ol class="agent-loop-list">${steps}</ol></details>`;
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
  bindHistoricalControls(document, {scope:captureProjectScope, current:isCurrentProjectScope,
    api:supabaseApi, notify:toast, locale:currentUiLocale});
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
  $("[data-action='story-home']")?.addEventListener("click", () => {
    persistChatHistory();
    stopVoiceMode({ silent: true });
    cancelDictation();
  });
  document.querySelectorAll("[data-add-workspace-memory]").forEach(button => button.addEventListener("click", () => focusWorkspaceMemory()));
  document.querySelectorAll("[data-explore-workspace-memory]").forEach(button => button.addEventListener("click", () => focusWorkspaceMemory(button.dataset.exploreWorkspaceMemory)));
  $("[data-finish-workspace-memory]")?.addEventListener("click", () => { state.workspaceMemoryFocus = null; render(); $("#chat-input")?.focus(); });
  document.querySelectorAll("[data-rework-section]").forEach(button => button.addEventListener("click", () => openSectionRework(button.dataset.reworkSection)));
  $("#section-rework-form")?.addEventListener("input", event => { const rework = currentSectionRework(); if (rework && !rework.payload) rework.instruction = event.target.value; });
  $("#section-rework-form")?.addEventListener("submit", submitSectionRework);
  $("[data-cancel-section-rework]")?.addEventListener("click", () => { state.sectionRework = null; render(); });
  $("#chat-form")?.addEventListener("submit", (event) => { event.preventDefault(); sendChatMessage(); });
  $("#chat-input")?.addEventListener("input", (event) => {
    if (!state.audioTranscript) state.audioTranscriptKind = "narrator_chat";
    state.audioTranscript = event.target.value;
    state.photoTurns?.saveAudioDraft();
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
  document.querySelectorAll("[data-draft-locale]").forEach(select => select.addEventListener("change", () => selectPrivateDraftLocale(select.value)));
  document.querySelectorAll(".saved-draft-sections").forEach(details => {
    const scope = captureProjectScope();
    details.addEventListener("toggle", () => {
      if (details.isConnected && isCurrentProjectScope(scope)) state.privateDraftExpanded = details.open;
    });
  });
  document.querySelectorAll("[data-proposal-id]").forEach(button => button.addEventListener("click", () => decidePrivateDraftProposal(button.dataset.proposalId, button.dataset.proposalAccept === "true")));
  document.querySelectorAll("[data-more-event-details]").forEach(button => button.addEventListener("click",() => loadMoreEventDetails(button.dataset.moreEventDetails)));
  document.querySelectorAll("[data-more-event-evidence]").forEach(button => button.addEventListener("click",() => loadMoreEventEvidence(button.dataset.moreEventEvidence)));
  document.querySelectorAll("[data-edit-memory-event]").forEach(button => button.addEventListener("click",() => openMemoryEventEdit(button.dataset.editMemoryEvent)));
  $("#memory-event-edit-form")?.addEventListener("input",event => { Object.assign(state.memoryEventEdit,Object.fromEntries(new FormData(event.currentTarget))); });
  $("#memory-event-edit-form")?.addEventListener("submit",saveMemoryEventEdit);
  const actions = {
    "start-memory": startMemory,
    "finish-chapter": finishChapter,
    "continue-memory": startMemory,
    "voice-input": toggleVoiceInput,
    "retry-interview-turn": () => retryInterviewTurn(),
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
    "discard-audio-draft": discardAudioDraft,
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
    "retry-private-draft": retryPrivateDraft,
    "load-more-private-draft": loadMorePrivateDraft,
    "refresh-private-draft": () => refreshPrivateDraft({restart:true}),
    "load-more-memory-events": loadMoreMemoryEvents,
    "refresh-memory-events": refreshFamilyContext,
    "cancel-event-edit": () => { state.memoryEventEdit = null; render(); },
  };
  document.querySelectorAll("[data-action]").forEach((button) => {
    const action = actions[button.dataset.action];
    if (action) button.addEventListener("click", () => action(button));
  });
}

async function ensureMemorySession() {
  const scope = captureProjectScope();
  if (state.session) return state.session;
  try {
    const session = await api(`/v1/projects/${state.project.id}/memory-sessions`, {
      method: "POST",
      headers: { "Idempotency-Key": `browser-first-memory-${state.project.id}` },
      body: JSON.stringify({ topic_id: "childhood_home" }),
    });
    if (!isCurrentProjectScope(scope)) return null;
    state.session = session;
    return state.session;
  } catch {
    // Codex remains usable when the chapter/session adapter is unavailable.
    return null;
  }
}

async function startMemory() {
  if (state.photoMemoryTask) return;
  const scope = captureProjectScope();
  const current = () => isCurrentProjectScope(scope);
  if (state.recallStatus?.payment_required) return;
  if (state.loading) return;
  try {
    state.loading = true;
    render();
    await ensureMemorySession();
    if (!current()) return;
    const fallback = conversationMessage("fallback");
    const result = await agentTurn("The storyteller wants to continue with another memory. Ask one open-ended question based on the conversation, without restarting onboarding.", fallback, ["memory.start", "memory.search"], conversationLanguage(), false, undefined, "continue");
    if (result.detached || !current()) return;
    await streamAssistantMessage(result.reply || fallback, { scope, streamedMessage: result.streamedMessage, trace: result.trace, traceMode: result.traceMode });
  } catch (error) { if (current()) toast(error.message); }
  if (!current()) return;
  state.loading = false;
  render();
}

async function sendChatMessage({ voiceTurn = false } = {}) {
  const scope = captureProjectScope();
  const current = () => isCurrentProjectScope(scope);
  if (voiceTurn && state.photoMemoryTask) {
    await state.photoMemoryTask.done;
    if (!current() || !state.voiceMode) return;
  }
  if (state.recallStatus?.payment_required) return;
  if (state.loading || state.photoMemoryTask || state.dictationStatus !== "off") return;
  if (state.photoTurns?.pending()?.accepted) return toast(translate("Memoir.story.retryTurn"));
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
  const sourceKind = voiceTurn || state.audioRecordings?.length ? "narrator_transcript" : state.audioTranscriptKind;
  const uploadId = state.audioUploadId;
  const attachments = [...state.attachments];
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
      if (!current()) return;
      state.loading = false;
      state.attachmentProgress = error.message;
      if (state.voiceMode) { state.voiceModeStatus = "listening"; queueVoiceModeTurn(); }
      render();
      return;
    }
    if (!current()) return;
  }
  const profileIntake = state.profileIntakePending;
  const messageText = text || (attachments.length ? translate("Memoir.story.sharedAttachments") : conversationMessage("voiceAnswer"));
  const firstReply = !profile().conversation_language?.initialized && !state.chat.some((message) => message.role === "user");
  try {
    if (firstReply && !await settleUiLocale()) throw new Error(localizedErrorMessage());
  } catch (error) {
    if (!current()) return;
    state.loading = false;
    if (state.voiceMode) state.voiceModeStatus = "listening";
    toast(error.message);
    render();
    return;
  }
  if (!current()) return;
  if ($("#chat-input")) $("#chat-input").value = "";
  state.chatHistoryCollapsed = false;
  state.chat.push({ role: "user", text: messageText, attachments });
  conversationScroll.follow();
  state.audioUploadId = null;
  state.audioTranscript = "";
  render();
  try {
    const session = text ? await ensureMemorySession() : null;
    if (!current()) return;
    let cues = [];
    let fallback = conversationMessage("fallback");
    let instruction = profileIntake
      ? PROFILE_INTAKE_PROMPT
      : "Acknowledge the storyteller naturally, then ask one gentle open-ended follow-up question. Do not restart onboarding or request profile fields.";
    if (session && (session.follow_ups_used || 0) < 3 && (session.turns?.length || 0) < 5) {
      try {
        const turnType = session.turns?.length ? "follow_up" : "initial";
        const answerOptions = { method: "POST", body: JSON.stringify({ text: messageText, upload_id: uploadId, turn_type: turnType }) };
        try {
          const answer = await api(`/v1/memory-sessions/${session.id}/answers`, answerOptions);
          if (!current()) return;
          state.session = answer;
        } catch (error) {
          if (!current()) return;
          if (error.code !== "POLICY_EPOCH_CONFLICT") throw error;
          // Consent/project setup is allowed to complete in parallel with the
          // first paint. Resync this still-open session once, then retry the
          // same answer; the Codex conversation remains the primary path.
          await api(`/v1/memory-sessions/${session.id}/resume`, { method: "POST" });
          if (!current()) return;
          const answer = await api(`/v1/memory-sessions/${session.id}/answers`, answerOptions);
          if (!current()) return;
          state.session = answer;
        }
        cues = state.session.context_cues || [];
        fallback = memoryFollowUpPrompt(state.session);
        const memoryInstruction = "Acknowledge the storyteller briefly, then ask one gentle follow-up question about their memory. Follow requests to finish, change direction, or shape the story. Later corrections revise the affected year/event without restarting the interview.";
        instruction = profileIntake ? `${PROFILE_INTAKE_PROMPT}\n${memoryInstruction}` : memoryInstruction;
      } catch {
        if (!current()) return;
        // The open Codex conversation is the primary path; session state is optional.
        state.session = null;
      }
    }
    const mediaContext = attachments.some(item => item.asset) ? `\nThe storyteller attached these saved sources: ${JSON.stringify(attachments.filter(item => item.asset).map(item => ({ asset_id: item.asset.id, filename: item.file.name, kind: item.kind })))}. Only attachment metadata is provided here; do not claim to have viewed their contents. Ask the storyteller about the people, place, or moment shown.` : "";
    if (firstReply && !await settleUiLocale()) throw new Error(localizedErrorMessage());
    if (!current()) return;
    const configuredConversationLanguage = conversationLanguage() || currentUiPreference()?.locale;
    const detectedFirstReplyLanguage = firstReply && !configuredConversationLanguage
      ? firstReplyLanguage(messageText)
      : undefined;
    if (detectedFirstReplyLanguage) {
      await applyFirstReplyLocalization(detectedFirstReplyLanguage);
      if (!await settleUiLocale()) throw new Error(localizedErrorMessage());
    }
    if (!current()) return;
    const result = await agentTurn(
      text ? `The storyteller said: ${text}\n${instruction}${mediaContext}` : "",
      fallback,
      ["memory.save", "memory.search"],
      conversationLanguage() || currentUiPreference()?.locale || detectedFirstReplyLanguage || (firstReply ? currentUiLocale() : undefined),
      Boolean(detectedFirstReplyLanguage) && !conversationLanguage() && currentUiPreference()?.source !== "manual",
      text,
      null,
      sourceKind,
      {attachments, recordingIds:(state.audioRecordings || []).map(recording => recording.id)},
    );
    if (result.detached || !current()) return;
    if (result.blocked) {
      // Another tab may have used the final free reply. Keep the unsent draft.
      state.chat.pop();
      state.audioTranscript = messageText;
      state.loading = false;
      render();
      return;
    }
    const cuesAlreadyShown = state.chat.some((message) => message.cues?.length);
    await streamAssistantMessage(result.reply || fallback, { scope, streamedMessage: result.streamedMessage, trace: result.trace, traceMode: result.traceMode, historicalContext:result.historicalContext, responsePhotos:result.responsePhotos, clientTurnId:result.clientTurnId, cues: cues.length && !cuesAlreadyShown ? cues : undefined });
    if (!current()) return;
    if (state.voiceMode && !result.failed) await speakVoiceReply(result.reply || fallback);
  } catch (error) {
    if (!current()) return;
    toast(error.message);
  }
  if (!current()) return;
  state.loading = false;
  render();
  void refreshFamilyContext();
  if (state.voiceMode) window.setTimeout(() => { if (current()) startVoiceModeTurn(); }, 260);
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

// Keep playback analysis local to the player so ending voice mode releases it too.

async function boot() {
  const generation = invalidateProjectNavigation();
  let releaseRecovery;
  const recovery = {generation, failed: true, promise: new Promise(resolve => {releaseRecovery = resolve;})};
  recovery.finish = () => {
    if (state.projectRecovery === recovery) state.projectRecovery = null;
    releaseRecovery();
  };
  state.projectRecovery = recovery;
  const path = currentPath();
  state.navigationPath = path;
  const current = () => generation === state.navigationGeneration;
  try {
    const choice = JSON.parse(sessionStorage.getItem("memoir-package-choice") || "null");
    if (FALLBACK_STORY_PLANS.some(plan => plan.plan_key === choice?.plan)) {
      state.selectedStoryPlan = choice.plan;
      state.storyBookCount = Math.max(2, Math.min(20, Number(choice.books) || 2));
    }
  } catch { /* Ignore unavailable storage or an invalid saved selection. */ }
  const authPromise = state.authPromise || ensureAuth();
  state.authPromise = authPromise;
  try {
    await authPromise;
    if (!current()) return;
    try {
      const completed = await guestTransfer.complete();
      if (!current()) return;
      if (completed) toast(translate("AuthReminder.mergeSuccess"));
    } catch {
      if (!current()) return;
      retryConversationTransfer(() => guestTransfer.complete(), async () => {
        await guestTransfer.restoreGuest();
        window.location.reload();
      });
    }
    await syncProfileUiLocale();
    if (!current()) return;
    // The old five-round entry point was client-only state. Clear it so a
    // refresh always returns to the persistent Codex conversation instead of
    // reopening a fixed question card.
    try { localStorage.removeItem("memory-spark-story-started"); } catch { /* Browser storage is optional. */ }
    // The interview URL identifies this page's project. The shared cache can
    // point at an older project or one opened in another tab.
    const interviewPrefix = `${MEMOIR_ROUTES.interview}/`;
    const routeProject = path.startsWith(interviewPrefix)
      ? path.slice(interviewPrefix.length).split("/")[0] : null;
    const cachedProject = savedProjectId();
    const saved = routeProject || cachedProject;
    if (saved) {
      try {
        const ownerId = state.supabase?.user?.id;
        state.project = { id: saved };
        state.session = null;
        state.codexReady = false;
        state.codexStarting = false;
        state.placeJourney = null;
        state.workspaceUnlocked = false;
        state.compositionStage = 0;
        state.workspaceCollapsed = false;
        state.memories = []; state.sources = []; state.chapters = [];
        state.people = []; state.relationships = []; state.timeline = [];
        state.freshAnonymousSession = false;
        state.chat = [];
        state.chatHistoryCollapsed = true;
        await refreshProject();
        if (!current() || state.project?.id !== saved || state.supabase?.user?.id !== ownerId) return;
        state.projectRecoveryBlocked = null;
        state.projectPrincipalId = state.supabase?.user?.id;
        state.chat = restoreChatHistory(saved);
        rememberProject(saved);
        try {
          await hydrateAccountHistory();
          if (!current()) return;
          // Canonical source masking must run before a pending receipt can
          // render any locally cached history during reconnect.
          await state.photoTurns?.recover();
        } catch {
          if (current()) {
            state.projectRecoveryBlocked = saved;
            toast(translate("AuthReminder.historyError"));
          }
        }
        if (!current()) return;
        await syncProfileUiLocale();
        if (!current()) return;
        await hydratePlaceJourney();
        if (!current()) return;
        await refreshFamilyEntitlement();
        if (!current()) return;
        state.profileIntakePending = !profileHasContext(state.project.profile);
        if (currentPath() === MEMOIR_ROUTES.start) window.history.replaceState({}, "", `${MEMOIR_ROUTES.interview}/${saved}`);
        recovery.failed = Boolean(state.projectRecoveryBlocked);
        recovery.finish(); // Do not couple start admission to subsequent opening-copy streaming.
        render();
        await startCodexConversation({ resume: true });
        return;
      }
      catch {
        if (!current()) return;
        // Preserve an unavailable saved interview rather than silently making a replacement.
        state.projectRecoveryBlocked = saved;
        state.project = null; state.projectPrincipalId = null; state.chat = [];
      }
    }
    if (!saved) recovery.failed = false;
    recovery.finish();
    if (currentPath() === MEMOIR_ROUTES.start) window.history.replaceState({}, "", MEMOIR_ROUTES.home);
    renderLanding();
  } catch (error) {
    if (current()) $("#app").innerHTML = `<div class="loading">${escapeHtml(error.message)}</div>`;
  } finally {
    recovery.finish();
    if (current() && state.authPromise === authPromise) state.authPromise = null;
  }
}

window.addEventListener("popstate", () => {
  const path = currentPath();
  // Photo albums own same-URL history entries. Their Back/Forward events
  // must not cancel the interview's reply or restart project recovery.
  if (path === state.navigationPath) return;
  state.navigationPath = path;
  invalidateProjectNavigation();
  const prefix = `${MEMOIR_ROUTES.interview}/`;
  const projectId = currentPath().startsWith(prefix) ? currentPath().slice(prefix.length).split("/")[0] : null;
  if (projectId) {
    $("#app").innerHTML = `<div class="loading">${escapeHtml(translate("Common.loading"))}</div>`;
    void boot();
  } else render();
});
window.addEventListener("pagehide", () => persistChatHistory());
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
