import { NextResponse } from 'next/server';
import { authConfig, hasSessionCookies, serverAuth } from './auth/server.mjs';

export async function proxy(request) {
  const code = request.method === 'GET' ? request.nextUrl.searchParams.get('code') : null;
  const callback = Boolean(code && code.length <= 2048);
  const destination = request.nextUrl.clone();
  destination.searchParams.delete('code');
  let response = callback ? NextResponse.redirect(destination) : NextResponse.next({ request });
  if (callback || hasSessionCookies(request.cookies)) {
    const config = await authConfig();
    if (config) {
      const client = serverAuth(config, {
        getAll: () => request.cookies.getAll(),
        setAll: (updates, headers) => {
          for (const { name, value } of updates) request.cookies.set(name, value);
          if (!callback) response = NextResponse.next({ request });
          for (const { name, value, options } of updates) response.cookies.set(name, value, options);
          for (const [name, value] of Object.entries(headers || {})) response.headers.set(name, value);
        },
      });
      // This step refreshes credentials only; it never authorizes a viewer.
      // The request-local locale reader independently verifies with getUser.
      try {
        if (callback) await client.auth.exchangeCodeForSession(code);
        else await client.auth.getSession();
      } catch { /* Safe anonymous render. */ }
    }
  }
  response.headers.set('Cache-Control', 'private, no-store');
  response.headers.set('Pragma', 'no-cache');
  response.headers.set('Expires', '0');
  return response;
}

export const config = { matcher: ['/', '/memoir/:path*', '/voice/:path*'] };
