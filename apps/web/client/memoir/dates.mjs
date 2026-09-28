const EXACT_DATE_RE = /^(\d{4})(?:[-/](\d{1,2})(?:[-/](\d{1,2}))?)?$/;
const EXACT_DATETIME_RE = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$/;

function validDate(parts) {
  const date = new Date(Date.UTC(parts[0], parts[1] - 1, ...parts.slice(2)));
  return Number.isNaN(date.getTime()) || date.getUTCFullYear() !== parts[0]
    || date.getUTCMonth() !== parts[1] - 1 || date.getUTCDate() !== parts[2] ? null : date;
}

/**
 * Localise exact machine-readable dates, while leaving human uncertainty
 * expressions ("around 1976", "the late 1960s", ranges) untouched.
 */
export function formatDateExpression(value, locale = "en-AU") {
  const raw = String(value ?? "").trim();
  if (!raw) return "";

  const datetime = raw.match(EXACT_DATETIME_RE);
  if (datetime) {
    const date = validDate([
      Number(datetime[1]), Number(datetime[2]), Number(datetime[3]),
      Number(datetime[4]), Number(datetime[5]), Number(datetime[6] || 0),
    ]);
    if (!date) return raw;
    return new Intl.DateTimeFormat(locale, {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: "UTC",
    }).format(date);
  }

  const exact = raw.match(EXACT_DATE_RE);
  if (!exact) return raw;
  const year = Number(exact[1]);
  if (!exact[2]) return raw;
  const month = Number(exact[2]);
  if (!exact[3]) {
    const date = validDate([year, month, 1]);
    return date ? new Intl.DateTimeFormat(locale, { year: "numeric", month: "long", timeZone: "UTC" }).format(date) : raw;
  }
  const day = Number(exact[3]);
  const date = validDate([year, month, day]);
  return date ? new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone: "UTC" }).format(date) : raw;
}
