import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages, getTranslations } from "next-intl/server";

import MemoirClientShell from "../components/MemoirClientShell";

export const dynamic = "force-dynamic";

export const viewport = { width: "device-width", initialScale: 1, viewportFit: "cover" };

export async function generateMetadata() {
  const t = await getTranslations("Platform");
  return {
    title: `${t("brand")} — ${t("headerNote")}`,
    description: t("description"),
  };
}

export default async function RootLayout({ children }) {
  const locale = await getLocale();
  const messages = await getMessages();

  return (
    <html lang={locale}>
      <head>
        <meta name="theme-color" content="#f6f1e8" />
        <link rel="icon" type="image/png" href="/static/copyme2_icon_light.png" />
        <link rel="apple-touch-icon" href="/static/copyme2_icon_light.png" />
        <link rel="preload" href="/static/fonts/dm-sans-latin.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
        <link rel="preload" href="/static/fonts/fraunces-latin.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
        <link rel="stylesheet" href="/static/styles.css" />
        <link rel="stylesheet" href="/static/story-game.css" />
      </head>
      <body>
        <NextIntlClientProvider locale={locale} messages={messages}>{children}</NextIntlClientProvider>

      </body>
    </html>
  );
}
