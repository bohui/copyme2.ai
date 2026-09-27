"use client";

import { useLocale, useTranslations } from "next-intl";

import { localeLabels, locales } from "../i18n/config";

export default function LanguageSwitcher({
  selectedLocale,
  languageLabel,
  onLocaleChange,
}) {
  const contextLocale = useLocale();
  const t = useTranslations("Common");
  const locale = selectedLocale || contextLocale;
  const label = languageLabel || t("language");

  async function changeLocale(event) {
    const nextLocale = event.target.value;
    if (nextLocale === locale) return;
    const change = onLocaleChange || globalThis.__copyme2SetUiLocale;
    if (!change) {
      event.target.value = locale;
      return;
    }
    const allowed = await change(nextLocale);
    if (allowed === false) {
      event.target.value = locale;
    }
  }

  return (
    <label className="locale-switcher">
      <span>{label}</span>
      <select aria-label={label} value={locale} onChange={changeLocale}>
        {locales.map((item) => (
          <option key={item} value={item}>
            {localeLabels[item]}
          </option>
        ))}
      </select>
    </label>
  );
}
