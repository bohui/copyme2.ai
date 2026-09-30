// Keep the guest user ID so the conversation remains attached to this user.
export function linkSocialIdentity(auth, provider, redirectTo) {
  try { sessionStorage.setItem('memoir-link-provider', provider); } catch { /* optional retry hint */ }
  return auth.linkIdentity({
    provider,
    options: {
      redirectTo,
      ...(provider === 'google' ? { queryParams: { prompt: 'consent select_account' } } : {}),
    },
  });
}
