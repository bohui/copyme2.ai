import enAU from "../messages/en-AU.json" with { type: "json" };
import zhCN from "../messages/zh-CN.json" with { type: "json" };

const localeMessages = {
  "en-AU": enAU,
  "zh-CN": zhCN,
};
const MISSING_TRANSLATION = "Translation unavailable";

function documentLocale() {
  const locale = globalThis.document?.documentElement?.lang;
  return Object.hasOwn(localeMessages, locale) ? locale : null;
}

function readMessage(messages, path) {
  return path.split(".").reduce((current, key) => current?.[key], messages);
}

export function currentUiLocale() {
  return globalThis.__copyme2Intl?.locale || documentLocale() || "en-AU";
}

export function translate(path) {
  const messages = globalThis.__copyme2Intl?.messages || localeMessages[currentUiLocale()] || enAU;
  const value = readMessage(messages, path);
  if (typeof value === "string") return value;
  const fallback = readMessage(enAU, path);
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
