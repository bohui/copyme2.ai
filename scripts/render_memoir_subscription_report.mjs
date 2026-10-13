#!/usr/bin/env node
// Offline presentation of saved evidence; never calls the application or a model.
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';

function cell(value) {
  return String(value ?? 'unknown').replaceAll('|', '\\|').replace(/[\r\n]+/g, ' ');
}

function fenced(value, language = '') {
  const text = String(value);
  const width = Math.max(3, ...Array.from(text.matchAll(/`+/g), match => match[0].length + 1));
  const fence = '`'.repeat(width);
  return `${fence}${language}\n${text}\n${fence}`;
}

function draftText(draft) {
  const sections = (draft.sections ?? []).map(section => section.content).filter(text => typeof text === 'string' && text.trim());
  return sections.join('\n\n') || draft.preview?.text || 'Draft text was not retained.';
}

export function renderReport(plan, receipt) {
  if (!['memoir-subscription-evaluation-plan/1','memoir-subscription-evaluation-plan/2'].includes(plan.schema_version)
      || plan.evaluation_profile !== 'subscription_fifty'
      || !['memoir-subscription-native-receipt/1', 'memoir-supabase-evaluation-receipt/1','memoir-supabase-evaluation-receipt/2'].includes(receipt.schema_version)
      || receipt.run_id !== plan.run_id || receipt.source_revision !== plan.source_revision) {
    throw new Error('A matching fifty-round plan and evaluation receipt are required.');
  }
  const remote = ['memoir-supabase-evaluation-receipt/1','memoir-supabase-evaluation-receipt/2'].includes(receipt.schema_version);
  const perCase = receipt.schema_version === 'memoir-supabase-evaluation-receipt/2';
  if (perCase && plan.schema_version !== 'memoir-subscription-evaluation-plan/2') throw new Error('Per-case receipt requires its per-case plan.');
  if (remote && plan.storage_backend !== 'remote_supabase') throw new Error('Remote receipt requires a Supabase plan.');
  const evaluation = receipt.evaluation ?? receipt.evaluation_progress ?? {};
  const rows = evaluation.cases ?? [];
  if (new Set(rows.map(item => item.case_id)).size !== rows.length) throw new Error('Duplicate case evidence.');
  const savedCases = new Map(rows.map(item => [item.case_id, item]));
  const accounting = receipt.request_accounting ?? evaluation.request_accounting ?? {};
  const lines = [
    '# Memoir live evaluation report', '',
    `Run: ${cell(plan.run_id)}  `,
    `Source commit: ${cell(plan.source_revision)}  `,
    `Source mode: ${plan.local_checkout_source ? 'local checkout' : 'reviewed main'}  `,
    ...(plan.local_checkout_source ? [
      `Branch: ${cell(plan.local_checkout_source.branch)}; local changes: ${cell(plan.local_checkout_source.dirty)}  `,
      `Checkout fingerprint: ${cell(plan.local_checkout_source.snapshot_sha256)}  `,
      `Checkout unchanged through ${remote ? 'execution' : 'cleanup'}: ${cell(receipt.local_checkout_unchanged)}  `,
      'Historical reviewed-source audit: not run (development evaluation).  ',
    ] : []),
    `Run status: **${cell(receipt.status)}**  `,
    `Evaluation status: ${cell(evaluation.status)}  `,
    `Stop reason: ${cell(receipt.stop_reason ?? evaluation.stop_reason ?? accounting.stop_reason)}  `,
    ...(receipt.source_validation_error ? [`Source validation error: ${cell(receipt.source_validation_error)}  `] : []),
    ...(receipt.source_changes?.length ? [
      `Local source fixes recorded between attempts: ${receipt.source_changes.length}. Original turn identities and budget contract retained.  `,
      ...receipt.source_changes.map(change => `Source fix after ${cell(change.backend_turn_submissions)} original submissions: ${cell(change.previous?.snapshot_sha256)} → ${cell(change.current?.snapshot_sha256)}.  `),
    ] : []),
    ...(receipt.elapsed_time_extensions?.length ? receipt.elapsed_time_extensions.map(extension =>
      `Explicit elapsed-time extension: ${cell(extension.seconds)} seconds from the original clock origin, recorded after ${cell(extension.backend_turn_submissions)} original submissions. Original request, settle and poll limits retained.  `) : []),
    `Failure stage: ${cell(evaluation.failure_stage)}  `,
    ...(remote ? [
      'Storage: remote Supabase; projects retained.  ',
      ...(perCase ? ['UI accounts: fixed case-to-account mapping shown below.  '] : [`UI account: ${cell(plan.user_email)}  `]),
      `Backend/Auth/readback HTTP requests reserved: ${cell(accounting.backend_http_requests_reserved)}  `,
      `Original turn submission attempts: ${cell(receipt.backend_turn_submissions)}  `,
      `Accepted turn response retry requests: ${receipt.backend_recovery_submissions ?? 0}  `,
      `Family features available: ${perCase ? (Object.entries(receipt.preflight ?? {}).map(([id,value]) => `${cell(id)}: ${cell(value.family_features_enabled)}`).join('; ') || 'unknown') : cell(receipt.preflight?.family_features_enabled)}  `,
    ] : [
      `Client HTTP requests reserved: ${cell(accounting.client_requests_reserved)}  `,
      `Unresolved requests: ${cell(accounting.unresolved_requests)}  `,
      `Native cleanup complete: ${cell(receipt.native?.cleanup_complete)}  `,
    ]),
    `Semantic acceptance: ${cell(receipt.semantic_acceptance ?? evaluation.semantic_acceptance)}`, '',
    'Completion records execution and saved readbacks. Model quality still requires human review. '
      + 'Provider request, token and spend totals are not verified by this launcher.', '',
    ...(remote ? [
      'Sign in as the owning account for that case and open its URL below. Run the frontend separately against this backend. '
        + '`make db-truncate RESET_CONFIRM=1` removes these projects and Auth accounts.', '',
      ...(receipt.ui_login_file === 'ui-login.html' ? ['Private, expiring, one-time [UI sign-in link](ui-login.html). '
        + 'Generate a new link with `make memoir-live-fifty-login` when needed.', ''] : []),
      'Saved evidence: [plan.json](plan.json), [receipt.json](receipt.json).', '',
    ] : [
      'Project IDs identify disposable test projects. They cannot be reopened in the normal app after database cleanup.', '',
      'Saved evidence: [plan.json](plan.json), [receipt.json](receipt.json), [request journal](journal/).', '',
    ]),
    '## Cases', '',
    ...(perCase ? ['| Case | Account | Owner | Locale | Status | Completed rounds | Ready checkpoints | Project ID |','| --- | --- | --- | --- | --- | --- | --- | --- |'] : ['| Case | Locale | Status | Completed rounds | Ready checkpoints | Project ID |','| --- | --- | --- | --- | --- | --- |']),
  ];
  for (const id of plan.case_ids) {
    const item = savedCases.get(id) ?? { status: 'not_recorded' };
    const binding = plan.cases[id];
    if (item.project_id !== undefined && item.project_id !== binding.project_id) {
      throw new Error('Saved case project does not match the plan.');
    }
    if (perCase && item.owner_id !== undefined && ['owner_id','conversation_id','user_email'].some(key => item[key] !== binding[key])) throw new Error('Saved case account identity does not match its plan.');
    const completed = (item.rounds ?? []).filter(round => round.status === 'completed').length;
    const ready = (item.checkpoints ?? []).filter(checkpoint => checkpoint.draft?.status === 'ready').length;
    lines.push(`| ${cell(id)} | ${perCase ? `${cell(binding.user_email)} | ${cell(binding.owner_id)} | ` : ''}${cell(binding.language)} | ${cell(item.status)} | ${completed}/${plan.rounds_per_case} | ${ready}/${plan.checkpoints.length} | ${cell(binding.project_id)} |`);
  }
  for (const id of plan.case_ids) {
    const item = savedCases.get(id) ?? {};
    const rounds = item.rounds ?? [];
    lines.push('', `## ${cell(id)}`, '');
    if (remote) {
      const url = plan.cases[id].ui_url;
      if (url == null && perCase) lines.push('Canonical account/project binding is unavailable.', '');
      else {
        if (typeof url !== 'string' || !/^https?:\/\/[^\s<>]+$/.test(url)) throw new Error('A valid UI URL is required.');
        lines.push(`[Open project in Memoir](<${url}>)`, '', `Owning account: ${cell(plan.cases[id].user_email ?? plan.user_email)}.`,
          `Authenticated UI recovery verified: ${cell(item.ui_recovery_verified)}.`,
          ...(perCase ? [`Current canonical evidence validated: ${cell(item.evidence_validated)}.`,
            `Current draft snapshot: ${cell(item.current_checkpoint?.draft?.snapshot_id)}; state: ${cell(item.current_checkpoint?.draft?.snapshot_state)}; approval required: ${cell(item.current_checkpoint?.draft?.approval_required)}.`] : []), '');
      }
      if (perCase && item.ui_login_file) {
        const prefix = `private-logins/${id}/`;
        if (!item.ui_login_file.startsWith(prefix) || !/^private-logins\/[A-Za-z0-9-]+\/[a-f0-9-]{36}\/ui-login\.html$/.test(item.ui_login_file)) throw new Error('Private login file crosses a case boundary.');
        lines.push(`Private expiring [sign-in link for this account](${item.ui_login_file}).`, '');
      }
    }
    lines.push('### Round results', '',
      '| Round | Status | Background settled | Accepted source |', '| --- | --- | --- | --- | --- |');
    for (const round of rounds) {
      lines.push(`| ${cell(round.round)} | ${cell(round.status)} | ${cell(round.background_settled)} | ${cell(round.accepted_source_id)} |`);
    }
    if (!rounds.length) lines.push('', 'No round evidence was retained.');
    for (const round of rounds) {
      const failures = Object.fromEntries(Object.entries(round).filter(([key, value]) => value &&
        (key === 'worker_failure' || key === 'failure_summary' || key.endsWith('_readback_diagnostic'))));
      if (Object.keys(failures).length) {
        lines.push('', `Round ${cell(round.round)} failure evidence:`, '', fenced(JSON.stringify(failures, null, 2), 'json'));
      }
    }
    if (item.skill_coverage) {
      lines.push('', '### Saved skill coverage', '', fenced(JSON.stringify(item.skill_coverage, null, 2), 'json'));
    }
    lines.push('', '### Saved checkpoint drafts', '');
    const checkpoints = item.checkpoints ?? [];
    if (!checkpoints.length) lines.push('No checkpoint draft was retained.');
    for (const checkpoint of checkpoints) {
      const draft = checkpoint.draft ?? {};
      lines.push(`#### Round ${cell(checkpoint.milestone)}`, '',
        `Status: ${cell(draft.status)}; revision: ${cell(draft.revision)}; covered round: ${cell(draft.coverage_round ?? draft.covered_round)}.`, '',
        fenced(checkpoint.readback_protocol === 'lifetime_private_draft_pages' ? (checkpoint.pages ?? []).flatMap(page => page.records ?? []).map(record => record.preview?.text ?? '').filter(Boolean).join('\n\n') : draftText(draft)), '');
    }
  }
  if (receipt.browser_readback) {
    lines.push('', '## Browser evidence', '',
      'Browser receipts and screenshot paths are recorded under `browser_readback` in [receipt.json](receipt.json).');
  }
  return `${lines.join('\n')}\n`;
}

export function writeReport(runDirectory) {
  const directory = resolve(runDirectory);
  const plan = JSON.parse(readFileSync(join(directory, 'plan.json'), 'utf8'));
  const receipt = JSON.parse(readFileSync(join(directory, 'receipt.json'), 'utf8'));
  const report = renderReport(plan, receipt);
  const output = join(directory, 'report.md');
  writeFileSync(output, report, { mode: 0o600 });
  return output;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  if (process.argv.length !== 4 || process.argv[2] !== '--run-dir') {
    console.error('Usage: node scripts/render_memoir_subscription_report.mjs --run-dir /absolute/run-directory');
    process.exitCode = 2;
  } else {
    try {
      console.log(`Report: ${writeReport(process.argv[3])}`);
    } catch (error) {
      console.error(`Could not render the saved report: ${error.code ?? error.message}`);
      process.exitCode = 1;
    }
  }
}
