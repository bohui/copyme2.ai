/** Optional local input-language adapter; not used on memoir/interview content.
 * Inject francAll from the installed 'franc' package as the ranker. Scores are
 * relative distances, NOT probabilities. Defaults are conservative heuristics,
 * not empirically calibrated accuracy guarantees. Browser detection works
 * independently of this optional module.
 */
export type Ranker = (text: string, options: {minLength: number}) => [string, number][];
export interface TextSignal {
  languageTag: string | null;
  quality: 'strong' | 'uncertain';
  evidenceUnits: number;
  mixed: boolean;
  reason: string;
}
const SIMPLIFIED_MARKERS = /[这说语忆录请为与过时学国会让们来还见写应个]/gu;
const TRADITIONAL_MARKERS = /[這說語憶錄請為與過時學國會讓們來還見寫應個]/gu;
const count = (text: string, pattern: RegExp): number => (text.match(pattern) ?? []).length;
export function detectDirectUiText(text: unknown, rank: Ranker): TextSignal {
  const unsure = (reason: string, evidenceUnits = 0, mixed = false): TextSignal =>
    ({languageTag: null, quality: 'uncertain', evidenceUnits, mixed, reason});
  if (typeof text !== 'string' || text.length > 4000) return unsure('invalid-size');
  // Do not try to infer personal preferences from pasted code, links or quotes.
  // Surface provenance is additionally enforced by the application and reducer.
  if (/```|https?:\/\/|^\s*>|[“”「」『』]/mu.test(text)) return unsure('quoted-or-nonconversation');
  const clean = text.trim();
  const letters = count(clean, /\p{Letter}/gu);
  if (letters < 20) return unsure('too-short', letters);
  const han = count(clean, /\p{Script=Han}/gu);
  const latin = count(clean, /\p{Script=Latin}/gu);
  const mixed = han > 0 && latin > 0 && Math.min(han, latin) / letters > 0.15;
  if (mixed) return unsure('mixed-language', letters, true);
  if (/[\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}]/u.test(clean))
    return unsure('unsupported-script', letters);
  let rankings: [string, number][];
  try {rankings = rank(clean, {minLength: 20});}
  catch {return unsure('detector-failed', letters);}
  const first = rankings[0];
  if (!first || !Number.isFinite(first[1])) return unsure('no-result', letters);
  if (first[0] === 'eng') {
    const second = rankings[1];
    // Reject ambiguous scores instead of treating top score=1 as certainty.
    if (letters < 60 || latin / letters < 0.95 || !second ||
        !Number.isFinite(second[1]) || first[1] - second[1] < 0.10)
      return unsure('ambiguous-english', letters);
    return {languageTag: 'en', quality: 'strong', evidenceUnits: letters,
      mixed: false, reason: 'local-english-candidate'};
  }
  if (first[0] === 'cmn' && han >= 20 && han / letters >= 0.85) {
    // These marker sets are a conservative gate, not a complete script detector.
    // Shared-only text and traditional/mixed markers abstain; never transliterate.
    if (count(clean, TRADITIONAL_MARKERS) > 0 || count(clean, SIMPLIFIED_MARKERS) < 2)
      return unsure('chinese-script-unresolved', letters);
    return {languageTag: 'zh-Hans', quality: 'strong', evidenceUnits: han,
      mixed: false, reason: 'local-simplified-chinese-candidate'};
  }
  return unsure('unsupported-or-uncertain-language', letters);
}
