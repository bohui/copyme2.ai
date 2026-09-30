const fallbackMessages = {
  Common: {
    language: "Language",
    you: "You",
    profile: "Profile",
    account: "ACCOUNT",
    openProfile: "Open profile menu",
    logout: "Log out",
    privateSession: "Private session",
    anonymousSession: "Anonymous session",
    yourProfile: "Your profile",
    supabaseAccount: "Private memory account",
    finishRecordingFirst: "Finish saving the current recording before changing languages.",
    loading: "Opening your private conversation…",
    loadError: "The Memoir workspace could not be loaded.",
  },
  Errors: {
    generic: "Something went wrong. Please try again.",
    sessionExpired: "Your private session expired. Sign in again to reconnect your memory.",
    paymentRequired: "Your free chapter is ready. Choose a package to continue.",
    entitlementRequired: "This action needs an active memoir package.",
    invalidAudio: "That recording could not be read. Try recording again or type your answer.",
    alreadyPaid: "This memoir already has a paid package.",
    invalidCheckout: "The checkout request could not be verified. Please choose the package again.",
    stripeMismatch: "The payment details did not match the selected package.",
    supabaseNotConfigured: "Private memory sign-in is not configured yet.",
    sessionUnavailable: "Your private memory session is unavailable. Sign in again to continue.",
    anonymousDisabled: "Guest access is unavailable. Sign in to continue with your memories.",
    authInput: "Enter an email and a password of at least 8 characters.",
    authFailed: "We could not connect your private memory account. Check your details and try again.",
    authConfirm: "Account created. Confirm the email, then sign in to connect your private memory.",
    memoryConnected: "Private memory is connected for this session.",
    logoutFailed: "Unable to log out right now. Please try again.",
    identityLinkFailed: "Unable to connect that sign-in provider. Please try again.",
  },
  Platform: {
    brand: "CopyMe2",
    homeAria: "CopyMe2 home",
    headerNote: "Every life holds a story.",
    eyebrow: "A question only you can answer",
    title: "Who am I?",
    description: "Turn your memories into stories your family can keep. Start wherever life takes you.",
    reflection: "The people you’ve loved. The places you’ve called home. The moments that made you, you.",
    products: "CopyMe2 products",
    memoirKicker: "COPYME2 · MEMOIR",
    memoirTitle: "Preserve the parts of you that matter.",
    memoirBody: "Start with a memory, place, or thought; make a story your family can keep.",
    begin: "Begin my story",
    diaryKicker: "COPYME2 · DIARY",
    diaryTitle: "Keep the everyday close.",
    diaryBody: "A private place for the small moments, thoughts, and details you’ll want to remember.",
    comingStatus: "Coming soon",
  },
  Memoir: {
    landing: {
      eyebrow: "Start with a conversation",
      title: "Start with a conversation.",
    },
    conversation: {
      opening: "Hi, I’m Mira. It’s nice to meet you.\n\nI’m here to help you tell your story, one memory at a time. You don’t need to remember everything, and there’s no right place to begin. I’ll ask a few simple questions, listen to what comes to mind, and sometimes show you old photos, places, or things from the past that might bring back a memory.\n\nWe’ll take it slowly, and you can skip anything you don’t feel like talking about.\n\nFirst, what would you like me to call you?",
      resume: "Welcome back. Your private profile and memories are ready; continue wherever the story leads.",
      fallback: "I’m here with you—continue wherever the story leads.",
      publicCueFollowUp: "Those public references are only prompts. Continue with whichever detail feels true to your memory.",
      memoryFollowUp: "Thank you for sharing that. Continue with whichever part of the memory feels most present.",
      memoryComplete: "Thank you. I have enough detail to shape the first chapter. Save this memory when it feels right.",
    },
    trace: {
      title: "Thinking steps",
      stepCount: "{count} steps",
      note: "High-level actions and tool results are shown here. Private model reasoning stays hidden.",
      analysisLabel: "Analyze",
      respondLabel: "Respond",
      analysis: "Classify the storyteller’s message and choose the next safe step.",
      toolCall: "Call {tool} with the current story context.",
      toolResult: "Completed with source-linked data; no personal facts were inferred.",
      final: "Return one concise, speakable question grounded in the conversation.",
      opening: "Show the fixed opening message before profile intake begins.",
    },
    story: {
      listen: "Read this message aloud with an AI-generated voice",
      listenButton: "Listen · AI voice",
      brand: "Memory Spark",
      thinkingCodex: "Thinking…",
      thinkingSimulated: "Thinking…",
      chapterSummary: "{blocks} story blocks · {memories} memories attached",
      workspaceSuffix: "workspace",
      chapterLabel: "Chapter {number}",
    },
  },
};

const MISSING_TRANSLATION = "Translation unavailable";

function readMessage(messages, path) {
  return path.split(".").reduce((current, key) => current?.[key], messages);
}

export function currentUiLocale() {
  return globalThis.__copyme2Intl?.locale || "en-AU";
}

export function translate(path) {
  const messages = globalThis.__copyme2Intl?.messages || fallbackMessages;
  const value = readMessage(messages, path);
  if (typeof value === "string") return value;
  const fallback = readMessage(fallbackMessages, path);
  if (typeof fallback === "string") return fallback;
  console.warn(`Missing UI translation: ${path}`);
  return MISSING_TRANSLATION;
}

export function translateWith(path, values = {}) {
  return Object.entries(values).reduce(
    (message, [key, value]) => message.replaceAll(`{${key}}`, String(value)),
    translate(path),
  );
}
