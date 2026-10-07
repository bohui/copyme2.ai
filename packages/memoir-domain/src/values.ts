import { LIFE_STAGES, type LifeStage, type Locale } from "@memoir/contracts";
export { LIFE_STAGES };
export function normalizeLocale(
  value: unknown,
  fallback: Locale = "en-AU",
): Locale {
  const locale = String(value ?? "")
    .replace(/_/g, "-")
    .toLowerCase();
  return locale === "zh" ||
    locale === "zh-cn" ||
    locale === "zh-hans" ||
    locale.startsWith("zh-hans-")
    ? "zh-CN"
    : locale === "en" || locale.startsWith("en-")
      ? "en-AU"
      : fallback;
}
export function normalizeLifeStage(value: unknown): LifeStage | "unplaced" {
  return LIFE_STAGES.includes(value as LifeStage)
    ? (value as LifeStage)
    : "unplaced";
}
export function compareLifeStages(left: unknown, right: unknown): number {
  const a = LIFE_STAGES.indexOf(left as LifeStage),
    b = LIFE_STAGES.indexOf(right as LifeStage);
  return (a < 0 ? LIFE_STAGES.length : a) - (b < 0 ? LIFE_STAGES.length : b);
}
export function normalizeDecimalSequence(value: string | number): string {
  if (typeof value === "number" && (!Number.isSafeInteger(value) || value < 0))
    throw new Error("Sequence must be a safe integer or exact decimal string");
  const string = String(value);
  if (!/^\d+$/.test(string)) throw new Error("Invalid decimal sequence");
  return string.replace(/^0+(?=\d)/, "");
}
export function compareDecimalSequences(
  left: string | number,
  right: string | number,
): -1 | 0 | 1 {
  const a = normalizeDecimalSequence(left),
    b = normalizeDecimalSequence(right);
  return a.length < b.length
    ? -1
    : a.length > b.length
      ? 1
      : a < b
        ? -1
        : a > b
          ? 1
          : 0;
}
const EXACT_DATE_RE = /^(\d{4})(?:[-/](\d{1,2})(?:[-/](\d{1,2}))?)?$/;
const EXACT_DATETIME_RE =
  /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$/;
function validDate(parts: number[]): Date | null {
  const date = new Date(
    Date.UTC(
      parts[0]!,
      parts[1]! - 1,
      parts[2]!,
      parts[3] ?? 0,
      parts[4] ?? 0,
      parts[5] ?? 0,
    ),
  );
  return Number.isNaN(date.getTime()) ||
    date.getUTCFullYear() !== parts[0] ||
    date.getUTCMonth() !== parts[1]! - 1 ||
    date.getUTCDate() !== parts[2]
    ? null
    : date;
}
/** Characterized port of apps/web/client/memoir/dates.mjs. Human uncertainty
 * stays untouched. A display date must never become a fabricated source date. */
export function formatDateExpression(
  value: unknown,
  locale: Locale = "en-AU",
): string {
  const raw = String(value ?? "").trim();
  if (!raw) return "";
  const datetime = raw.match(EXACT_DATETIME_RE);
  if (datetime) {
    const date = validDate([
      Number(datetime[1]),
      Number(datetime[2]),
      Number(datetime[3]),
      Number(datetime[4]),
      Number(datetime[5]),
      Number(datetime[6] || 0),
    ]);
    return date
      ? new Intl.DateTimeFormat(locale, {
          dateStyle: "medium",
          timeStyle: "short",
          timeZone: "UTC",
        }).format(date)
      : raw;
  }
  const exact = raw.match(EXACT_DATE_RE);
  if (!exact) return raw;
  const year = Number(exact[1]);
  if (!exact[2]) return raw;
  const month = Number(exact[2]);
  if (!exact[3]) {
    const date = validDate([year, month, 1]);
    return date
      ? new Intl.DateTimeFormat(locale, {
          year: "numeric",
          month: "long",
          timeZone: "UTC",
        }).format(date)
      : raw;
  }
  const date = validDate([year, month, Number(exact[3])]);
  return date
    ? new Intl.DateTimeFormat(locale, {
        dateStyle: "medium",
        timeZone: "UTC",
      }).format(date)
    : raw;
}
export type DatePrecision = "unknown" | "year" | "month" | "day";
export function exactDatePrecision(expression: string): DatePrecision {
  const match = expression.trim().match(EXACT_DATE_RE);
  if (!match) return "unknown";
  if (!match[2]) return "year";
  if (!validDate([Number(match[1]), Number(match[2]), Number(match[3] ?? 1)]))
    return "unknown";
  return match[3] ? "day" : "month";
}
