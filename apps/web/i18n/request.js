import { match } from "@formatjs/intl-localematcher";
import { cookies, headers } from "next/headers";
import { getRequestConfig } from "next-intl/server";

import enAU from "../messages/en-AU.json";
import zhCN from "../messages/zh-CN.json";
import { defaultLocale, isUiLocale, localeCookie, locales, resolveUiLocale } from "./config";

const messages = { "en-AU": enAU, "zh-CN": zhCN };

export default getRequestConfig(async () => {
  const cookieStore = await cookies();
  const headerStore = await headers();
  const locale = resolveUiLocale({
    cookieLocale: cookieStore.get(localeCookie)?.value,
    acceptLanguage: headerStore.get("accept-language") || "",
    matchLocale: (requested, supported, fallback) => match(requested, supported, fallback),
  });

  return {
    locale: isUiLocale(locale) ? locale : defaultLocale,
    messages: messages[locale] || messages[defaultLocale],
  };
});
