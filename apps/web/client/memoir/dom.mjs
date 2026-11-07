export const $ = (selector) => document.querySelector(selector);

export const escapeHtml = (value = "") => String(value).replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;", "'":"&#039;"}[char]));

export const formatText = (value = "") => escapeHtml(value).replace(/\n/g, "<br>");

export function memoirParagraphs(text) {
  return text.trim().split(/\r?\n\s*\r?\n/).filter(Boolean)
    .map(paragraph => `<p class="chapter-body-block">${formatText(paragraph)}</p>`).join("");
}
