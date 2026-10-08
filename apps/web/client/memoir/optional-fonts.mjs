export const MEMOIR_FONT_STYLESHEET = 'https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Fraunces:opsz,wght@9..144,500;9..144,600&display=swap';

// Insert optional typography after client startup. A parser-created remote
// stylesheet can hold Next's bootstrap scripts while its response is pending.
export function ensureMemoirFonts(document = globalThis.document) {
  if (!document?.head) return null;
  try {
    const existing = document.querySelector('link[data-memoir-fonts]');
    if (existing) return existing;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = MEMOIR_FONT_STYLESHEET;
    link.dataset.memoirFonts = 'true';
    document.head.append(link);
    return link;
  } catch {
    // Optional typography cannot replace a working conversation with an error.
    return null;
  }
}
