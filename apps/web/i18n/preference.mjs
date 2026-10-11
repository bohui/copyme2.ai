export const preferenceCookie = 'copyme2_ui_preference_v1';
export const supportedLocales = ['en-AU', 'zh-CN'];
export function readPreference(value, viewer = null) {
  try {
    const preference = JSON.parse(value || 'null');
    if (preference?.version !== 1 || !supportedLocales.includes(preference.locale)
      || !['manual', 'first_reply', 'profile'].includes(preference.source)
      || preference.viewer !== viewer) return null;
    return preference;
  } catch { return null; }
}
export function encodePreference(locale, source, viewer = null) {
  return JSON.stringify({ version: 1, locale, source, viewer });
}
