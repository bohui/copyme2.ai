import { missingPreferenceRpc } from "../i18n/session.mjs";
import { createServerClient } from '@supabase/ssr';

// Deployment-owned configuration only; never derive an auth destination from
// Host, query parameters, or a cookie. No service-role credential is used.
export async function authConfig() {
  if (process.env.SUPABASE_URL && process.env.SUPABASE_PUBLISHABLE_KEY) {
    return { url: process.env.SUPABASE_URL, key: process.env.SUPABASE_PUBLISHABLE_KEY };
  }
  try {
    const origin = process.env.MEMORY_SPARK_API_ORIGIN || 'http://127.0.0.1:8000';
    const response = await fetch(`${origin}/api/v1/memoir/agent/config`, {
      cache: 'no-store', signal: AbortSignal.timeout(3000),
    });
    if (!response.ok) return null;
    const config = await response.json();
    return config.supabase_url && config.supabase_publishable_key
      ? { url: config.supabase_url, key: config.supabase_publishable_key } : null;
  } catch { return null; }
}

export function hasSessionCookies(cookieStore) {
  return cookieStore.getAll().some(({name}) => /^sb-.+-auth-token(?:\.\d+)?$/.test(name));
}

export function serverAuth(config, cookies) {
  return createServerClient(config.url, config.key, {
    cookieOptions: { path: '/', sameSite: 'lax', secure: process.env.NODE_ENV === 'production' || new URL(config.url).protocol === 'https:' },
    cookies,
    global: { fetch: (url, options = {}) => fetch(url, {
      ...options, cache: 'no-store', signal: AbortSignal.timeout(5000),
    }) },
  });
}

export async function verifiedLocaleAccount(cookieStore) {
  if (!hasSessionCookies(cookieStore)) return { viewer: null, preference: null };
  const config = await authConfig();
  if (!config) return { viewer: null, preference: null };
  const client = serverAuth(config, {
    getAll: () => cookieStore.getAll(),
    // Refresh cookie writes belong to the proxy before the layout streams.
    setAll: () => {},
  });
  try {
    const { data, error } = await client.auth.getUser();
    if (error || !data.user) return { viewer: null, preference: null };
    const { data: preference, error: preferenceError } = await client.rpc('read_ui_locale_preference', {p_expected_viewer:data.user.id});
    // A missing migration/outage is not a persisted success. The existing
    // verified account metadata is the conservative legacy read fallback.
    return { viewer: data.user.id, preference: preferenceError
      ? (missingPreferenceRpc(preferenceError) ? { locale: data.user.user_metadata?.ui_locale, source: 'manual', revision: 0 } : null)
      : preference };
  } catch { return { viewer: null, preference: null }; }
}
