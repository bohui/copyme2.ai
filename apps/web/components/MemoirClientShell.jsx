"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useLocale, useMessages, useTranslations } from "next-intl";

import enAU from "../messages/en-AU.json";
import zhCN from "../messages/zh-CN.json";
import { localeCookie, locales } from "../i18n/config";
import LanguageSwitcher from "./LanguageSwitcher";

const messageCatalogues = { "en-AU": enAU, "zh-CN": zhCN };

export default function MemoirClientShell() {
  const serverLocale = useLocale();
  const serverMessages = useMessages();
  const t = useTranslations("Common");
  const [languageTarget, setLanguageTarget] = useState(null);
  const [activeLocale, setActiveLocale] = useState(serverLocale);
  const [activeMessages, setActiveMessages] = useState(serverMessages);

  useEffect(() => {
    const app = document.querySelector("#app");
    if (!app) return undefined;

    const syncLanguageTarget = () => {
      setLanguageTarget(app.querySelector("[data-language-switcher-slot]"));
    };

    syncLanguageTarget();
    const observer = new MutationObserver(syncLanguageTarget);
    observer.observe(app, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    globalThis.__copyme2Intl = { locale: activeLocale, messages: activeMessages };
    document.documentElement.lang = activeLocale;
  }, [activeLocale, activeMessages]);

  async function changeLocale(nextLocale, { persistAccount = true } = {}) {
    if (!locales.includes(nextLocale) || !Object.prototype.hasOwnProperty.call(messageCatalogues, nextLocale)) return false;
    if (nextLocale === activeLocale) return true;
    const beforeChange = globalThis.__copyme2BeforeUiLocaleChange;
    if (beforeChange) {
      const allowed = await beforeChange(nextLocale, { persistAccount });
      if (allowed === false) return false;
    }
    const nextMessages = messageCatalogues[nextLocale];
    if (persistAccount) {
      document.cookie = `${localeCookie}=${encodeURIComponent(nextLocale)}; Path=/; Max-Age=${60 * 60 * 24 * 365}; SameSite=Lax`;
    }
    globalThis.__copyme2Intl = { locale: nextLocale, messages: nextMessages };
    document.documentElement.lang = nextLocale;
    setActiveLocale(nextLocale);
    setActiveMessages(nextMessages);
    window.dispatchEvent(new CustomEvent("copyme2:ui-locale-change", { detail: { locale: nextLocale } }));
    return true;
  }

  useEffect(() => {
    globalThis.__copyme2SetUiLocale = changeLocale;
    return () => {
      if (globalThis.__copyme2SetUiLocale === changeLocale) delete globalThis.__copyme2SetUiLocale;
    };
  }, [activeLocale]);

  useEffect(() => {
    let mounted = true;

    import("../client/memoir/client.js").catch((error) => {
      if (!mounted) return;
      const node = document.querySelector("#app");
      if (node) {
        node.innerHTML = `<div class="loading">${t("loadError")}</div>`;
      }
    });

    return () => {
      mounted = false;
    };
  }, [t]);

  const languageSwitcher = (
    <div id="locale-switcher-root">
      <LanguageSwitcher
        selectedLocale={activeLocale}
        languageLabel={activeMessages.Common?.language}
        onLocaleChange={changeLocale}
      />
    </div>
  );

  return (
    <>
      <div id="app" className="app-shell">
        <div className="loading">{t("loading")}</div>
      </div>
      {languageTarget ? createPortal(languageSwitcher, languageTarget) : null}
      <div id="toast" className="toast" role="status" aria-live="polite" />
    </>
  );
}
