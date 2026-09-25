import { MEMOIR_ROUTES } from "/app/routes.js";

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
  preview: null,
  chat: [],
  codexStarting: false,
  codexReady: false,
  placeJourney: null,
  workspaceTab: "chapters",
  workspaceUnlocked: false,
  chapterDecision: null,
  story: null,
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
  audioUploadId: null,
  audioTranscript: "",
  audioPlayer: null,
  recognition: null,
  supabase: null,
  authPromise: null,
};

const MEMOIR_API_PREFIX = "/api/v1/memoir";
const CESIUM_VERSION = "1.145";
let cesiumPlaceJourneyViewer = null;
let cesiumLoadPromise = null;

const CODEX_START_PROMPT = `The storyteller has just opened a new conversation. Start naturally by welcoming them,
explain that they can talk about any memory, person, place, or feeling, and ask one open-ended
question about what they would like to remember today. Do not run a fixed onboarding questionnaire,
do not ask for their name, birth date, or birthplace first, and do not assume any personal facts.
Keep the reply warm and concise.`;
const CODEX_START_FALLBACK = "Hi — I’m here to listen. What would you like to remember today?";

const FOLLOW_UP_QUESTIONS = [
  "What could you see, hear, smell, or feel in that moment?",
  "Who was with you, and what do you remember about them?",
  "What small detail would you like to keep for your family?",
];

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value = "") => String(value).replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;", "'":"&#039;"}[char]));
const formatText = (value = "") => escapeHtml(value).replace(/\n/g, "<br>");

function memoirApiPath(path) {
  if (path.startsWith(MEMOIR_API_PREFIX)) return path;
  if (path === "/v1") return MEMOIR_API_PREFIX;
  if (path.startsWith("/v1/")) return `${MEMOIR_API_PREFIX}${path.slice(3)}`;
  return path;
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
  const method = (options.method || "GET").toUpperCase();
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (!path.startsWith("/v1/auth/") && method !== "GET" && method !== "HEAD") {
    headers["X-CSRF-Token"] = state.csrfToken || readCookie("memory_spark_csrf");
  }
  const response = await fetch(memoirApiPath(path), { ...options, headers });
  let body = null;
  try { body = await response.json(); } catch { body = { detail: response.statusText }; }
  if (!response.ok) throw new Error(body?.detail || "Something went wrong");
  return body;
}

function readCookie(name) {
  const prefix = `${name}=`;
  const match = document.cookie.split("; ").find((item) => item.startsWith(prefix));
  return match ? decodeURIComponent(match.slice(prefix.length)) : "";
}

async function ensureAuth() {
  await loadSupabaseConfig();
  if (state.supabase?.auth_mode === "test") {
    syncSupabaseSession({ access_token: "browser-test-token", refresh_token: null, user: { is_anonymous: true } });
    return;
  }
  if (!state.supabase?.client) throw new Error("Supabase anonymous auth is not configured.");
  const { data, error } = await state.supabase.client.auth.getSession();
  if (error) throw new Error(error.message || "Unable to restore your Supabase session.");
  let session = data.session;
  if (!session) {
    const signedIn = await state.supabase.client.auth.signInAnonymously();
    if (signedIn.error) {
      const message = signedIn.error.message || "Unable to start an anonymous Supabase session.";
      if (message.toLowerCase().includes("anonymous sign-ins are disabled")) {
        throw new Error("Anonymous sign-ins are disabled in Supabase. Enable Auth → Sign In / Providers → Anonymous, then reload.");
      }
      throw new Error(message);
    }
    session = signedIn.data.session;
  }
  syncSupabaseSession(session);
}

async function loadSupabaseConfig() {
  const response = await fetch(memoirApiPath("/v1/agent/config"));
  const config = await response.json();
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
  state.supabase.accessToken = session?.access_token || null;
  state.supabase.refreshToken = session?.refresh_token || null;
  state.supabase.user = session?.user || null;
}

async function supabaseAuth(action) {
  if (!state.supabase?.supabase_url || !state.supabase?.supabase_publishable_key) return toast("Supabase sign-in is not configured.");
  const email = $("#agent-email")?.value.trim();
  const password = $("#agent-password")?.value || "";
  if (!email || password.length < 8) return toast("Enter an email and a password of at least 8 characters.");
  if (state.supabase.client) {
    const result = action === "signup"
      ? await state.supabase.client.auth.signUp({ email, password })
      : await state.supabase.client.auth.signInWithPassword({ email, password });
    if (result.error) return toast(result.error.message || "Supabase sign-in failed.");
    if (!result.data.session) return toast("Account created. Confirm the email, then sign in to connect Codex memory.");
    syncSupabaseSession(result.data.session);
    renderLanding();
    toast("Codex memory is connected for this session.");
    return;
  }
  const path = action === "signup" ? "/auth/v1/signup" : "/auth/v1/token?grant_type=password";
  const response = await fetch(`${state.supabase.supabase_url}${path}`, { method: "POST", headers: { "Content-Type": "application/json", apikey: state.supabase.supabase_publishable_key }, body: JSON.stringify({ email, password }) });
  const body = await response.json();
  if (!response.ok) return toast(body.error_description || body.msg || body.message || "Supabase sign-in failed.");
  if (!body.access_token) return toast("Account created. Confirm the email, then sign in to connect Codex memory.");
  state.supabase = { ...state.supabase, accessToken: body.access_token, refreshToken: body.refresh_token, user: body.user };
  try { sessionStorage.setItem("memory-spark-supabase-session", JSON.stringify({ accessToken: body.access_token, refreshToken: body.refresh_token, user: body.user })); } catch { /* session remains in memory */ }
  renderLanding();
  toast("Codex memory is connected for this session.");
}

async function storySession() {
  if (state.supabase?.auth_mode === "test") return { access_token: "browser-test-token" };
  if (!state.supabase?.client) throw new Error("Supabase anonymous auth is not configured.");
  const { data, error } = await state.supabase.client.auth.getSession();
  if (error || !data.session) throw new Error(error?.message || "Your Supabase session is unavailable.");
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
    const error = new Error(body?.detail || "The story could not be saved.");
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
    throw new Error("Your Supabase session expired. Sign in again to reconnect Codex memory.");
  }
  if (!response.ok) throw new Error(body.detail || "Supabase request failed");
  return body;
}

function simulatedLoopTrace(toolNames = ["memory.search"], finalDetail = "Return one concise, speakable question grounded in the conversation.") {
  const tools = toolNames.flatMap((name) => [
    { kind: "tool_call", label: name, detail: `Call ${name} with the current story context.` },
    { kind: "tool_result", label: `${name} result`, detail: "Completed with source-linked data; no personal facts were inferred." },
  ]);
  return [
    { kind: "analysis", label: "Analyze", detail: "Classify the storyteller's message and choose the next safe step." },
    ...tools,
    { kind: "final", label: "Respond", detail: finalDetail },
  ];
}

async function agentTurn(text, fallback = "", toolNames = ["memory.search"]) {
  const simulated = simulatedLoopTrace(toolNames);
  if (!state.supabase?.accessToken) return { reply: fallback || null, trace: simulated, traceMode: "simulated" };
  try {
    const body = await supabaseApi("/v1/agent/turn", { method: "POST", body: JSON.stringify({ text }) });
    if (body.place_journey) {
      state.placeJourney = body.place_journey;
      if (!state.workspaceUnlocked || state.workspaceTab === "chapters") state.workspaceTab = "places";
    }
    return { reply: body.reply || fallback || null, trace: body.trace || simulated, traceMode: body.trace_mode || "codex", placeJourney: body.place_journey || null };
  } catch (error) {
    toast(error.message);
    return { reply: fallback || null, trace: simulated, traceMode: "simulated" };
  }
}

async function startCodexConversation({ resume = false } = {}) {
  if (!state.project || state.codexStarting || state.codexReady || state.chat.length) return;
  state.codexStarting = true;
  state.loading = true;
  render();
  const prompt = resume
    ? "Resume this storyteller's conversation naturally. Welcome them back briefly and invite them to continue with whatever memory or thought is present. Do not repeat a fixed onboarding questionnaire."
    : CODEX_START_PROMPT;
  const fallback = resume
    ? "Welcome back. What would you like to remember today?"
    : CODEX_START_FALLBACK;
  try {
    const result = await agentTurn(prompt, fallback, ["conversation.start", "memory.search"]);
    if (result.reply) state.chat.push({ role: "assistant", text: result.reply, trace: result.trace, traceMode: result.traceMode });
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
  if (value && !state.project) $("#app").innerHTML = '<div class="loading">Opening your private conversation…</div>';
}

function profile() {
  return state.project?.profile || {};
}

function profileDetails() {
  const user = state.supabase?.user || state.supabaseSession?.user || {};
  const metadata = user.user_metadata || {};
  const name = profile().name || metadata.full_name || metadata.name || user.email || (user.is_anonymous ? "Private session" : "Your profile");
  const email = user.email || (user.is_anonymous ? "Anonymous session" : "Supabase account");
  const parts = String(name).trim().split(/\s+/).filter(Boolean);
  const initials = parts.length > 1
    ? `${parts[0][0]}${parts[parts.length - 1][0]}`
    : (parts[0] || "Me").slice(0, 2);
  return { name, email, initials: initials.toUpperCase() };
}

function profileMenu() {
  const details = profileDetails();
  return `
    <div class="profile-menu" data-profile-menu>
      <button class="profile-trigger" type="button" data-profile-trigger aria-label="Open profile menu" aria-expanded="false" aria-haspopup="menu" aria-controls="profile-menu-content">
        <span class="profile-avatar" aria-hidden="true">${escapeHtml(details.initials)}</span>
        <span class="profile-trigger-copy"><span class="profile-trigger-label">Profile</span><span class="profile-trigger-name">${escapeHtml(details.name)}</span></span>
        <span class="profile-chevron" aria-hidden="true"></span>
      </button>
      <div class="profile-dropdown" id="profile-menu-content" role="menu" hidden>
        <div class="profile-dropdown-header"><span class="profile-dropdown-eyebrow">ACCOUNT</span><strong>${escapeHtml(details.name)}</strong><small>${escapeHtml(details.email)}</small></div>
        <button class="profile-menu-item profile-logout" type="button" role="menuitem" data-profile-action="logout"><span>Log out</span><span aria-hidden="true">↗</span></button>
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
  menu.querySelector("[data-profile-action='logout']")?.addEventListener("click", signOut);
}

async function signOut() {
  closeProfileMenu();
  try {
    if (state.supabase?.client) {
      const { error } = await state.supabase.client.auth.signOut();
      if (error) throw new Error(error.message || "Unable to log out.");
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
    state.codexStarting = false;
    state.codexReady = false;
    state.placeJourney = null;
    state.workspaceTab = "chapters";
    state.workspaceUnlocked = false;
    state.chapterDecision = null;
    state.story = null;
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
      localStorage.removeItem("memory-spark-story-started");
      sessionStorage.removeItem("memory-spark-supabase-session");
    } catch { /* private browsing or storage restrictions */ }
    navigateTo(MEMOIR_ROUTES.home, true);
    await boot();
  } catch (error) {
    toast(error.message || "Unable to log out.");
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
  const used = Number(session?.follow_ups_used || 0);
  if (used === 0 && session?.context_cues?.length) {
    return "Does anything in these public historical references bring back a detail? What felt familiar, and what was different in your own life?";
  }
  const cueOffset = session?.context_cues?.length ? 1 : 0;
  return FOLLOW_UP_QUESTIONS[Math.min(Math.max(0, used - cueOffset), FOLLOW_UP_QUESTIONS.length - 1)];
}

function memoryTurnFallback(session = state.session) {
  if (memoryFollowUpsRemaining(session) > 0) return memoryFollowUpPrompt(session);
  return "Thank you. I have enough detail to shape the first chapter. Save this memory when it feels right.";
}

function storyRoundQuestion() {
  return CODEX_START_FALLBACK;
}

const STORY_ROUNDS_REQUIRED = 5;

const FALLBACK_STORY_PLANS = [
  { plan_key: "electronic_memoir_v1", name: "Electronic memoir", price_minor: 4900, description: "A beautifully shaped electronic version of your memoir.", features: ["Electronic memoir", "Source-linked story chapters", "Private digital delivery"], electronic_only: true, additional_book_price_minor: 0, minimum_books: 0, default_books: 0 },
  { plan_key: "printed_memoir_v1", name: "Printed memoir", price_minor: 7900, description: "Two printed books, with extra copies available for A$10 each.", features: ["Electronic memoir", "2 printed books", "Add extra books for A$10 each"], electronic_only: false, additional_book_price_minor: 1000, minimum_books: 2, default_books: 2 },
  { plan_key: "family_memoir_v1", name: "Family legacy memoir", price_minor: 12900, description: "Two printed books plus a richer family record.", features: ["Electronic memoir", "2 printed books", "Family tree", "Life timeline", "More detailed story context"], electronic_only: false, additional_book_price_minor: 1000, minimum_books: 2, default_books: 2 },
];

function formatAudMinor(amountMinor) {
  return new Intl.NumberFormat("en-AU", { style: "currency", currency: "AUD", maximumFractionDigits: 0 }).format(Number(amountMinor || 0) / 100);
}

function storyPlanTotal(plan, bookCount) {
  if (plan.electronic_only) return plan.price_minor;
  return plan.price_minor + Math.max(0, Number(bookCount || plan.default_books || 2) - 2) * (plan.additional_book_price_minor || 1000);
}

function storyCheckoutForm() {
  const plans = state.storyPlans.length ? state.storyPlans : FALLBACK_STORY_PLANS;
  const selectedPlan = plans.find((plan) => plan.plan_key === state.selectedStoryPlan) || plans[0];
  const selectedKey = selectedPlan.plan_key;
  const bookCount = Math.max(2, Number(state.storyBookCount || selectedPlan.default_books || 2));
  const printed = !selectedPlan.electronic_only;
  const total = storyPlanTotal(selectedPlan, printed ? bookCount : 0);
  const checkoutMessage = state.checkout?.message ? `<p class="fine-print story-payment-note">${escapeHtml(state.checkout.message)}</p>` : "";
  return `
    <form id="story-checkout-form" class="story-checkout-form">
      <div class="story-plan-grid" role="radiogroup" aria-label="Memoir packages">
        ${plans.map((plan) => `
          <label class="story-plan-card ${plan.plan_key === selectedKey ? "selected" : ""}">
            <input type="radio" name="plan_key" value="${escapeHtml(plan.plan_key)}" ${plan.plan_key === selectedKey ? "checked" : ""} />
            <span class="story-plan-card-top"><span class="eyebrow">${escapeHtml(plan.name)}</span><strong>from ${formatAudMinor(plan.price_minor)}</strong></span>
            <span class="story-plan-description">${escapeHtml(plan.description)}</span>
            <span class="story-plan-features">${plan.features.map((feature) => `<span>✓ ${escapeHtml(feature)}</span>`).join("")}</span>
          </label>`).join("")}
      </div>
      <div class="story-book-options ${printed ? "" : "is-disabled"}">
        <label for="story-book-count"><span>Printed books</span><select id="story-book-count" name="book_count" ${printed ? "" : "disabled"}>${Array.from({ length: 19 }, (_, index) => index + 2).map((count) => `<option value="${count}" ${count === bookCount ? "selected" : ""}>${count} books${count > 2 ? ` · +${formatAudMinor((count - 2) * 1000)}` : ""}</option>`).join("")}</select></label>
        <div class="story-checkout-total"><span>Total today</span><strong data-story-total>${formatAudMinor(total)}</strong></div>
      </div>
      <button type="submit" class="button button-primary" ${state.loading ? "disabled" : ""}>Continue to secure checkout <span>↗</span></button>
      <p class="fine-print">Prices are in Australian dollars. Stripe securely collects payment details on its hosted checkout page.</p>
      ${checkoutMessage}
    </form>`;
}

function checkoutRedirectNotice() {
  const status = new URLSearchParams(window.location.search).get("checkout");
  if (status === "success" && state.story?.payment_status !== "paid") return "Payment received. We’re confirming it with Stripe now; this page will unlock as soon as the webhook arrives.";
  if (status === "cancelled") return "No payment was taken. You can choose a package whenever you’re ready.";
  return "";
}

function renderStoryFlow() {
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
      <div class="story-progress">Round ${completed + 1} of ${STORY_ROUNDS_REQUIRED}</div>
      <h1>${escapeHtml(storyRoundQuestion())}</h1>
      <p class="story-lead">Take your time. A few honest sentences are enough.</p>
      <div class="story-question-tools"><button type="button" class="listen-button" data-story-action="listen-story-question">◖ Listen · AI voice</button><span>AI-generated audio · text remains available</span></div>
      <form id="story-round-form" class="story-round-form">
        <button type="button" class="voice-button story-voice-button ${state.storyRecording ? "recording" : ""}" data-story-action="toggle-story-voice" aria-label="${state.storyRecording ? "Stop voice answer" : "Record a voice answer"}">${state.storyRecording ? "■ Stop recording" : "● Record a voice answer"}</button>
        <textarea id="story-answer" rows="7" placeholder="Write what comes back to you, or record your answer…" aria-label="Your story answer">${escapeHtml(state.storyTranscript)}</textarea>
        <p class="composer-note">${state.storyAudioBase64 ? "Review the transcript before saving. Your original recording stays attached." : "You can type, record, pause, or skip."}</p>
        <button type="submit" class="button button-primary">Save answer <span>↗</span></button>
      </form>`;
  } else if (isLinking) {
    body = `
      <div class="story-progress">Five rounds complete</div>
      <h1>Your first five memories are ready.</h1>
      <p class="story-lead">Create a free account to keep them and receive one free chapter. You can use Google or Facebook.</p>
      <div class="story-auth-actions">
        <button class="button button-primary" data-story-provider="google">Continue with Google <span>↗</span></button>
        <button class="button button-secondary" data-story-provider="facebook">Continue with Facebook</button>
      </div>
      <p class="fine-print">Your anonymous session will be linked to the account you choose.</p>`;
  } else if (needsFreeChapter) {
    body = `
      <div class="story-progress">Your free chapter</div>
      <h1>Shape these memories into your first chapter.</h1>
      <p class="story-lead">Your five answers are saved privately. Claim one free chapter to see how they come together.</p>
      <button class="button button-primary" data-story-action="free-chapter">Claim my free chapter <span>↗</span></button>`;
  } else if (needsPayment) {
    const redirectNotice = checkoutRedirectNotice();
    body = `
      <div class="story-progress">Chapter one is yours</div>
      <h1>Ready to keep going?</h1>
      ${chapter ? `<article class="story-chapter"><div class="eyebrow">Chapter 1 · ${escapeHtml(chapter.title)}</div><p>${formatText(chapter.text)}</p></article>` : `<p class="story-lead">Your free chapter is saved to your private memory.</p>`}
      <p class="story-lead">Choose the finish that feels right for your family. Every package includes the electronic memoir.</p>
      ${redirectNotice ? `<p class="story-payment-banner">${escapeHtml(redirectNotice)}</p>` : ""}
      ${storyCheckoutForm()}`;
  } else {
    const paidPlan = (state.storyPlans.length ? state.storyPlans : FALLBACK_STORY_PLANS).find((plan) => plan.plan_key === state.story?.payment_plan);
    body = `
      <div class="story-progress">Memoir complete</div>
      <h1>Your memoir is ready.</h1>
      <p class="story-lead">Your paid generation has been unlocked${paidPlan ? ` with the ${escapeHtml(paidPlan.name.toLowerCase())} package` : ""}.</p>
      <button class="button button-primary" data-story-action="full-memoir">Generate my memoir <span>↗</span></button>`;
  }

  $("#app").innerHTML = `
    <div class="story-shell conversation-only">
      <header class="story-topbar">
        <a class="brand" href="/memoir" data-action="story-flow-home"><span class="brand-mark">✦</span><span class="brand-name">Memory Spark</span></a>
        <div class="story-topbar-actions"><div class="story-status"><span class="topbar-hint">Saved with Supabase</span></div>${profileMenu()}</div>
      </header>
      <main class="chat-main story-flow-main" aria-label="Memoir story journey">
        <div class="story-flow-card">${body}</div>
        <div class="story-answer-list">${state.storyAnswers.map((answer, index) => `<article><span>Round ${index + 1}</span><p>${formatText(answer)}</p></article>`).join("")}</div>
  </main>
    </div>`;
  bindStoryFlowActions();
  bindProfileMenu();
}

function bindStoryFlowActions() {
  $("[data-action='story-flow-home']")?.addEventListener("click", (event) => {
    event.preventDefault();
    state.story = null;
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
  if (!answer && !state.storyAudioBase64) return toast("A few honest words or a voice answer are enough to continue.");
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
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return toast("This browser cannot record here. You can type your answer instead.");
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
        const transcript = await storyApi("/v1/story/transcriptions", { method: "POST", body: JSON.stringify({ audio_base64: state.storyAudioBase64, filename: state.storyAudioFilename, mime_type: state.storyAudioMimeType, language: profile().preferred_language || "en-AU" }) });
        state.storyTranscript = transcript.text || "";
        toast("Transcript ready. Review it, then save your answer.");
      } catch (error) {
        state.storyAudioBase64 = "";
        toast(error.message || "The recording could not be transcribed. You can type instead.");
      }
      render();
    });
    recorder.start();
    state.storyRecording = true;
    render();
  } catch {
    toast("Microphone access was not available. You can type your answer instead.");
  }
}

async function speakStoryQuestion(text) {
  state.storyAudioPlayer?.pause();
  try {
    const generated = await storyApi("/v1/story/question-audio", { method: "POST", body: JSON.stringify({ text, language: profile().preferred_language || "en-AU", voice: "marin" }) });
    const player = new Audio(URL.createObjectURL(base64ToBlob(generated.audio_base64, generated.mime_type)));
    state.storyAudioPlayer = player;
    player.onended = () => URL.revokeObjectURL(player.src);
    await player.play();
  } catch (error) {
    if (error.status !== 503) toast(error.message);
    if (!window.speechSynthesis) return toast("Read aloud is not available in this browser.");
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = profile().preferred_language || "en-AU";
    utterance.rate = 0.96;
    window.speechSynthesis.speak(utterance);
  }
}

function base64ToBlob(value, mimeType = "application/octet-stream") {
  const bytes = Uint8Array.from(atob(value), (char) => char.charCodeAt(0));
  return new Blob([bytes], { type: mimeType });
}

async function linkStoryIdentity(provider) {
  if (!state.supabase?.client) return toast("Supabase sign-in is not configured.");
  const { error } = await state.supabase.client.auth.linkIdentity({
    provider,
    options: { redirectTo: `${window.location.origin}${MEMOIR_ROUTES.start}` },
  });
  if (error) toast(error.message || `Unable to connect ${provider}.`);
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
  if (state.loading) return;
  state.loading = true;
  try {
    const result = await storyApi("/v1/story/full-memoir", { method: "POST" });
    toast(result.memoir?.status === "generated" ? "Your memoir is ready." : "Memoir generation started.");
  } catch (error) {
    if (error.code === "PAYMENT_REQUIRED" || error.status === 402) {
      state.checkout = await storyApi("/v1/story/checkout", { method: "POST" }).catch(() => null);
    } else {
      toast(error.message);
    }
  } finally {
    state.loading = false;
    render();
  }
}

function render() {
  disposeCesiumPlaceJourney();
  if (!state.project) return renderLanding();
  renderStory();
}

function renderLanding() {
  if (currentPath() === "/") return renderPlatformLanding();
  return renderMemoirLanding();
}

function renderPlatformLanding() {
  $("#app").innerHTML = `
    <div class="platform-landing">
      <header class="landing-header platform-header">
        <a class="brand" href="/" aria-label="CopyMe2 home"><span class="brand-mark">✦</span><span class="brand-name">CopyMe2</span></a>
        <span class="header-note">Preserve the parts of you that matter.</span>
      </header>
      <main class="platform-main">
        <section class="platform-hero">
          <div class="eyebrow">The CopyMe2 platform</div>
          <h1>Preserve the parts of you that matter.</h1>
          <p class="hero-copy">Thoughtful tools for turning the stories, memories, and voice of a life into something a family can keep.</p>
        </section>
        <section class="platform-products" aria-label="CopyMe2 products">
          <article class="product-card product-card-primary">
            <div class="product-kicker">COPYME2 · MEMOIR</div>
            <h2>Start with a conversation.</h2>
            <p>Bring a memory, a photograph, a place, or simply a thought, and let the story find its shape.</p>
            <button class="button button-primary" data-action="open-memoir">Begin my story <span>↗</span></button>
          </article>
          <article class="product-card product-card-muted">
            <div class="product-kicker">COPYME2 · VOICE</div>
            <h2>Voice</h2>
            <p>Coming separately. A future product for keeping your voice close.</p>
            <span class="product-status">Coming soon</span>
          </article>
        </section>
      </main>
    </div>`;
  $("[data-action='open-memoir']")?.addEventListener("click", () => startStory("self"));
}

function renderMemoirLanding() {
  $("#app").innerHTML = `
    <div class="landing">
      <header class="landing-header">
        <a class="brand" href="/memoir" aria-label="Memoir home"><span class="brand-mark">✦</span><span class="brand-name">Memoir</span></a>
        <span class="header-note">A private conversation for one life at a time</span>
      </header>
      <main class="landing-main">
        <section class="hero">
          <div>
            <div class="eyebrow">Start with a conversation</div>
            <h1>Start with a conversation.</h1>
            <p class="hero-copy">Memory Spark starts as a normal Codex conversation. Bring whatever is on your mind; places, pictures, chapters, and delivery options appear beside the chat only when they become useful.</p>
            <div class="hero-actions"><button class="button button-primary" data-action="start-story" data-mode="self">Begin my story <span>↗</span></button><button class="button button-secondary" data-action="start-story" data-mode="family">Help someone I love</button></div>
            <p class="fine-print" style="margin-top:16px">Your first chapter is free. You can pause, skip, correct, or leave at any time.</p>
          </div>
          <div class="hero-art" aria-hidden="true"><div class="orb"></div><div class="memory-card"><div class="card-kicker"><span>MEMORY SPARK · PRIVATE</span><span>listening</span></div><blockquote>“Tell me whatever is on your mind. We’ll follow the thread together.”</blockquote><div class="card-line"></div><div class="card-meta"><span>Conversation first · workspace when useful</span><span>♡</span></div></div></div>
        </section>
        <details class="agent-connect">
          <summary>Connect Codex memory for this session</summary>
          <p>Supabase starts you anonymously, keeps your private story under your user account, and lets you link Google or Facebook after the five free rounds.</p>
          <form id="agent-auth-form">
            <input id="agent-email" type="email" autocomplete="email" placeholder="Email address" aria-label="Codex memory email" />
            <input id="agent-password" type="password" autocomplete="current-password" placeholder="Password" aria-label="Codex memory password" />
            <div class="agent-auth-actions"><button type="button" class="button button-primary button-small" data-auth-action="signin">Sign in</button><button type="button" class="button button-secondary button-small" data-auth-action="signup">Create account</button></div>
          </form>
          <small>${state.supabase?.accessToken ? "Supabase memory is connected for this browser session." : "Supabase Auth is required to start your private story."}</small>
        </details>
        <section class="feature-row"><article class="feature"><div class="feature-icon">◌</div><h3>Talk or type</h3><p>You can answer by voice or text. The assistant can read its questions aloud.</p></article><article class="feature"><div class="feature-icon">⌁</div><h3>Remember with context</h3><p>Public historical references are labelled clearly and never become facts about your life on their own.</p></article><article class="feature"><div class="feature-icon">▱</div><h3>Workspace when ready</h3><p>Chapters, family tree, and timeline appear after your first chapter is finished.</p></article></section>
      </main>
    </div>`;
  document.querySelectorAll('[data-action="start-story"]').forEach((button) => button.addEventListener("click", () => startStory(button.dataset.mode || "self")));
  document.querySelectorAll("[data-auth-action]").forEach((button) => button.addEventListener("click", () => supabaseAuth(button.dataset.authAction)));
}

async function startStory(mode = "self") {
  await startLegacyStory(mode);
}

async function startLegacyStory(mode = "self") {
  try {
    if (state.authPromise) await state.authPromise;
    setLoading(true);
    state.project = await api("/v1/projects", { method: "POST", body: JSON.stringify({ mode, language: "en-AU" }) });
    localStorage.setItem("memory-spark-project", state.project.id);
    await api(`/v1/projects/${state.project.id}/consents`, { method: "POST", body: JSON.stringify({ purpose: "recording", granted: true, locale: "en-AU" }) });
    if (mode === "self") await api(`/v1/projects/${state.project.id}/consents`, { method: "POST", body: JSON.stringify({ purpose: "storyteller_assent", granted: true, locale: "en-AU" }) });
    state.chat = [];
    state.codexStarting = false;
    state.codexReady = false;
    state.placeJourney = null;
    state.workspaceTab = "chapters";
    state.story = null;
    localStorage.removeItem("memory-spark-story-started");
    await refreshProject();
    state.loading = false;
    navigateTo(`${MEMOIR_ROUTES.interview}/${state.project.id}`, true);
    await startCodexConversation();
  } catch (error) {
    state.project = null;
    setLoading(false);
    toast(error.message);
  }
}

async function refreshProject() {
  const projectId = state.project.id;
  const base = await api(`/v1/projects/${projectId}`);
  const journey = await api(`/v1/projects/${projectId}/journey`);
  state.project = { ...base, ...journey };
  state.session = journey.active_session;
  state.preview = state.project.preview || null;
  state.workspaceUnlocked = Boolean(state.workspaceUnlocked || state.project.workspace_unlocked);
  if (state.workspaceUnlocked) {
    const [memories, sources, chapters, people, relationships, timeline] = await Promise.all([
      api(`/v1/projects/${projectId}/memories`),
      api(`/v1/projects/${projectId}/sources`),
      api(`/v1/projects/${projectId}/chapters`),
      api(`/v1/projects/${projectId}/people`),
      api(`/v1/projects/${projectId}/relationships`),
      api(`/v1/projects/${projectId}/timeline`),
    ]);
    state.memories = memories.items;
    state.sources = sources.items;
    state.chapters = chapters.items;
    state.people = people.items;
    state.relationships = relationships.items;
    state.timeline = timeline.items;
  }
}

function renderStory() {
  const unlocked = state.workspaceUnlocked || state.project.workspace_unlocked;
  const workspaceVisible = workspaceIsVisible();
  const contextOnly = workspaceVisible && !unlocked;
  const shellClass = unlocked ? "workspace-visible" : contextOnly ? "context-visible" : "conversation-only";
  activeWorkspaceTab();
  $("#app").innerHTML = `
    <div class="story-shell ${shellClass}">
      <header class="story-topbar">
        <a class="brand" href="#" data-action="story-home"><span class="brand-mark">✦</span><span class="brand-name">Memory Spark</span></a>
        <div class="story-topbar-actions"><div class="story-status"><span class="topbar-hint">Voice is available on both sides</span></div>${profileMenu()}</div>
      </header>
      <div class="conversation-layout">
        ${unlocked ? workspaceRail() : ""}
        <main class="chat-main" aria-label="Memory Spark conversation">
          <div class="chat-heading"><div><div class="eyebrow">${unlocked ? "Your story workspace" : "The conversation comes first"}</div><h1>${unlocked ? "Keep following the thread." : "Let’s remember together."}</h1><p>${unlocked ? "Your chapter, family tree, and timeline are here when you need them." : "Start anywhere. You can speak, type, pause, or change direction at any time."}</p></div><span class="chapter-chip">${unlocked ? `Chapter ${state.chapters.length || 1}` : "Before chapter one"}</span></div>
          <div id="chat-scroll" class="chat-scroll">${state.chat.map(renderMessage).join("")}${state.loading ? `<div class="thinking"><span></span><span></span><span></span><em>${state.supabase?.accessToken ? "Running the Codex loop…" : "Simulating the Codex loop…"}</em></div>` : ""}${placeJourneySurface()}</div>
          ${chatComposer()}
        </main>
        ${workspaceVisible ? workspaceDetail() : ""}
      </div>
    </div>`;
  bindViewActions();
  bindProfileMenu();
  initCesiumPlaceJourney();
  const scroll = $("#chat-scroll");
  if (scroll) scroll.scrollTop = scroll.scrollHeight;
}

function workspaceRail() {
  const tabs = workspaceTabs();
  return `<aside class="workspace-rail" aria-label="Story workspace"><div class="workspace-label">WORKSPACE</div><h2>What we’ve kept</h2><nav class="workspace-tabs">${tabs.map(([key, label, hint]) => `<button class="workspace-tab ${state.workspaceTab === key ? "active" : ""}" data-workspace-tab="${key}"><span>${label}</span><small>${hint}</small></button>`).join("")}</nav><div class="workspace-unlock"><span class="unlock-mark">✦</span><strong>Chapter one is free</strong><small>The workspace opened after your first chapter was finished.</small></div></aside>`;
}

function workspaceDetail() {
  const tabs = workspaceTabs();
  const active = activeWorkspaceTab();
  const title = tabs.find(([key]) => key === active)?.[1] || "Workspace";
  const content = active === "family"
    ? familyWorkspace()
    : active === "timeline"
      ? timelineWorkspace()
      : active === "places"
        ? placesWorkspace()
        : active === "pictures"
          ? picturesWorkspace()
          : active === "delivery"
            ? deliveryWorkspace()
            : chaptersWorkspace();
  const persistent = Boolean(state.workspaceUnlocked || state.project?.workspace_unlocked);
  const tabsMarkup = !persistent && tabs.length > 1
    ? `<nav class="workspace-detail-tabs" aria-label="Context workspace">${tabs.map(([key, label]) => `<button class="workspace-detail-tab ${active === key ? "active" : ""}" data-workspace-tab="${key}">${escapeHtml(label)}</button>`).join("")}</nav>`
    : "";
  return `<aside class="workspace-detail" aria-label="${escapeHtml(title)} workspace"><div class="workspace-detail-top"><div>${persistent ? `<span class="eyebrow">${escapeHtml(title)}</span>` : `<span class="eyebrow">WORKSPACE</span><strong>${escapeHtml(title)}</strong>`}</div><span class="detail-state">${persistent ? "Autosaved" : "From this conversation"}</span></div>${tabsMarkup}${content}</aside>`;
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

function deliveryAvailable() {
  return Boolean(state.storyPlans.length || state.checkout || state.storyChapter || state.story?.next_action === "payment" || state.story?.payment_status === "paid");
}

function workspaceTabs() {
  const tabs = [];
  const persistent = Boolean(state.workspaceUnlocked || state.project?.workspace_unlocked);
  if (state.placeJourney) tabs.push(["places", "Places", "Where memory begins"]);
  if (searchedPictures().length) tabs.push(["pictures", "Pictures", "Searched references"]);
  if (deliveryAvailable()) tabs.push(["delivery", "Delivery", "Your memoir options"]);
  if (persistent) {
    tabs.push(["chapters", "Chapters", "The story"], ["family", "Family tree", "People and ties"], ["timeline", "Timeline", "Dates and moments"]);
    if (!state.placeJourney) tabs.splice(0, 0, ["places", "Places", "Where memory begins"]);
  }
  return tabs;
}

function activeWorkspaceTab() {
  const tabs = workspaceTabs();
  if (!tabs.length) return state.workspaceTab;
  if (!tabs.some(([key]) => key === state.workspaceTab)) state.workspaceTab = tabs[0][0];
  return state.workspaceTab;
}

function workspaceIsVisible() {
  return workspaceTabs().length > 0;
}

function chaptersWorkspace() {
  const chapters = state.chapters.length ? state.chapters.map((chapter) => `<article class="workspace-card chapter-card"><div class="card-topline"><span class="tag">Chapter ${chapter.chapter_number || 1}</span><span class="mini-status">${escapeHtml(chapter.status.toLowerCase())}</span></div><h3>${escapeHtml(chapter.title)}</h3><p>${chapter.blocks?.length || 0} story blocks · ${chapter.source_memory_ids?.length || 0} memories attached</p><div class="source-pills">${sourcePills(chapter.source_memory_ids || [])}</div></article>`).join("") : '<div class="workspace-empty"><span>✦</span><p>Your first chapter will settle here after the conversation is finished.</p></div>';
  return `<div class="workspace-scroll"><div class="workspace-intro"><h2>Chapters</h2><p>Short, honest pieces of a life. Every chapter keeps its source links.</p></div><div class="workspace-list">${chapters}</div>${referencesWorkspace()}</div>`;
}

function familyWorkspace() {
  const people = state.people.length ? state.people.map((person) => `<article class="person-row"><span class="person-avatar">${escapeHtml((person.name || "?").slice(0, 1).toUpperCase())}</span><div><strong>${escapeHtml(person.name)}</strong><small>${escapeHtml(person.family_title || "Family member · relationship to be explored")}</small></div></article>`).join("") : '<div class="workspace-empty"><span>♧</span><p>Names will appear here as you remember the people around you.</p></div>';
  const relationships = state.relationships.map((relation) => { const from = state.people.find((person) => person.id === relation.from_person_id)?.name || "Someone"; const to = state.people.find((person) => person.id === relation.to_person_id)?.name || "Someone"; return `<div class="relationship-row"><span>${escapeHtml(from)}</span><b>→</b><span>${escapeHtml(to)}</span><small>${escapeHtml(relation.relationship_type)}</small></div>`; }).join("");
  return `<div class="workspace-scroll"><div class="workspace-intro"><div class="workspace-heading-row"><div><h2>Family tree</h2><p>Keep names, titles, and uncertainty visible.</p></div><button class="button button-secondary button-small" data-action="add-person">Add person</button></div></div><div class="people-list">${people}</div>${relationships ? `<div class="relationship-list"><div class="eyebrow">Connections</div>${relationships}</div>` : ""}<div class="reference-note">You can refer back to diary notes and old photos while the conversation continues.</div>${referencesWorkspace()}</div>`;
}

function timelineWorkspace() {
  const items = state.timeline.length ? state.timeline.map((item) => `<article class="timeline-row"><span class="timeline-dot"></span><div><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.date_expression || "Date unknown")} · ${escapeHtml(item.precision || "uncertain")}</small></div></article>`).join("") : '<div class="workspace-empty"><span>⌁</span><p>Moments will appear here with their original uncertainty.</p></div>';
  return `<div class="workspace-scroll"><div class="workspace-intro"><div class="workspace-heading-row"><div><h2>Timeline</h2><p>Recorded dates stay separate from historical dates.</p></div><button class="button button-secondary button-small" data-action="add-timeline">Add moment</button></div></div><div class="timeline-list">${items}</div>${referencesWorkspace()}</div>`;
}

function placeMapUrl(journey) {
  if (!Number.isFinite(journey?.latitude) || !Number.isFinite(journey?.longitude)) return "";
  return `https://www.openstreetmap.org/?mlat=${encodeURIComponent(journey.latitude)}&mlon=${encodeURIComponent(journey.longitude)}#map=11/${encodeURIComponent(journey.latitude)}/${encodeURIComponent(journey.longitude)}`;
}

function placeJourneyMarkup(journey, variant = "surface") {
  if (!journey) return "";
  const labels = (journey.hierarchy || []).map((label, index) => `<span class="place-journey-label ${index === journey.hierarchy.length - 1 ? "is-destination" : ""}">${escapeHtml(label)}</span>`).join('<span class="place-journey-arrow" aria-hidden="true">→</span>');
  const mapUrl = placeMapUrl(journey);
  const mapLink = mapUrl ? `<a class="text-button" href="${escapeHtml(mapUrl)}" target="_blank" rel="noreferrer">Open approximate map ↗</a>` : "";
  const latitude = Number.isFinite(journey.latitude) ? journey.latitude : "";
  const longitude = Number.isFinite(journey.longitude) ? journey.longitude : "";
  const duration = Number(journey.duration_ms) || 5200;
  return `<section class="place-journey-card place-journey-${variant}" aria-label="Place journey"><div class="place-journey-heading"><div><div class="eyebrow">A place to return to</div><h2>${escapeHtml(journey.place)}</h2></div><span class="place-journey-status">Approximate ${escapeHtml(journey.granularity || "place")}</span></div><div class="place-journey-scene" style="--journey-duration:${duration}ms"><div class="cesium-place-journey" data-cesium-place="${escapeHtml(journey.place)}" data-cesium-latitude="${latitude}" data-cesium-longitude="${longitude}" data-cesium-duration="${duration}"></div><div class="place-journey-fallback" aria-hidden="true"><span class="journey-earth">◒</span><span class="journey-fallback-line">Earth → ${escapeHtml(journey.place)}</span><span class="journey-pin">✦</span></div><span class="journey-scene-caption">following the thread</span></div><div class="place-journey-hierarchy">${labels}</div><p class="place-journey-note">This is a gentle visual prompt, not proof of an exact address or a fact about your life.</p>${mapLink}</section>`;
}

function placeJourneySurface() {
  return state.placeJourney && !workspaceIsVisible() ? placeJourneyMarkup(state.placeJourney) : "";
}

function placesWorkspace() {
  if (!state.placeJourney) return '<div class="workspace-scroll"><div class="workspace-intro"><h2>Places</h2><p>When a place becomes part of the conversation, its journey will settle here.</p></div><div class="workspace-empty"><span>◎</span><p>Name a country, region, town, or neighbourhood and I’ll keep the map broad and approximate.</p></div></div>';
  return `<div class="workspace-scroll"><div class="workspace-intro"><h2>Places</h2><p>Follow the geography of a memory without turning it into an exact address.</p></div>${placeJourneyMarkup(state.placeJourney, "workspace")}<div class="reference-note">You can correct the place at any time. The journey is separate from the words you choose to save.</div></div>`;
}

function picturesWorkspace() {
  const pictures = searchedPictures();
  return `<div class="workspace-scroll"><div class="workspace-intro"><h2>Pictures</h2><p>Public references found during the conversation stay here as prompts, never as facts about your life.</p></div>${pictures.length ? renderCueCards(pictures) : '<div class="workspace-empty"><span>▧</span><p>When a picture or historical reference is searched, it will appear here.</p></div>'}</div>`;
}

function deliveryWorkspace() {
  const plans = state.storyPlans.length ? state.storyPlans : FALLBACK_STORY_PLANS;
  const selected = plans.find((plan) => plan.plan_key === state.selectedStoryPlan) || plans[0];
  const chapter = state.storyChapter ? `<article class="workspace-card"><div class="eyebrow">Chapter one</div><h3>${escapeHtml(state.storyChapter.title || "Your first chapter")}</h3><p>${formatText(state.storyChapter.text || "Your first chapter is ready to review.")}</p></article>` : "";
  const planCards = plans.slice(0, 3).map((plan) => `<article class="workspace-card delivery-card ${plan.plan_key === selected?.plan_key ? "selected" : ""}"><div class="card-topline"><span class="tag">${escapeHtml(plan.name)}</span><strong>${formatAudMinor(plan.price_minor)}</strong></div><p>${escapeHtml(plan.description)}</p><small>${plan.features?.slice(0, 2).map((feature) => `✓ ${escapeHtml(feature)}`).join(" · ") || "Electronic memoir delivery"}</small></article>`).join("");
  return `<div class="workspace-scroll"><div class="workspace-intro"><h2>Delivery</h2><p>Choose how the story should reach you when a chapter is ready.</p></div>${chapter}<div class="workspace-list">${planCards}</div>${state.checkout?.message ? `<div class="reference-note">${escapeHtml(state.checkout.message)}</div>` : ""}</div>`;
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

function initCesiumPlaceJourney() {
  const container = $("[data-cesium-place]");
  if (!container) return;
  const latitude = Number(container.dataset.cesiumLatitude);
  const longitude = Number(container.dataset.cesiumLongitude);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
  loadCesium().then((cesium) => {
    if (!container.isConnected) return;
    let viewer = null;
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
      scene3DOnly: true,
      shouldAnimate: false,
      });
      cesiumPlaceJourneyViewer = viewer;
      viewer.scene.backgroundColor = cesium.Color.fromCssColorString("#173f45");
      viewer.scene.globe.enableLighting = true;
      viewer.scene.skyAtmosphere.show = true;
      const destination = cesium.Cartesian3.fromDegrees(longitude, latitude, 7_500);
      viewer.entities.add({
      position: destination,
      point: {
        color: cesium.Color.fromCssColorString("#f3c66b"),
        outlineColor: cesium.Color.fromCssColorString("#fff8e7"),
        outlineWidth: 2,
        pixelSize: 12,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      label: {
        text: container.dataset.cesiumPlace || "Memory place",
        fillColor: cesium.Color.WHITE,
        font: "600 14px DM Sans, sans-serif",
        style: cesium.LabelStyle.FILL_AND_OUTLINE,
        outlineColor: cesium.Color.fromCssColorString("#173f45"),
        outlineWidth: 3,
        pixelOffset: new cesium.Cartesian2(0, -24),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      });
      viewer.camera.setView({
      destination: cesium.Cartesian3.fromDegrees(0, 18, 31_000_000),
      orientation: {
        heading: 0,
        pitch: cesium.Math.toRadians(-68),
        roll: 0,
      },
      });
      viewer.camera.flyTo({
      destination,
      orientation: {
        heading: cesium.Math.toRadians(8),
        pitch: cesium.Math.toRadians(-38),
        roll: 0,
      },
      duration: Math.max(2.8, Math.min(9, Number(container.dataset.cesiumDuration || 5200) / 1000)),
      easingFunction: cesium.EasingFunction.QUADRATIC_IN_OUT,
      });
      container.closest(".place-journey-scene")?.classList.add("is-cesium-live");
    } catch (error) {
      if (viewer && !viewer.isDestroyed()) viewer.destroy();
      if (cesiumPlaceJourneyViewer === viewer) cesiumPlaceJourneyViewer = null;
      console.warn("Cesium place journey unavailable; using the hierarchy fallback.", error);
    }
  }).catch((error) => console.warn("Cesium place journey unavailable; using the hierarchy fallback.", error));
}

function referencesWorkspace() {
  const references = state.sources.slice(0, 5);
  if (!references.length) return '<div class="reference-shelf"><div class="eyebrow">References</div><p class="fine-print">Diary notes and old photos you add will stay beside the story as sources.</p></div>';
  return `<div class="reference-shelf"><div class="eyebrow">References</div><p class="fine-print">Diary and photo sources stay separate from the words they help you remember.</p>${references.map((item) => `<div class="reference-row"><span class="reference-icon">${item.kind === "photo" ? "▧" : "✎"}</span><div><strong>${escapeHtml(item.filename || item.historical_date_expression || "Personal source")}</strong><small>${escapeHtml(item.kind || "source")} · ${item.original_retained ? "original retained" : "source note"}</small></div></div>`).join("")}</div>`;
}

function sourcePills(memoryIds) {
  if (!memoryIds.length) return '<span class="source-pill">No memory links</span>';
  return memoryIds.map((id) => `<span class="source-pill">${escapeHtml(id.slice(-8))}</span>`).join("");
}

function chatComposer() {
  const voiceLabel = state.recording ? "Stop voice input" : "Speak your answer";
  const note = state.audioUploadId ? "Review the transcript, then press send when you are ready." : "Your words stay attached to their source.";
  return `<div class="composer-wrap"><form id="chat-form" class="chat-composer"><button type="button" class="voice-button ${state.recording ? "recording" : ""}" data-action="voice-input" aria-label="${voiceLabel}" title="${voiceLabel}">${state.recording ? "■" : "●"}</button><textarea id="chat-input" rows="1" placeholder="Type a message, or use your voice…" aria-label="Your message">${escapeHtml(state.audioTranscript)}</textarea><button type="submit" class="send-button" aria-label="Send message">↗</button></form><div class="composer-note"><span>${note}</span><span>Press Enter to send · Shift + Enter for a new line</span></div></div>`;
}

function renderMessage(message) {
  if (message.role === "user") return `<article class="chat-row user-message"><div class="chat-bubble"><div class="message-label">You</div><div class="message-text">${formatText(message.text)}</div></div><span class="chat-avatar user-avatar">You</span></article>`;
  const action = message.action ? `<button class="button button-primary button-small message-action" data-action="${message.action.name}">${escapeHtml(message.action.label)} <span>↗</span></button>` : "";
  const cues = message.cues?.length && !workspaceIsVisible() ? renderCueCards(message.cues) : "";
  const trace = message.trace?.length ? renderAgentTrace(message.trace, message.traceMode) : "";
  return `<article class="chat-row assistant-message"><span class="chat-avatar assistant-avatar">✦</span><div class="chat-bubble"><div class="message-meta"><span class="message-label">Memory Spark</span><button class="listen-button" data-action="speak" data-text="${escapeHtml(message.text)}" aria-label="Read this message aloud with an AI-generated voice">◖ Listen · AI voice</button></div><div class="message-text">${formatText(message.text)}</div>${trace}${cues}${action}</div></article>`;
}

function renderAgentTrace(trace, mode = "simulated") {
  const title = mode === "codex" ? "Codex agent loop" : "Simulated Codex loop";
  const steps = trace.map((step) => `<li class="agent-loop-step agent-loop-${escapeHtml(step.kind || "analysis")}"><span class="agent-loop-kind">${escapeHtml(step.label || step.kind || "step")}</span><span class="agent-loop-detail">${escapeHtml(step.detail || "")}</span></li>`).join("");
  return `<details class="agent-loop"><summary><span>${title}</span><small>${trace.length} steps</small></summary><p class="agent-loop-note">High-level actions and tool results are shown here. Private model reasoning stays hidden.</p><ol class="agent-loop-list">${steps}</ol></details>`;
}

function renderCueCards(cues) {
  return `<div class="cue-section"><div class="cue-section-label">Public history cues · not personal evidence</div><div class="cue-grid">${cues.map((cue) => `<article class="photo-card"><div class="photo-art ${cue.kind === "video" ? "video-art" : "image-art"}"><span>${cue.kind === "video" ? "▶" : "✦"}</span></div><div class="photo-card-body"><strong>${escapeHtml(cue.title)}</strong><small>${escapeHtml(cue.location || "Historical reference")} · ${escapeHtml(cue.scene_date_range?.start || "date unknown")}–${escapeHtml(cue.scene_date_range?.end || "")}</small><p>${escapeHtml(cue.label)}</p><div class="photo-actions"><a href="${escapeHtml(cue.source_url || "#")}" target="_blank" rel="noreferrer">View source</a><button class="text-button" data-action="cue-reaction" data-asset="${escapeHtml(cue.asset_id)}" data-reaction="familiar">Familiar</button><button class="text-button" data-action="cue-reaction" data-asset="${escapeHtml(cue.asset_id)}" data-reaction="different">Different</button></div></div></article>`).join("")}</div></div>`;
}

function bindViewActions() {
  $("[data-action='story-home']")?.addEventListener("click", (event) => { event.preventDefault(); state.chat = []; state.placeJourney = null; state.workspaceTab = "chapters"; render(); });
  $("#chat-form")?.addEventListener("submit", (event) => { event.preventDefault(); sendChatMessage(); });
  $("#chat-input")?.addEventListener("input", (event) => { state.audioTranscript = event.target.value; });
  $("#chat-input")?.addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendChatMessage(); } });
  document.querySelectorAll("[data-workspace-tab]").forEach((button) => button.addEventListener("click", () => { state.workspaceTab = button.dataset.workspaceTab; render(); }));
  const actions = {
    "start-memory": startMemory,
    "save-memory": completeMemory,
    "finish-chapter": finishChapter,
    "continue-memory": startMemory,
    "voice-input": toggleVoiceInput,
    "speak": (button) => speakText(button.dataset.text),
    "cue-reaction": (button) => reactCue(button.dataset.asset, button.dataset.reaction),
    "add-person": addPerson,
    "add-timeline": addTimeline,
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
    // Codex remains usable when the legacy chapter/session adapter is unavailable.
    return null;
  }
}

async function beginMemoryConversation(renderNow = true) {
  await ensureMemorySession();
  const fallback = CODEX_START_FALLBACK;
  const result = await agentTurn("The storyteller wants to begin exploring a memory. Invite them to share whatever comes to mind, without using a fixed onboarding question.", fallback, ["memory.start", "memory.search"]);
  state.chat.push({ role: "assistant", text: result.reply || fallback, trace: result.trace, traceMode: result.traceMode });
  try {
    const context = await api(`/v1/projects/${state.project.id}/context-search`, { method: "POST", body: JSON.stringify({ coarse_place: profile().birth_place || profile().childhood_place || null, approximate_year_start: profile().birth_year ? profile().birth_year + 5 : null, approximate_year_end: profile().birth_year ? profile().birth_year + 16 : null, topic_id: "childhood_home", language: profile().preferred_language || "en-AU", requested_media: ["image"] }) });
    if (context.items?.length) state.chat.push({ role: "assistant", text: "While you think, I found a few public historical references from that broad place and period. See if any feeling or detail comes back; you can also ignore them.", cues: context.items });
  } catch {
    // A context provider can be unavailable; the conversation continues without it.
  }
  if (renderNow) render();
}

async function startMemory() {
  if (state.loading) return;
  try {
    state.loading = true;
    render();
    await ensureMemorySession();
    const fallback = CODEX_START_FALLBACK;
    const result = await agentTurn("The storyteller wants to continue with another memory. Ask one open-ended question based on the conversation, without restarting onboarding.", fallback, ["memory.start", "memory.search"]);
    state.chat.push({ role: "assistant", text: result.reply || fallback, trace: result.trace, traceMode: result.traceMode });
  } catch (error) { toast(error.message); }
  state.loading = false;
  render();
}

async function sendChatMessage() {
  if (state.loading) return;
  const input = $("#chat-input");
  const text = input?.value.trim() || "";
  const uploadId = state.audioUploadId;
  if (!text && !uploadId) return toast("A few words or a voice answer are enough to continue.");
  state.chat.push({ role: "user", text: text || "Voice answer" });
  state.loading = true;
  state.audioUploadId = null;
  state.audioTranscript = "";
  render();
  try {
    const session = await ensureMemorySession();
    let cues = [];
    let action = null;
    let fallback = "Thank you for sharing that. What part of it feels most important to you?";
    let instruction = "Acknowledge the storyteller naturally, then ask one gentle open-ended follow-up question. Do not restart onboarding or request profile fields.";
    if (session) {
      try {
        const turnType = session.turns?.length ? "follow_up" : "initial";
        state.session = await api(`/v1/memory-sessions/${session.id}/answers`, { method: "POST", body: JSON.stringify({ text, upload_id: uploadId, turn_type: turnType }) });
        cues = state.session.context_cues || [];
        if (cues.length) state.workspaceTab = "pictures";
        const remaining = memoryFollowUpsRemaining(state.session);
        fallback = memoryTurnFallback(state.session);
        instruction = remaining > 0
          ? "Acknowledge the storyteller in one sentence, then ask exactly one gentle follow-up question or offer one clearly labelled hint that helps the memory unfold. Do not suggest saving yet."
          : "Acknowledge the storyteller briefly, say there is enough detail to shape the first chapter, and tell them they can save this memory now. Do not ask another question.";
        if (remaining === 0) action = { name: "save-memory", label: "Save this memory" };
      } catch {
        // The open Codex conversation is the primary path; legacy session state is optional.
        state.session = null;
      }
    }
    const result = await agentTurn(`The storyteller said: ${text || "[voice answer]"}\n${instruction}`, fallback, ["memory.save", "memory.search"]);
    const cuesAlreadyShown = state.chat.some((message) => message.cues?.length);
    state.chat.push({ role: "assistant", text: result.reply || fallback, trace: result.trace, traceMode: result.traceMode, cues: cues.length && !cuesAlreadyShown ? cues : undefined, action });
  } catch (error) { toast(error.message); }
  state.loading = false;
  render();
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
    const decisionText = decisionResponse.free ? "This memory has enough shape to become the first chapter. It is free, and I’ll open the workspace after you finish it." : decisionResponse.should_start_new_chapter ? `I think this begins ${decisionResponse.title}. I’ll keep it as a separate chapter.` : "I’ll keep this memory with the current chapter.";
    state.chat.push({ role: "assistant", text: decisionText, trace: simulatedLoopTrace(["memory.complete", "chapter.decide"], "Explain the chapter decision and keep the first approved chapter free."), traceMode: "simulated", action: decisionResponse.should_start_new_chapter ? { name: "finish-chapter", label: decisionResponse.free ? "Finish my free first chapter" : `Finish chapter ${decisionResponse.chapter_number}` } : { name: "start-memory", label: "Continue the conversation" } });
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
    const chapterText = decision.free ? "Chapter one is finished, and it’s yours. I’ve opened the workspace beside us so you can keep the chapter, family tree, timeline, diary notes, and photos in view." : `Chapter ${decision.chapter_number} is finished. I’ll keep the workspace open while we continue.`;
    state.chat.push({ role: "assistant", text: chapterText, trace: simulatedLoopTrace(["chapter.build", "chapter.approve"], "Confirm the chapter and reveal the workspace tabs."), traceMode: "simulated" });
    await refreshProject();
  } catch (error) { toast(error.message); }
  state.loading = false;
  render();
}

async function reactCue(assetId, reaction) {
  if (!state.session) return;
  try { await api(`/v1/memory-sessions/${state.session.id}/cue-reactions`, { method: "POST", body: JSON.stringify({ asset_id: assetId, reaction }) }); toast(reaction === "different" ? "Got it — your life stays the authority." : "Saved as a memory prompt, not a fact."); } catch (error) { toast(error.message); }
}

async function speakText(text) {
  state.audioPlayer?.pause();
  if (state.session) {
    try {
      const generated = await api(`/v1/memory-sessions/${state.session.id}/question-audio`, {
        method: "POST",
        body: JSON.stringify({ language: profile().preferred_language || "en-AU", voice: "marin" }),
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
  if (!window.speechSynthesis) return toast("Read aloud is not available in this browser.");
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = profile().preferred_language || "en-AU";
  utterance.rate = 0.96;
  utterance.onend = () => { state.speaking = false; };
  state.speaking = true;
  window.speechSynthesis.speak(utterance);
}

function toggleVoiceInput() {
  if (state.recording && state.recorder) { state.recorder.stop(); return; }
  startAudioRecorder();
}

async function startAudioRecorder() {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) return toast("This browser cannot record here. You can type your answer instead.");
  try {
    state.recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const preferredMime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((value) => window.MediaRecorder.isTypeSupported?.(value));
    const recorder = preferredMime ? new MediaRecorder(state.recordingStream, { mimeType: preferredMime }) : new MediaRecorder(state.recordingStream);
    state.recorder = recorder;
    state.recordedChunks = [];
    recorder.addEventListener("dataavailable", (event) => { if (event.data.size) state.recordedChunks.push(event.data); });
    recorder.addEventListener("stop", async () => {
      const blob = new Blob(state.recordedChunks, { type: recorder.mimeType || "audio/webm" });
      state.recordingStream?.getTracks().forEach((track) => track.stop());
      state.recordingStream = null;
      state.recording = false;
      state.recorder = null;
      if (!blob.size) return render();
      try {
        const encoded = await blobToBase64(blob);
        const mimeType = (blob.type || recorder.mimeType || "audio/webm").split(";")[0];
        const created = await api("/v1/uploads", { method: "POST", body: JSON.stringify({ project_id: state.project.id, kind: "audio", filename: `memory-${Date.now()}.webm`, mime_type: mimeType, expected_size: blob.size }) });
        await api(`/v1/uploads/${created.id}/parts`, { method: "POST", body: JSON.stringify({ sequence: 0, content: encoded }) });
        await api(`/v1/uploads/${created.id}/finalize`, { method: "POST", body: JSON.stringify({}) });
        const transcript = await api(`/v1/uploads/${created.id}/transcription`, { method: "POST", body: JSON.stringify({ language: profile().preferred_language || "en-AU" }) });
        state.audioUploadId = created.id;
        state.audioTranscript = transcript.source.text || "";
        toast("Transcript ready. Review it, then press send.");
      } catch (error) { toast(error.message); }
      render();
    });
    recorder.start();
    state.recording = true;
    render();
  } catch { toast("Microphone access was not available. You can type your answer instead."); }
}

function blobToBase64(blob) { return new Promise((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1] || ""); reader.onerror = reject; reader.readAsDataURL(blob); }); }

async function addPerson() {
  const name = prompt("Who is this?", "Older brother");
  if (!name) return;
  try { await api(`/v1/projects/${state.project.id}/people`, { method: "POST", body: JSON.stringify({ name, family_title: name === "Older brother" ? "older brother" : null }) }); await refreshProject(); render(); } catch (error) { toast(error.message); }
}

async function addTimeline() {
  const title = prompt("What happened?", "Started school");
  if (!title) return;
  try { await api(`/v1/projects/${state.project.id}/timeline`, { method: "POST", body: JSON.stringify({ title, date_expression: "unknown", precision: "unknown" }) }); await refreshProject(); render(); } catch (error) { toast(error.message); }
}

async function boot() {
  state.authPromise = ensureAuth();
  try {
    await state.authPromise;
    // The old five-round entry point was client-only state. Clear it so a
    // refresh always returns to the persistent Codex conversation instead of
    // reopening a fixed question card.
    localStorage.removeItem("memory-spark-story-started");
    const saved = localStorage.getItem("memory-spark-project");
    if (saved) {
      try {
        state.project = { id: saved };
        await refreshProject();
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
window.addEventListener("click", (event) => {
  const menu = $("[data-profile-menu]");
  if (menu && !menu.contains(event.target)) closeProfileMenu();
});
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeProfileMenu(true);
});
renderLanding();
boot();
