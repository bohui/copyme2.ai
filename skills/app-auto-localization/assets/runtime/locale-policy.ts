/** CopyMe2 reference policy. Pure functions; no cookies, network, LLMs or DB writes.
 * Copy/adapt into the app after reading references/integration.md.
 * All context fields must be derived by application code, not accepted as authority
 * from a model, website, memoir, or arbitrary request body.
 */
export const UI_LOCALES = ['en-AU', 'zh-CN'] as const;
export type UiLocale = (typeof UI_LOCALES)[number];
export const DEFAULT_UI_LOCALE: UiLocale = 'en-AU';
export const UI_COOKIE = 'copyme2_ui_locale';
export const AUTO_COOKIE = 'copyme2_ui_auto';
export const AUTO_POLICY_VERSION = 'copyme2-auto-ui-v1';

export function isUiLocale(value: unknown): value is UiLocale {
  return typeof value === 'string' && UI_LOCALES.some((item) => item === value);
}

/** Catalogue matching, not nationality, residence, dialect or script detection.
 * Generic zh is a product fallback to the initial Simplified Chinese catalogue.
 * Explicit Traditional Chinese requests are not silently collapsed into zh-CN.
 */
export function matchSupportedLocale(value: unknown): UiLocale | null {
  if (typeof value !== 'string' || value.length > 100) return null;
  try {
    const tag = new Intl.Locale(value.trim());
    if (tag.language === 'en') return 'en-AU';
    if (tag.language !== 'zh') return null;
    if (tag.script === 'Hant') return null;
    if (tag.script && tag.script !== 'Hans') return null;
    if (!tag.script && ['TW', 'HK', 'MO'].includes(tag.region ?? '')) return null;
    return 'zh-CN';
  } catch {
    return null;
  }
}

export type LocaleSource = 'device' | 'account' | 'session' | 'browser' | 'default';
export interface LocaleResolution {
  locale: UiLocale;
  source: LocaleSource;
  locked: boolean;
}
export interface ResolveInput {
  /** Explicit device preference only, not an inferred/cached locale. */
  deviceLocale?: unknown;
  /** Fixed preference of the authenticated viewer, not the project owner. */
  accountLocale?: unknown;
  /** Verified, viewer-scoped, unexpired automatic session preference. */
  sessionLocale?: unknown;
  /** BCP 47 candidates in descending HTTP quality order; q=0 removed upstream. */
  browserLanguages?: readonly string[];
}
export function resolveUiLocale(input: ResolveInput): LocaleResolution {
  if (isUiLocale(input.deviceLocale))
    return {locale: input.deviceLocale, source: 'device', locked: true};
  if (isUiLocale(input.accountLocale))
    return {locale: input.accountLocale, source: 'account', locked: true};
  if (isUiLocale(input.sessionLocale))
    return {locale: input.sessionLocale, source: 'session', locked: false};
  for (const language of (input.browserLanguages ?? []).slice(0, 32)) {
    const locale = matchSupportedLocale(language);
    if (locale) return {locale, source: 'browser', locked: false};
  }
  return {locale: DEFAULT_UI_LOCALE, source: 'default', locked: false};
}

export interface BusyState {
  recording: boolean;
  recordingUnsaved: boolean;
  uploading: boolean;
  composingText: boolean;
  unsavedForm: boolean;
  paymentInProgress: boolean;
}
export const IDLE: BusyState = {
  recording: false, recordingUnsaved: false, uploading: false,
  composingText: false, unsavedForm: false, paymentInProgress: false
};
export function isBusy(busy: BusyState): boolean {
  // Fail closed for missing fields in untyped JavaScript callers.
  return Object.keys(IDLE).some((key) => busy[key as keyof BusyState] !== false);
}
export interface AutoState {
  locale: UiLocale;
  revision: number;
  candidate: UiLocale | null;
  count: number;
  lastEvidenceAt: number | null;
  /** A bounded replay cache, scoped to this viewer's UI session. */
  seenIds: string[];
  pending: UiLocale | null;
  /** At most one inferred switch per UI session. Explicit Auto starts a new one. */
  autoApplied: boolean;
}
export function newAutoState(locale: UiLocale, revision = 0): AutoState {
  if (!isUiLocale(locale) || !Number.isInteger(revision) || revision < 0)
    throw new Error('Invalid initial locale state');
  return {locale, revision, candidate: null, count: 0, lastEvidenceAt: null,
    seenIds: [], pending: null, autoApplied: false};
}
export type SignalOrigin = 'direct-ui-text' | 'ui-voice-command' |
  'interview' | 'transcript' | 'import' | 'external' | 'generated';
export interface LanguageObservation {
  id: string;
  languageTag: string;
  quality: 'strong' | 'uncertain';
  origin: SignalOrigin;
  actor: 'current-viewer' | 'other' | 'unknown';
  final: boolean;
  mixed: boolean;
  evidenceUnits: number;
  observedAt: number;
  revision: number;
}
export interface AutoContext {
  now: number;
  locked: boolean;
  /** Turn on only for explicitly identified current-viewer UI input surfaces. */
  inputDetectionEnabled: boolean;
  busy: BusyState;
}
export type DecisionKind = 'ignore' | 'observe' | 'defer' | 'apply';
export interface AutoDecision {
  kind: DecisionKind;
  reason: string;
  state: AutoState;
  target?: UiLocale;
}
const WINDOW_MS = 5 * 60 * 1000;
function decision(kind: DecisionKind, reason: string, state: AutoState,
                  target?: UiLocale): AutoDecision {
  return {kind, reason, state, ...(target ? {target} : {})};
}
function resetCandidate(state: AutoState): AutoState {
  return {...state, candidate: null, count: 0, lastEvidenceAt: null, pending: null};
}
export function observeLanguage(state: AutoState, event: LanguageObservation,
                                context: AutoContext): AutoDecision {
  if (context.locked) return decision('ignore', 'explicit-preference', resetCandidate(state));
  if (!context.inputDetectionEnabled) return decision('ignore', 'input-detection-disabled', resetCandidate(state));
  if (state.autoApplied) return decision('ignore', 'session-switch-limit', state);
  if (event.revision !== state.revision) return decision('ignore', 'stale-revision', state);
  if (!event.id || event.id.length > 128 || state.seenIds.includes(event.id))
    return decision('ignore', 'invalid-or-duplicate-event', state);
  if (!Number.isFinite(context.now) || !Number.isFinite(event.observedAt) ||
      event.observedAt > context.now || context.now - event.observedAt > WINDOW_MS ||
      (state.lastEvidenceAt !== null && event.observedAt < state.lastEvidenceAt))
    return decision('ignore', 'stale-or-invalid-time', state);
  if (event.actor !== 'current-viewer' ||
      !['direct-ui-text', 'ui-voice-command'].includes(event.origin) || !event.final)
    return decision('ignore', 'ineligible-origin', state);
  const seen = {...state, seenIds: [...state.seenIds, event.id].slice(-32)};
  const target = matchSupportedLocale(event.languageTag);
  if (!target || event.quality !== 'strong' || event.mixed ||
      !Number.isFinite(event.evidenceUnits) ||
      event.evidenceUnits < (target === 'zh-CN' ? 20 : 60))
    return decision('ignore', 'insufficient-language-evidence', resetCandidate(seen));
  if (target === state.locale)
    return decision('observe', 'matches-current-locale', resetCandidate(seen));
  const continuing = state.candidate === target && state.lastEvidenceAt !== null &&
    event.observedAt - state.lastEvidenceAt <= WINDOW_MS;
  const next = {...seen, candidate: target,
    count: continuing ? state.count + 1 : 1,
    lastEvidenceAt: event.observedAt, pending: null};
  if (next.count < 2) return decision('observe', 'waiting-for-second-signal', next);
  if (isBusy(context.busy))
    return decision('defer', 'busy', {...next, pending: target}, target);
  // This is a proposal. Persist successfully and then call commitAutomaticSwitch.
  return decision('apply', 'two-consistent-signals', {...next, pending: target}, target);
}
export function flushPending(state: AutoState, context: AutoContext): AutoDecision {
  if (context.locked || !context.inputDetectionEnabled)
    return decision('ignore', 'preference-changed', resetCandidate(state));
  if (!state.pending || state.autoApplied) return decision('ignore', 'nothing-pending', state);
  if (!Number.isFinite(context.now) || state.lastEvidenceAt === null ||
      context.now < state.lastEvidenceAt || context.now - state.lastEvidenceAt > WINDOW_MS)
    return decision('ignore', 'pending-expired', resetCandidate(state));
  if (isBusy(context.busy)) return decision('defer', 'busy', state, state.pending);
  return decision('apply', 'safe-boundary', state, state.pending);
}
/** Call only after the preference action succeeds; use revision/CAS in the host. */
export function commitAutomaticSwitch(state: AutoState, target: UiLocale,
                                      expectedRevision: number): AutoState {
  if (!isUiLocale(target) || state.revision !== expectedRevision ||
      state.pending !== target || state.autoApplied)
    throw new Error('Stale or invalid automatic locale commit');
  return {...resetCandidate(state), locale: target, revision: state.revision + 1,
    autoApplied: true};
}
/** Manual changes also wait for a safe boundary; the host persists fixed prefs. */
export function manualSwitchPlan(target: unknown, busy: BusyState): {
  kind: 'invalid' | 'defer' | 'apply'; target?: UiLocale
} {
  if (!isUiLocale(target)) return {kind: 'invalid'};
  return {kind: isBusy(busy) ? 'defer' : 'apply', target};
}
