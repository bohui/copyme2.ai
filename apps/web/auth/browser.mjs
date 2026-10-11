const loggedOutClients = new WeakSet();
const pendingImports = new WeakMap();
const logoutEpochs = new WeakMap();
const activeLogouts = new WeakSet();
const migrationKey = url => `sb-${new URL(url).hostname.split('.')[0]}-auth-token`;

// A successful migration or explicit logout retires localStorage permanently.
// An old tab writing that obsolete key cannot resurrect its session afterward.
export function retireLegacyBrowserSession(url, storage) {
  const key=migrationKey(url);
  storage.setItem(`${key}:cookie-migrated`, '1');
  storage.removeItem(key);
}

export function restoreLegacyBrowserSession(client, url, storage) {
  if (pendingImports.has(client)) return pendingImports.get(client);
  const operation = restoreLegacySession(client, url, storage);
  pendingImports.set(client, operation);
  operation.finally(() => {
    if (pendingImports.get(client) === operation) pendingImports.delete(client);
  }).catch(() => {});
  return operation;
}

async function restoreLegacySession(client, url, storage) {
  const epoch = logoutEpochs.get(client);
  const check = () => {
    if (activeLogouts.has(client) || epoch !== logoutEpochs.get(client)) throw new Error('Saved sign-in cancelled by logout');
  };
  check();
  const { data, error } = await client.auth.getSession();
  check();
  if (error) throw error;
  const key=migrationKey(url);
  let saved, retired;
  try { saved=storage?.getItem(key); retired=storage?.getItem(`${key}:cookie-migrated`); }
  catch { if (data.session) return data.session; throw new Error('Sign-in storage unavailable'); }
  if (data.session) {
    if (saved) {
      // Coexistence may be an interrupted import. Verify the CURRENT cookie
      // user before retiring the old key; never replace the current session.
      const verified=await client.auth.getUser();
      check();
      if (verified.error || !verified.data.user) throw new Error('Saved sign-in needs recovery');
      retireLegacyBrowserSession(url,storage);
    }
    return data.session;
  }
  if (retired || loggedOutClients.has(client)) {
    if (saved) storage.removeItem(key);
    return null;
  }
  if (!saved) return null;
  let session;
  try { session=JSON.parse(saved); } catch { throw new Error('Saved sign-in needs recovery'); }
  if (!session?.access_token || !session?.refresh_token) throw new Error('Saved sign-in needs recovery');
  const restored=await client.auth.setSession({access_token:session.access_token,refresh_token:session.refresh_token});
  if (restored.error || !restored.data.session) throw new Error('Saved sign-in needs recovery');
  check();
  const verified=await client.auth.getUser();
  check();
  if (verified.error || !verified.data.user) throw new Error('Saved sign-in needs recovery');
  retireLegacyBrowserSession(url,storage);
  return restored.data.session;
}

// Legacy cleanup must never prevent revocation of the current cookie session.
export async function signOutBrowserSession(client, url, storage) {
  loggedOutClients.add(client);
  activeLogouts.add(client);
  logoutEpochs.set(client, (logoutEpochs.get(client) || 0) + 1);
  let legacyRetired = true;
  try { retireLegacyBrowserSession(url, storage); }
  catch {
    legacyRetired = false;
    try { storage?.removeItem(migrationKey(url)); } catch { /* warn caller */ }
  }
  // Finish any SDK setSession already dispatched before final logout. Never
  // perform a detached compensating signOut after a later user action.
  try { await pendingImports.get(client); } catch { /* cancelled import */ }
  try {
    const { error } = await client.auth.signOut();
    return { error, legacyRetired };
  } finally { activeLogouts.delete(client); }
}
