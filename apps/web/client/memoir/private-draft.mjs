import { $, escapeHtml, formatText } from "./dom.mjs";
import { currentUiLocale, translate, translateWith } from "../i18n.js";

export function createPrivateDraft({
  applyBackgroundSkillProgress, captureProjectScope, freeRecallFinished, isCurrentProjectScope, memoirApiPath, persistChatHistory, profile,
  render, state, storyApi, updateStreamingAssistantMessage
}) {
  function currentSectionRework() {
    const rework = state.sectionRework;
    return rework && isCurrentProjectScope(rework)
      && rework.locale === (state.privateDraftLocale || state.privateDraft?.locale) ? rework : null;
  }

  function openSectionRework(partitionId) {
    const saved = state.privateDraft;
    const record = [saved?.first_record, ...(saved?.pages || []), saved?.selected_record].find(item => item?.id === partitionId);
    if (!record?.preview || record.proposed_preview || saved.updating || saved.deciding || currentSectionRework()?.busy) return;
    state.sectionRework = {...captureProjectScope(), locale:saved.locale, partitionId, snapshotId:saved.snapshot_id,
      rootDigest:saved.root_digest, requestId:crypto.randomUUID(), instruction:"", busy:false};
    render();
    $("#section-rework-instruction")?.focus();
  }

  function sectionReworkMarkup(record, saved) {
    if (!saved.snapshot_id || !record.id || !state.supabase?.accessToken) return "";
    const t = key => escapeHtml(translate(`Memoir.workspace.${key}`));
    const rework = currentSectionRework();
    if (rework?.partitionId === record.id && !rework.queued) {
      return `<form id="section-rework-form" class="section-rework-form"><label for="section-rework-instruction">${t("reworkInstruction")}</label><textarea id="section-rework-instruction" required maxlength="1000" rows="3" ${rework.busy || rework.payload ? "disabled" : ""} placeholder="${t("reworkPlaceholder")}">${escapeHtml(rework.instruction)}</textarea><div class="workspace-task-actions"><button type="submit" class="button button-secondary button-small" ${rework.busy ? "disabled" : ""}>${t(rework.busy ? "reworkSending" : rework.error ? "retrySectionRework" : "requestSectionRework")}</button><button type="button" class="text-button" data-cancel-section-rework ${rework.busy ? "disabled" : ""}>${t("cancelSectionRework")}</button></div></form>`;
    }
    return `<button type="button" class="text-button" data-rework-section="${escapeHtml(record.id)}" ${saved.updating || saved.deciding || record.proposed_preview || rework?.queued && !rework.ready ? "disabled" : ""}>${t("reworkThisSection")}</button>`;
  }

  function sectionReworkNotice() {
    const rework = currentSectionRework();
    const key = rework?.error ? "reworkError" : rework?.ready ? "reworkReady" : rework?.queued ? "reworkQueued" : null;
    return key ? `<p role="status">${escapeHtml(translate(`Memoir.workspace.${key}`))}</p>` : "";
  }

  async function submitSectionRework(event) {
    event.preventDefault();
    const rework = currentSectionRework();
    if (!rework || rework.busy || !rework.instruction.trim()) return;
    // Keep one exact request identity even if its response is lost after commit.
    rework.payload ||= {project_id:rework.projectId, request_id:rework.requestId,
      snapshot_id:rework.snapshotId, root_digest:rework.rootDigest,
      partition_id:rework.partitionId, instruction:rework.instruction.trim()};
    rework.busy = true;
    rework.error = false;
    render();
    try {
      await storyApi('/v1/story/private-draft/rework', {method:"POST", body:JSON.stringify(rework.payload)});
      if (currentSectionRework() !== rework) return;
      rework.queued = true;
    } catch (_) {
      if (currentSectionRework() === rework) rework.error = true;
    } finally {
      rework.busy = false;
      if (currentSectionRework() === rework) { render(); await refreshPrivateDraft({restart:true}); }
    }
  }

  function updateBackgroundComposerProgress(result) {
    if (!state.showThinkingSteps) return;
    if (Object.hasOwn(result,'skill_progress')) {
      if (result.skill_progress) applyBackgroundSkillProgress(result.skill_progress);
      return;
    }
    const progress = result.background_progress;
    const message = state.chat?.find(item => item.role === "assistant" && item.clientTurnId === state.backgroundDraftTurn);
    if (!message || !progress || !["pending", "running", "finished", "retry_required"].includes(progress.state)) return;
    const labels = {summarizing:"backgroundSummary", drafting:"backgroundDraft", reviewing:"backgroundReview", saving:"backgroundSave"};
    const phase = progress.state === "finished" ? "saved" : labels[progress.phase] ? progress.phase : "queued";
    const key = 'memoir-composer-state';
    const trace = message.trace ||= [];
    // Lane state is not a receipt for any preceding phase or model invocation.
    const step = {id:key, kind:"skill", skill:"memoir-composer", label:"memoir-composer", lane:"B", execution:"model", model_invoked:false,
      detail:translate(`Memoir.trace.${phase === "saved" ? "backgroundSaved" : labels[phase] || "backgroundQueued"}`),
      status:progress.state === "retry_required" ? "failed" : phase === "saved" ? "saved" : progress.state === "pending" ? "queued" : "running"};
    const index = trace.findIndex(item => item.id === key);
    if (index < 0) trace.push(step); else trace[index] = step;
    message.traceMode ||= "live";
    updateStreamingAssistantMessage(message);
    persistChatHistory();
  }

  async function applyPrivateDraftUpdate(result, scope, requestId) {
    if (!isCurrentProjectScope(scope) || requestId !== state.privateDraftRequest) return;
    const previous = state.privateDraft;
    const sameRoot = result.snapshot_id && previous?.snapshot_id === result.snapshot_id && previous.root_digest === result.root_digest;
    state.privateDraft={...result, pages: sameRoot ? previous.pages || [] : []};
    updateBackgroundComposerProgress(result);
    const rework = currentSectionRework();
    if (rework && result.snapshot_id) {
      try {
        const query = new URLSearchParams({project_id:scope.projectId, snapshot_id:result.snapshot_id, partition_id:rework.partitionId});
        const section = await storyApi(`/v1/story/private-draft/section?${query}`);
        if (!isCurrentProjectScope(scope) || requestId !== state.privateDraftRequest) return;
        state.privateDraft.selected_record = section;
        if (section.proposed_preview) rework.ready = true;
      } catch (_) { /* A stale selected section does not hide the remaining draft. */ }
    }
    if (!state.loading && (!sameRoot || previous?.updating !== result.updating || previous?.status !== result.status || previous?.error !== result.error)) {
      // A stream update can arrive before the browser dispatches the details toggle event.
      const details = globalThis.document?.querySelector?.(".saved-draft-sections");
      if (details) state.privateDraftExpanded = details.open;
      render();
    }
  }

  async function consumePrivateDraftStream(response, onUpdate, signal) {
    if (!response.body || !response.headers.get("Content-Type")?.includes("application/x-ndjson")) {
      throw new Error("Invalid draft stream");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8", {fatal:true});
    const cancel = () => { void reader.cancel().catch(() => {}); };
    signal.addEventListener("abort", cancel, {once:true});
    let buffer = "", latest = null;
    try {
      while (!signal.aborted) {
        const {value, done} = await reader.read();
        buffer += decoder.decode(value, {stream:!done});
        const lines = buffer.split("\n");
        buffer = done ? "" : lines.pop();
        if (buffer.length > 1024 * 1024) throw new Error("Draft stream frame too large");
        for (const line of lines) {
          if (!line.trim()) continue;
          if (line.length > 1024 * 1024) throw new Error("Draft stream frame too large");
          const event = JSON.parse(line);
          if (signal.aborted) return;
          if (event.type === "draft_update" && event.data && typeof event.data === "object" && !Array.isArray(event.data)) {
            latest = event.data;
            await onUpdate(latest);
          } else if (event.type === "complete" && latest && !latest.updating) return;
          else if (event.type !== "heartbeat") throw new Error("Draft stream unavailable");
        }
        if (done) throw Object.assign(new Error("Draft stream interrupted"), {retryable:true});
      }
    } finally {
      signal.removeEventListener("abort", cancel);
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }

  async function refreshPrivateDraft({restart = false} = {}) {
    const scope = captureProjectScope();
    if (!scope.projectId || !state.supabase?.accessToken) return;
    const language = state.privateDraftLocale || profile().preferred_language || currentUiLocale();
    const debug = state.showThinkingSteps || state.showDraftUpdates;
    const active = state.privateDraftStream;
    if (debug && !restart && active && !active.controller.signal.aborted &&
        isCurrentProjectScope(active.scope) && active.language === language) return active.ready;
    active?.controller.abort();
    state.privateDraftStream = null;
    const requestId = state.privateDraftRequest = (state.privateDraftRequest || 0) + 1;
    const path = `/v1/story/private-draft?project_id=${encodeURIComponent(scope.projectId)}&language=${encodeURIComponent(language)}`;
    const update = result => applyPrivateDraftUpdate(result, scope, requestId);
    const fail = () => update({...state.privateDraft, updating:false, error:"PRIVATE_DRAFT_UNAVAILABLE",
      background_progress:{state:"retry_required"}});
    if (!debug) {
      if (!freeRecallFinished()) return;
      try { await update(await storyApi(path)); } catch (_) { await fail(); }
      return;
    }
    const controller = new AbortController();
    let ready;
    const subscription = {scope, language, controller, ready:new Promise(resolve => { ready = resolve; })};
    state.privateDraftStream = subscription;
    const current = () => !controller.signal.aborted && isCurrentProjectScope(scope) && state.privateDraftStream === subscription;
    // The first snapshot is awaitable; background updates continue after the caller resumes.
    void (async () => {
      try {
        for (let attempt = 0; current(); attempt++) {
          try {
            const response = await fetch(memoirApiPath(path), {
              headers:{Accept:"application/x-ndjson", Authorization:`Bearer ${state.supabase.accessToken}`},
              signal:controller.signal,
            });
            if (!current()) return;
            if (!response.ok) throw new Error("Draft stream unavailable");
            await consumePrivateDraftStream(response, async result => {
              if (!current()) return;
              await update(result);
              ready();
            }, controller.signal);
            break;
          } catch (error) {
            if (!current()) return;
            if (!(error.retryable || error.name === "TypeError") || attempt >= 2) throw error;
            await new Promise(resolve => {
              const finish = () => { clearTimeout(timer); controller.signal.removeEventListener("abort", finish); resolve(); };
              const timer = setTimeout(finish, 1000 * 2 ** attempt);
              controller.signal.addEventListener("abort", finish, {once:true});
            });
          }
        }
      } catch (_) {
        if (current()) await fail();
      } finally {
        ready();
        if (state.privateDraftStream === subscription) state.privateDraftStream = null;
      }
    })();
    return subscription.ready;
  }

  async function retryPrivateDraft() {
    await storyApi('/v1/story/private-draft/retry',{method:'POST',body:JSON.stringify({
      project_id:state.project.id,language:state.privateDraftLocale || profile().preferred_language || currentUiLocale()})});
    await refreshPrivateDraft({restart:true});
  }

  async function selectPrivateDraftLocale(language) {
    if (!["en-AU", "zh-CN"].includes(language)) return;
    state.sectionRework = null;
    state.privateDraftLocale = language;
    state.privateDraft = null;
    await refreshPrivateDraft({restart:true});
  }

  async function decidePrivateDraftProposal(partitionId, accept) {
    const scope = captureProjectScope();
    const saved = state.privateDraft;
    const record = [saved?.first_record,...(saved?.pages || []),saved?.selected_record].find(item => item?.id === partitionId);
    if (!record?.proposal_digest || saved.deciding || saved.loading_page) return;
    state.privateDraftStream?.controller.abort();
    state.privateDraftRequest = (state.privateDraftRequest || 0) + 1;
    saved.deciding = true;
    saved.decision_error = false;
    render();
    try {
      const result = await storyApi('/v1/story/private-draft/proposal', {method: 'POST', body: JSON.stringify({
        project_id: state.project.id, snapshot_id: saved.snapshot_id, root_digest: saved.root_digest,
        partition_id: partitionId, expected_proposal_digest: record.proposal_digest, accept})});
      if (!isCurrentProjectScope(scope) || state.privateDraft !== saved) return;
      state.privateDraft = {...result, pages: []};
      if (currentSectionRework()?.partitionId === partitionId) state.sectionRework = null;
    } catch (_) {
      if (isCurrentProjectScope(scope) && state.privateDraft === saved) saved.decision_error = true;
    } finally {
      saved.deciding = false;
      if (isCurrentProjectScope(scope)) render();
    }
  }

  async function loadMorePrivateDraft() {
    const scope = captureProjectScope();
    const saved = state.privateDraft;
    if (!saved?.snapshot_id || !saved.next_cursor || saved.loading_page || saved.deciding) return;
    saved.loading_page = true;
    saved.page_error = false;
    render();
    try {
      const query = new URLSearchParams({project_id: state.project.id,
        snapshot_id: saved.snapshot_id, cursor: saved.next_cursor});
      const page = await storyApi(`/v1/story/private-draft/page?${query}`);
      if (!isCurrentProjectScope(scope) || state.privateDraft !== saved || page.snapshot_id !== saved.snapshot_id) return;
      saved.pages = [...(saved.pages || []), ...(page.records || [])];
      saved.next_cursor = page.next_cursor || null;
      saved.page_complete = page.complete === true;
    } catch (_) {
      if (isCurrentProjectScope(scope) && state.privateDraft === saved) saved.page_error = true;
    } finally {
      saved.loading_page = false;
      if (isCurrentProjectScope(scope) && state.privateDraft === saved) render();
    }
  }

  function privateDraftThinkingStep(clientTurnId) {
    const saved = state.privateDraft;
    if (!state.showThinkingSteps || !saved || !clientTurnId) return "";
    const receipts = saved.skill_progress?.project_id === state.project?.id
      ? (saved.skill_progress.items || []).filter(step => step.skill === "memoir-composer" && step.client_turn_id) : [];
    // Canonical previews belong to their frozen coverage, even while a later turn is composing.
    const receipt = saved.source_revision != null
      ? receipts.findLast(step => step.coverage_end === saved.source_revision) : receipts.at(-1);
    const turn = Object.hasOwn(saved, "skill_progress") ? receipt?.client_turn_id : state.backgroundDraftTurn;
    if (turn !== clientTurnId) return "";
    const t = key => escapeHtml(translate(`Memoir.workspace.${key}`));
    const records = [...new Map([saved.first_record, ...(saved.pages || []), saved.selected_record].filter(Boolean).map(record => [record.id, record])).values()];
    const previews = records.length ? records.filter(record => record.preview) : saved.preview ? [{preview:saved.preview}] : [];
    if (!previews.length) return "";
    const sections = previews.map(record => `<article class="agent-composer-section" data-event-id="${escapeHtml(record.event_id || "")}"><h4>${escapeHtml(record.preview.title)}</h4>${formatText(record.preview.text)}</article>`).join("");
    const pagination = saved.next_cursor ? `<p>${t('draftPagesPartial')}</p><button type="button" class="text-button" data-action="load-more-private-draft" ${saved.loading_page ? "disabled" : ""}>${t(saved.loading_page ? 'loadingSavedPage' : 'loadMoreDraft')}</button>` : "";
    return `<li class="agent-loop-step agent-loop-skill" data-step-id="memoir-composer-draft"><details class="agent-composer-draft" ${state.privateDraftThinkingExpanded ? "open" : ""}><summary><span>memoir-composer · ${t('readSavedDraft')}</span></summary><div class="agent-composer-content">${sections}${pagination}${saved.page_error ? `<p role="status">${t('savedPageChanged')}</p>` : ""}</div></details></li>`;
  }

  function privateDraftPreview({ inChapters = false } = {}) {
    if (!inChapters || !(state.showDraftUpdates || freeRecallFinished())) return "";
    const saved=state.privateDraft;
    if (!saved || !saved.preview && !saved.error && !saved.approval_required && !saved.original_withheld &&
        !saved.updating) return "";
    const t=(key,values={})=>escapeHtml(translateWith(`Memoir.workspace.${key}`,values));
    const preview=saved.preview;
    const status=[preview ? t('privateDraftSaved',{round:saved.covered_round ?? saved.coverage_round ?? saved.milestone}) : "", saved.updating ? t('privateDraftUpdating') : saved.error ? t('privateDraftBlocked') : ""].filter(Boolean).join(" ");
    const records = [...new Map([saved.first_record, ...(saved.pages || []), saved.selected_record].filter(Boolean).map(record => [record.id, record])).values()];
    const sections = records.length ? records.filter(record => record.preview).map(record => `<article class="private-draft-section" data-draft-section="${escapeHtml(record.id)}"><h3>${escapeHtml(record.preview.title)}</h3>${formatText(record.preview.text)}${sectionReworkMarkup(record, saved)}</article>`).join("") : preview ? `<h3>${escapeHtml(preview.title)}</h3>${formatText(preview.text)}` : "";
    const proposalRecords = records.length ? records.filter(section => section.proposed_preview)
      : saved.proposed_preview ? [{proposed_preview:saved.proposed_preview}] : [];
    const proposalMarkup = proposalRecords.length ? `<details><summary>${t('draftProposalReview')}</summary>${proposalRecords.map(section => `<h3>${escapeHtml(section.proposed_preview.title)}</h3>${formatText(section.proposed_preview.text)}${section.proposal_digest ? `<div><button type="button" class="text-button" data-proposal-id="${escapeHtml(section.id)}" data-proposal-accept="true" ${saved.deciding || saved.loading_page ? "disabled" : ""}>${t('acceptDraftProposal')}</button><button type="button" class="text-button" data-proposal-id="${escapeHtml(section.id)}" data-proposal-accept="false" ${saved.deciding || saved.loading_page ? "disabled" : ""}>${t('rejectDraftProposal')}</button></div>` : ""}`).join("")}</details>` : "";
    const protectedNotice = saved.approval_required || (saved.pages || []).some(section => section.proposed_preview) ? `<p role="status">${t('draftApprovalRequired')}</p>` : "";
    const withheldNotice = saved.original_withheld || (saved.pages || []).some(section => section.original_withheld) ? `<p role="status">${t('draftOriginalWithheld')}</p>` : "";
    const partial = saved.snapshot_id && saved.page_complete === false;
    const pagination = partial ? `<p role="status">${t('draftPagesPartial')}</p><button type="button" class="button button-secondary button-small" data-action="load-more-private-draft" ${saved.loading_page ? "disabled" : ""}>${t(saved.loading_page ? 'loadingSavedPage' : 'loadMoreDraft')}</button>` : "";
    const locale = saved.locale || state.privateDraftLocale || profile().preferred_language || currentUiLocale();
    const edition = saved.snapshot_id || saved.error ? `<label>${t('draftEditionLanguage')} <select data-draft-locale ${saved.deciding || saved.loading_page ? "disabled" : ""}><option value="en-AU" ${locale === "en-AU" ? "selected" : ""}>English</option><option value="zh-CN" ${locale === "zh-CN" ? "selected" : ""}>简体中文</option></select></label>` : "";
    const decisionError = saved.decision_error ? `<p role="status">${t('draftProposalChanged')}</p><button type="button" class="text-button" data-action="refresh-private-draft">${t('reloadSavedPages')}</button>` : "";
    return `<section class="private-draft-status">${edition}<p>${status}</p>${sections ? `<details class="saved-draft-sections" ${state.privateDraftExpanded || currentSectionRework() ? "open" : ""}><summary>${t('readSavedDraft')}</summary>${sections}</details>` : ""}${sectionReworkNotice()}${protectedNotice}${withheldNotice}${proposalMarkup}${decisionError}${pagination}${saved.page_error ? `<p role="status">${t('savedPageChanged')}</p><button type="button" class="text-button" data-action="refresh-private-draft">${t('reloadSavedPages')}</button>` : ""}${saved.error && !saved.updating ? `<button type="button" class="button button-secondary button-small" data-action="${saved.error === 'PRIVATE_DRAFT_UNAVAILABLE' ? 'refresh-private-draft' : 'retry-private-draft'}">${t('retryPrivateDraft')}</button>` : ""}</section>`;
  }

  return {
    currentSectionRework, decidePrivateDraftProposal, loadMorePrivateDraft, openSectionRework,
    privateDraftPreview, privateDraftThinkingStep, refreshPrivateDraft, retryPrivateDraft, selectPrivateDraftLocale, submitSectionRework
  };
}
