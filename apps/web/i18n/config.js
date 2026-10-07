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
    .flatMap((part, index) => {
      const [rawLocale, ...parameters] = part.trim().split(";");
      // HTTP quality values are in [0, 1], with at most three decimal places.
      // Invalid or repeated values must not outrank a valid browser preference.
      if (parameters.length > 1) return [];
      const quality = parameters[0]?.trim().match(/^q\s*=\s*(0(?:\.\d{0,3})?|1(?:\.0{0,3})?)$/i);
      if (parameters.length && !quality) return [];
      const weight = quality ? Number(quality[1]) : 1;
      if (weight === 0 || rawLocale.trim() === "*") return [];
      try {
        // intl-localematcher canonicalizes its entire input list and throws if
        // any tag is malformed. Discard only that tag, preserving valid choices.
        const [locale] = Intl.getCanonicalLocales(rawLocale.trim());
        return locale ? [{ locale, weight, index }] : [];
      } catch (error) {
        if (error instanceof RangeError) return [];
        throw error;
      }
    })
    .sort((left, right) => right.weight - left.weight || left.index - right.index)
    .map(({ locale }) => locale);
}

export function resolveUiLocale({ cookieLocale, acceptLanguage, matchLocale }) {
  if (isUiLocale(cookieLocale)) return cookieLocale;
  const requested = browserLocalePreferences(acceptLanguage);
  for (const locale of requested) {
    // Best-fit distance across a whole list can let a lower-priority exact
    // match beat a preferred regional variant. Match one preference at a time
    // so HTTP quality order wins while retaining the existing regional mapping.
    // "und" distinguishes no match from a genuine match to the English pack.
    const matched = matchLocale([locale], locales, "und");
    if (isUiLocale(matched)) return matched;
  }
  return defaultLocale;
}
