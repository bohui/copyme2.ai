// Public response snapshot only. Private query hypotheses never reach the UI.
const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function historicalContext(value) {
  if (!value || typeof value !== 'object' || !/^news-[a-f0-9]{24}$/.test(value.id)) return null;
  try {
    const url = new URL(value.source_url);
    if (!['http:','https:'].includes(url.protocol) || url.username || url.password) return null;
  } catch { return null; }
  if (!Number.isInteger(value.event_start) || !Number.isInteger(value.event_end) || value.event_start > value.event_end) return null;
  const fields = ['id','title','summary','event_start','event_end','precision','place','source_url','source_title','publisher','publication_date'];
  return Object.fromEntries(fields.filter(key => value[key] !== undefined).map(key => [key,value[key]]));
}
export function historicalContextMarkup(value, locale = 'en-AU') {
  const clue = historicalContext(value);
  if (!clue) return '';
  const zh = locale === 'zh-CN';
  const year = clue.event_start === clue.event_end ? clue.event_start : `${clue.event_start}–${clue.event_end}`;
  return `<aside class="historical-context" aria-label="${zh ? '公开历史背景' : 'Public historical context'}">
    <small>${zh ? '公开历史背景，可跳过' : 'Public historical context · optional'}</small>
    <p><strong>${escape(clue.title)}</strong> · ${escape(year)}</p>
    <p>${escape(clue.summary)}</p>
    <a href="${escape(clue.source_url)}" target="_blank" rel="noopener noreferrer">${escape(clue.source_title)}</a>
    <span> · ${escape(clue.publisher)}</span>
    <div><button type="button" class="button button-secondary button-small" data-news-reject="${escape(clue.id)}">${zh ? '跳过这条线索' : 'Skip this clue'}</button>
    <button type="button" class="button button-secondary button-small" data-news-disable>${zh ? '关闭历史线索' : 'Turn off historical clues'}</button></div>
  </aside>`;
}

export function bindHistoricalControls(root, {scope, current, api, notify, locale}) {
  root.querySelectorAll('[data-news-reject], [data-news-disable], [data-news-enable]').forEach(button => {
    button.addEventListener('click', async () => {
      const owner = scope();
      if (!owner.projectId) return;
      button.disabled = true;
      try {
        await api(`/v1/agent/projects/${encodeURIComponent(owner.projectId)}/historical-news`, {
          method:'PUT', body:JSON.stringify({enabled:button.dataset.newsReject ? null : !button.hasAttribute('data-news-disable'),
            reject_id:button.dataset.newsReject || null}),
        });
        if (!current(owner)) return;
        notify(locale() === 'zh-CN' ? '历史线索设置已保存' : 'Historical clue preference saved');
      } catch (error) { if (current(owner)) notify(error.message); }
      finally { if (current(owner)) button.disabled = false; }
    });
  });
}
