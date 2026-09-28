export const locales = ["en-AU", "zh-CN"];
export const defaultLocale = "en-AU";
export const localeCookie = "copyme2_ui_locale";
// Keep cookie provenance separate from the legacy locale value so a default
// or inferred cookie is not mistaken for a deliberate device choice.
export const localeSourceCookie = "copyme2_ui_locale_source";

export const localeLabels = {
  "en-AU": "English",
  "zh-CN": "简体中文",
};

export function isUiLocale(value) {
  return typeof value === "string" && locales.includes(value);
}

function browserLocalePreferences(acceptLanguage = "") {
  return acceptLanguage
    .split(",")
    .map((part, index) => {
      const [rawLocale, ...parameters] = part.trim().split(";");
      const quality = parameters.find((parameter) => parameter.trim().startsWith("q="));
      const weight = quality ? Number(quality.trim().slice(2)) : 1;
      return { locale: rawLocale, weight: Number.isFinite(weight) ? weight : 0, index };
    })
    .filter(({ locale, weight }) => locale && locale !== "*" && weight > 0)
    .sort((left, right) => right.weight - left.weight || left.index - right.index)
    .map(({ locale }) => locale);
}

export function resolveUiLocale({ cookieLocale, acceptLanguage, matchLocale }) {
  if (isUiLocale(cookieLocale)) return cookieLocale;
  const requested = browserLocalePreferences(acceptLanguage);
  return matchLocale(requested, locales, defaultLocale);
}
