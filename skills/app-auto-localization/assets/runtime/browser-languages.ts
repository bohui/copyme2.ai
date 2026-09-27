/** Optional HTTP adapter; install negotiator and its types in the target app.
 * locale-policy.ts consumes this ordered list, never a substring search for zh.
 * No request content is sent to another service.
 */
import Negotiator from 'negotiator';
export function browserLanguages(acceptLanguage: string | null): string[] {
  if (!acceptLanguage || acceptLanguage.length > 8192) return [];
  try {
    return new Negotiator({headers: {'accept-language': acceptLanguage}})
      .languages().filter((value: string) => value !== '*').slice(0, 32)
      .flatMap((value: string) => {
        try {return Intl.getCanonicalLocales(value);} catch {return [];}
      });
  } catch {return [];}
}
