export const GUEST_TRANSFER_KEY = 'memoir-guest-conversation-transfer';

export function createGuestConversationTransfer({ getAuth, getConversation, api, storage, getRedirectTo, onMerged }) {
  function pending() {
    try { return JSON.parse(storage.getItem(GUEST_TRANSFER_KEY) || 'null'); }
    catch { return null; }
  }
  function cancel() { storage.removeItem(GUEST_TRANSFER_KEY); }
  async function signIn(provider) {
    const account = getAuth();
    if (!account?.user?.is_anonymous) throw new Error('Guest session required');
    const sessionResult = await account.client.auth.getSession();
    if (sessionResult.error || !sessionResult.data?.session?.refresh_token) throw new Error('Guest session unavailable');
    const session = sessionResult.data.session;
    if (session.user?.id !== account.user.id || !session.user.is_anonymous) throw new Error('Guest session changed');
    const prior = pending();
    const bytes = crypto.getRandomValues(new Uint8Array(32));
    const token = prior?.guestId === account.user.id ? prior.token
      : Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
    // Verify redirect-safe storage before leaving the guest session.
    storage.setItem(GUEST_TRANSFER_KEY, JSON.stringify({ token, guestId: account.user.id,
      // Keep a tab-scoped recovery session until the attachment succeeds.
      // It is never sent to the transfer API and is removed on success/cancel.
      guestSession: { access_token: session.access_token, refresh_token: session.refresh_token },
    }));
    await api('/v1/user/conversation-transfer', {
      method: 'POST', body: JSON.stringify({ token, ...getConversation() }),
    });
    const { error } = await account.client.auth.signInWithOAuth({
      provider,
      options: { redirectTo: getRedirectTo(), ...(provider === 'google' ? { queryParams: { prompt: 'consent select_account' } } : {}) },
    });
    if (error) throw error;
  }
  async function complete() {
    const transfer = pending();
    const user = getAuth()?.user;
    if (!transfer || !user || user.is_anonymous) return false;
    if (transfer.guestId === user.id) { cancel(); return false; }
    const result = await api('/v1/user/conversation-transfer/attach', {
      method: 'POST', body: JSON.stringify({ token: transfer.token }),
    });
    await onMerged?.(result);
    // An uncertain response leaves the capability in place; redemption is
    // idempotent so a reload retries without duplicating the conversation.
    cancel();
    return true;
  }
  async function restoreGuest() {
    const transfer = pending();
    if (!transfer?.guestSession) throw new Error('Guest session unavailable');
    const { error } = await getAuth().client.auth.setSession(transfer.guestSession);
    if (error) throw error;
    cancel();
  }
  return { signIn, complete, pending, cancel, restoreGuest };
}
