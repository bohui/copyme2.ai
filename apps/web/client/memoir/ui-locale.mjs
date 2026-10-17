import { createPreferenceSession, firstReplyUiCandidate } from "../../i18n/session.mjs";
import { currentUiLocale, translate } from "../i18n.js";
import { preferenceCookie, readPreference } from "../../i18n/preference.mjs";

export const UI_LOCALES = new Set(["en-AU", "zh-CN"]);

export function createUiLocale({
  captureProjectScope, isCurrentProjectScope, preserveConversationLocale, profile, state, storyApi, toast
}) {
  function readCookie(name) {
    const prefix = `${name}=`;
    const match = document.cookie.split("; ").find((item) => item.startsWith(prefix));
    try { return match ? decodeURIComponent(match.slice(prefix.length)) : ""; } catch { return ""; }
  }

  const uiPreferenceSession = createPreferenceSession();
  let writeTail = Promise.resolve();

  function currentUiPreference() {
    return uiPreferenceSession.preference || readPreference(readCookie(preferenceCookie), state.supabase?.user?.id || null);
  }

  function clearDerivedUiPreference() {
    uiPreferenceSession.invalidate();
    document.cookie = `${preferenceCookie}=; Path=/; Max-Age=0; SameSite=Lax`;
  }

  async function syncAccountUiLocale() {
    if (uiPreferenceSession.busy) return;
    const scope = uiPreferenceSession.capture();
    let preference = await uiPreferenceSession.refresh();
    if (!uiPreferenceSession.current(scope) || uiPreferenceSession.busy) return;
    if (!preference && state.supabase?.user?.is_anonymous) {
      const beforeSignIn = readPreference(readCookie(preferenceCookie), null);
      if (beforeSignIn?.source === "manual") {
        preference = await uiPreferenceSession.choose(beforeSignIn.locale, "manual");
        if (!preference) return;
      }
    }
    if (!preference) return;
    await globalThis.__copyme2SetUiLocale?.(preference.locale, {
      persistAccount: false, persistCookie: true, source: preference.source,
    });
  }

  async function settleUiLocale() {
    const scope = captureProjectScope();
    let writes;
    do {
      writes = writeTail;
      await writes;
      if (!isCurrentProjectScope(scope)) return false;
      const hydration = state.conversationLocaleHydration;
      if (hydration && isCurrentProjectScope(hydration.scope)) await hydration.promise;
      if (!isCurrentProjectScope(scope)) return false;
      if (!uiPreferenceSession.resolved) await syncAccountUiLocale();
      if (!isCurrentProjectScope(scope)) return false;
    } while (writes !== writeTail);
    return uiPreferenceSession.resolved && !uiPreferenceSession.busy;
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
    const preference = currentUiPreference();
    return Boolean(preference && ["manual", "first_reply", "profile"].includes(preference.source));
  }

  async function applyProfileUiLocale(locale) {
    if (!UI_LOCALES.has(locale) || uiPreferenceSession.busy || uiPreferenceSession.preference || currentUiPreference()?.source === "manual" || currentUiLocale() === locale) return false;
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
    if (!UI_LOCALES.has(locale) || uiPreferenceSession.busy || hasFixedUiLocale()) return false;
    const setUiLocale = globalThis.__copyme2SetUiLocale;
    if (typeof setUiLocale !== "function") return false;
    // This is the explicitly requested product exception: only the first
    // narrator answer may provide a bounded UI-language signal. It changes
    // the durable viewer UI preference, only if no established preference wins.
    const changed = await setUiLocale(locale, { persistAccount: true, persistCookie: true, source: "first_reply" });
    return changed;
  }

  async function persistCommittedFirstReplyUiLocale(privateProfile) {
    const locale = firstReplyUiCandidate(privateProfile);
    if (!locale || uiPreferenceSession.busy || uiPreferenceSession.preference || currentUiPreference()?.source === "manual") return false;
    return globalThis.__copyme2SetUiLocale?.(locale, {persistAccount:true, persistCookie:true, source:"first_reply"});
  }

  async function syncProfileUiLocale() {
    const scope = captureProjectScope();
    if (uiPreferenceSession.preference || currentUiPreference()?.source === "manual") return false;
    let privateProfile = state.project?.profile;
    let preferredLanguage = privateProfile?.preferred_language;
    if (!preferredLanguage && state.supabase?.accessToken) {
      try {
        privateProfile = await storyApi("/v1/agent/profile");
        preferredLanguage = privateProfile.preferred_language;
      } catch {
        // The profile endpoint is optional during boot; conversation still works.
      }
    }
    if (!isCurrentProjectScope(scope)) return false;
    await persistCommittedFirstReplyUiLocale(privateProfile);
    if (isCurrentProjectScope(scope)) return applyProfileUiLocale(preferredLanguage);
  }

  function installUiLocaleBridge() {
    globalThis.__copyme2UiLocaleScope = () => uiPreferenceSession.capture();
    globalThis.__copyme2UiLocaleScopeCurrent = (scope) => uiPreferenceSession.current(scope)
      && !state.recording && !state.storyRecording && !state.voiceModeRecorder;
    globalThis.__copyme2BeforeUiLocaleChange = async (nextLocale, { persistAccount = true, source = "manual" } = {}) => {
      if (!UI_LOCALES.has(nextLocale)) return false;
      if (uiPreferenceSession.busy && (!persistAccount || source !== "manual")) return false;
      if (state.recording || state.storyRecording || state.voiceModeRecorder) {
        toast(translate("Common.finishRecordingFirst"));
        return false;
      }
      if (persistAccount) uiPreferenceSession.beginIntent();
      const scope = uiPreferenceSession.capture();
      const projectId = state.project?.id;
      const navigationGeneration = state.navigationGeneration;
      const perform = async () => {
        if (!uiPreferenceSession.current(scope) || state.project?.id !== projectId
          || state.navigationGeneration !== navigationGeneration
          || state.recording || state.storyRecording || state.voiceModeRecorder) {
          uiPreferenceSession.cancelIntent(scope);
          return false;
        }
        let conversationSaved = persistAccount && source === "manual"
          && profile().preferred_language === nextLocale && profile().conversation_language?.source === "explicit";
        if (persistAccount && source === "manual" && !conversationSaved && state.project && state.supabase?.accessToken) {
          try {
            const saved = await storyApi("/v1/agent/profile", {method:"PATCH", body:JSON.stringify({preferred_language:nextLocale})});
            if (state.project?.id !== projectId || state.navigationGeneration !== navigationGeneration || !uiPreferenceSession.current(scope)) {
              uiPreferenceSession.cancelIntent(scope);
              return false;
            }
            state.project = {...state.project, profile:preserveConversationLocale({...profile(), ...saved}, profile())};
            conversationSaved = true;
          } catch {
            if (uiPreferenceSession.current(scope)) toast(translate("Profile.saveError"));
            uiPreferenceSession.cancelIntent(scope);
            return false;
          }
        }
        if (!uiPreferenceSession.current(scope)) return false;
        if (!persistAccount) return { locale: nextLocale, source, scope };
        try {
          const preference = await uiPreferenceSession.choose(nextLocale, source);
          if (!preference) return false;
          return { ...preference, scope: uiPreferenceSession.capture() };
        } catch {
          toast(translate(conversationSaved ? "Common.languagePartiallySaved" : "Profile.saveError"));
          return false;
        }
      };
      if (!persistAccount) return perform();
      // Serialize the conversation PATCH together with its account write. A newer
      // intent supersedes queued work, while an in-flight older PATCH finishes
      // before the newer action is dispatched to either persistence destination.
      const operation = writeTail.then(perform);
      writeTail = operation.catch(() => {});
      return operation;
    };
  }

  return {
    applyFirstReplyLocalization, applyProfileUiLocale, clearDerivedUiPreference, currentUiPreference, firstReplyLanguage,
    installUiLocaleBridge, persistCommittedFirstReplyUiLocale, readCookie, syncAccountUiLocale,
    settleUiLocale, syncProfileUiLocale, uiPreferenceSession
  };
}
