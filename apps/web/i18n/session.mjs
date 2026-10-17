import { supportedLocales } from './preference.mjs';
const valid = p => p && supportedLocales.includes(p.locale) && ['manual','first_reply'].includes(p.source);
export const missingPreferenceRpc = error => ['PGRST202','42883'].includes(error?.code);

// Client epochs fence completions; the RPC enforces cross-client source priority
// and rejects dispatch under a different SDK principal.
export function createPreferenceSession() {
  let client=null, user=null, generation=0, preference=null, pending=false, hydrated=false, writeTail=Promise.resolve();
  const capture = () => ({ viewer:user?.id || null, generation });
  const current = scope => scope.viewer === (user?.id || null) && scope.generation === generation;
  return {
    get preference() { return preference; },
    get busy() { return pending; },
    get resolved() { return !client || !user?.id || hydrated; },
    get viewer() { return user?.id || null; },
    capture, current,
    beginIntent() { generation++; pending=true; },
    cancelIntent(scope) { if (current(scope)) pending=false; },
    invalidate() { generation++; preference=null; pending=false; hydrated=false; },
    setSession(nextClient,nextUser) {
      if ((user?.id || null) !== (nextUser?.id || null)) { generation++; preference=null; pending=false; hydrated=false; }
      client=nextClient; user=nextUser;
    },
    async refresh() {
      if (!client || !user?.id || pending) return null;
      const scope=capture();
      const {data,error}=await client.rpc('read_ui_locale_preference',{p_expected_viewer:scope.viewer});
      if (!current(scope) || pending) return null;
      if (error && !missingPreferenceRpc(error)) return null;
      hydrated=true;
      const value=error ? {locale:user.user_metadata?.ui_locale,source:'manual',revision:0} : data;
      if (!valid(value)) return null;
      // A second overlapping read cannot install a lower committed revision.
      if (preference && preference.revision > value.revision) return null;
      preference=value;
      return preference;
    },
    async choose(locale,source) {
      if (!supportedLocales.includes(locale) || !['manual','first_reply'].includes(source)) throw new Error('Invalid UI preference');
      generation++; pending=true;
      const scope=capture();
      const operation=writeTail.then(async () => {
        if (!current(scope)) return null;
        try {
        const result = !client || !user?.id ? {data:{locale,source,revision:0}}
          : await client.rpc('set_ui_locale_preference',{p_locale:locale,p_source:source,p_expected_viewer:scope.viewer});
        if (!current(scope)) return null;
        // Fence reads begun while the write was in flight, including Auth events.
        if (result.error || !valid(result.data)) throw new Error('UI preference could not be saved');
        generation++; pending=false; hydrated=true;
        preference=result.data;
        return preference;
      } catch (error) {
        if (!current(scope)) return null;
        generation++; pending=false;
        throw error;
        }
      });
      writeTail=operation.catch(() => {});
      return operation;
    },
  };
}


// Only a committed, original first-reply detection can repair a missed account
// write. An explicit/legacy conversation preference or a browser fallback is not
// a new inference signal.
export function firstReplyUiCandidate(profile) {
  const record=profile?.conversation_language;
  return record?.version===1 && record.initialized===true && record.source==='first_reply'
    && supportedLocales.includes(record.first_reply_locale) ? record.first_reply_locale : null;
}
