export const $ = (selector) => document.querySelector(selector);

export const escapeHtml = (value = "") => String(value).replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;", "'":"&#039;"}[char]));

export const formatText = (value = "") => escapeHtml(value).replace(/\n/g, "<br>");
