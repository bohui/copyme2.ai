export const AUTH_REMINDER_DELAY = 10 * 60 * 1000;

// Store visible usage, rather than a deadline that also counts closed tabs.
export function createGuestUsage(storage, key) {
  let elapsed = 0;
  try { elapsed = Math.max(0, Number(storage.getItem(key)) || 0); } catch { /* memory fallback */ }
  return {
    add(milliseconds) {
      elapsed = Math.min(AUTH_REMINDER_DELAY, elapsed + Math.max(0, milliseconds));
      try { storage.setItem(key, String(elapsed)); } catch { /* private browsing */ }
      return elapsed >= AUTH_REMINDER_DELAY;
    },
  };
}
