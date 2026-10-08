import Script from "next/script";
import { NextIntlClientProvider } from "next-intl";
import { getLocale, getMessages, getTranslations } from "next-intl/server";

import MemoirClientShell from "../components/MemoirClientShell";

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
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link rel="stylesheet" href="/static/styles.css" />
      </head>
      <body>
        <NextIntlClientProvider locale={locale} messages={messages}>{children}</NextIntlClientProvider>
        <Script
          src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"
          strategy="beforeInteractive"
        />
      </body>
    </html>
  );
}
