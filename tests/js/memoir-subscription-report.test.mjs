import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { renderReport, writeReport } from '../../scripts/render_memoir_subscription_report.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));

function fixture() {
  const ids = ['harbour', 'chengdu', 'perth', 'kunming', 'sydney'];
  const plan = {
    schema_version: 'memoir-subscription-evaluation-plan/1', evaluation_profile: 'subscription_fifty',
    run_id: 'saved-run', source_revision: 'saved-source', case_ids: ids, rounds_per_case: 50,
    checkpoints: Array.from({ length: 10 }, (_, index) => (index + 1) * 5),
    cases: Object.fromEntries(ids.map((id, index) => [id, { project_id: `project-${index}`, language: index % 2 ? 'zh-CN' : 'en-AU' }])),
  };
  const receipt = {
    schema_version: 'memoir-subscription-native-receipt/1', run_id: plan.run_id,
    source_revision: plan.source_revision, status: 'incomplete', semantic_acceptance: 'human_review_required',
    evaluation: { status: 'incomplete', stop_reason: 'checkpoint_incomplete', failure_stage: 'checkpoint_readback', cases: [
      { case_id: 'harbour', project_id: 'project-0', status: 'incomplete', rounds: [
        { round: 1, status: 'completed', background_settled: true, accepted_source_id: 'source-1' },
        { round: 2, status: 'delivered', background_settled: false, failure_summary: { reason: 'worker_timeout' },
          canonical_readback_diagnostic: { boundary: 'canonical', predicate: 'source_count' } },
      ], checkpoints: [{ milestone: 5, draft: { status: 'ready', revision: 1, covered_round: 5,
        preview: { text: 'short preview' }, sections: [{ content: '完整草稿 ``` and | evidence' }] } }] },
    ] },
  };
  return { plan, receipt };
}

test('partial report counts only completed rounds and retains all five planned cases and actual draft text', () => {
  const { plan, receipt } = fixture();
  const report = renderReport(plan, receipt);
  assert.match(report, /Run status: \*\*incomplete\*\*/);
  assert.match(report, /\| harbour \| en-AU \| incomplete \| 1\/50 \| 1\/10 \| project-0 \|/);
  assert.match(report, /\| sydney \| en-AU \| not_recorded \| 0\/50 \| 0\/10 \| project-4 \|/);
  assert.match(report, /checkpoint_readback/);
  assert.match(report, /worker_timeout/);
  assert.match(report, /source_count/);
  assert.match(report, /````\n完整草稿 ``` and \| evidence\n````/);
  assert.doesNotMatch(report, /short preview/);
  assert.match(report, /human_review_required/);
  assert.match(report, /Client HTTP requests reserved: unknown/);
  assert.match(report, /Native cleanup complete: unknown/);
});

test('interrupted native receipt uses retained progress without claiming native completion', () => {
  const { plan, receipt } = fixture();
  receipt.evaluation_progress = receipt.evaluation;
  receipt.evaluation_progress.status = 'completed';
  delete receipt.evaluation;
  const report = renderReport(plan, receipt);
  assert.match(report, /Run status: \*\*incomplete\*\*/);
  assert.match(report, /Evaluation status: completed/);
  assert.match(report, /1\/50/);
});

test('receipt before session creation preserves planned IDs and unknown accounting', () => {
  const { plan, receipt } = fixture();
  delete receipt.evaluation;
  const report = renderReport(plan, receipt);
  assert.match(report, /project-4/);
  assert.match(report, /Evaluation status: unknown/);
  assert.match(report, /Unresolved requests: unknown/);
});

test('report labels local changes and provenance without claiming the reviewed-source audit passed', () => {
  const { plan, receipt } = fixture();
  plan.local_checkout_source = { branch: 'codex/development', dirty: true, snapshot_sha256: 'b'.repeat(64) };
  receipt.local_checkout_unchanged = false;
  const report = renderReport(plan, receipt);
  assert.match(report, /Source mode: local checkout/);
  assert.match(report, /codex\/development; local changes: true/);
  assert.match(report, /Checkout unchanged through cleanup: false/);
  assert.match(report, /Historical reviewed-source audit: not run/);
});

test('report rejects mismatched run, source and project bindings', () => {
  for (const key of ['run_id', 'source_revision']) {
    const { plan, receipt } = fixture();
    receipt[key] = 'different';
    assert.throws(() => renderReport(plan, receipt), /matching fifty-round plan/);
  }
  const { plan, receipt } = fixture();
  receipt.evaluation.cases[0].project_id = 'foreign';
  assert.throws(() => renderReport(plan, receipt), /project does not match/);
});

test('offline report writes a private Markdown file and preserves raw evidence', () => {
  const directory = mkdtempSync(join(tmpdir(), 'memoir-report-'));
  try {
    const { plan, receipt } = fixture();
    const original = JSON.stringify(receipt);
    writeFileSync(join(directory, 'plan.json'), JSON.stringify(plan));
    writeFileSync(join(directory, 'receipt.json'), original);
    const output = writeReport(directory);
    assert.match(readFileSync(output, 'utf8'), /完整草稿/);
    assert.equal(statSync(output).mode & 0o777, 0o600);
    assert.equal(readFileSync(join(directory, 'receipt.json'), 'utf8'), original);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test('Make plan invokes the actual launcher with five original 50-round cases without reading provider configuration', () => {
  const directory = mkdtempSync(join(tmpdir(), 'memoir-make-plan-'));
  try {
    const binary = process.execPath;
    const digest = createHash('sha256').update(readFileSync(binary)).digest('hex');
    const runDirectory = join(directory, 'not allocated');
    const envFile = join(directory, 'must-not-be-read.env');
    writeFileSync(envFile, 'not a provider configuration', { mode: 0o000 });
    const result = spawnSync('make', ['--no-print-directory', 'memoir-live-fifty-disposable-plan',
      'EVAL_SOURCE_MODE=reviewed',
      `EVAL_SOURCE_REVISION=${'a'.repeat(40)}`, `EVAL_CODEX_BINARY=${binary}`, `EVAL_CODEX_SHA256=${digest}`,
      `EVAL_TEMPORAL_BINARY=${binary}`, `EVAL_TEMPORAL_SHA256=${digest}`,
      `EVAL_RUN_DIR=${runDirectory}`, `ENV_FILE=${envFile}`,
    ], { cwd: root, encoding: 'utf8' });
    assert.equal(result.status, 0, result.stderr || result.stdout);
    const plan = JSON.parse(result.stdout);
    assert.deepEqual(plan.case_ids, ['harbour-copper-notebook', 'chengdu-tea-ledger',
      'perth-workshop-compass', 'kunming-garden-lanterns', 'sydney-platform-letters']);
    assert.equal(plan.rounds_per_case, 50);
    assert.equal(plan.checkpoints.length, 10);
    assert.equal(plan.execution_started, false);
    assert.equal(plan.collector_timeout_seconds, 180);
    assert.throws(() => statSync(runDirectory), { code: 'ENOENT' });
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

const caseIds = ['harbour-copper-notebook', 'chengdu-tea-ledger', 'perth-workshop-compass',
  'kunming-garden-lanterns', 'sydney-platform-letters'];

function remoteFixture() {
  const { plan, receipt } = fixture();
  plan.storage_backend = 'remote_supabase';
  plan.user_email = 'test@test.com';
  for (const binding of Object.values(plan.cases)) binding.ui_url = `http://localhost:3010/memoir/interview/${binding.project_id}`;
  receipt.schema_version = 'memoir-supabase-evaluation-receipt/1';
  receipt.ui_login_file = 'ui-login.html';
  receipt.request_accounting = { backend_http_requests_reserved: 234 };
  receipt.backend_turn_submissions = 50;
  return { plan, receipt };
}

test('remote report links retained UI projects and private login without claiming native cleanup or provider accounting', () => {
  const { plan, receipt } = remoteFixture();
  const report = renderReport(plan, receipt);
  assert.match(report, /Storage: remote Supabase; projects retained/);
  assert.match(report, /UI account: test@test.com/);
  assert.match(report, /HTTP requests reserved: 234/);
  assert.match(report, /Original turn submission attempts: 50/);
  assert.match(report, /UI sign-in link\]\(ui-login.html\)/);
  assert.match(report, /http:\/\/localhost:3010\/memoir\/interview\/project-0/);
  assert.match(report, /removes these projects and Auth accounts/);
  assert.doesNotMatch(report, /disposable test projects|Native cleanup complete|request journal/);
});

for (const selectedCase of ['', ...caseIds]) {
  test(`remote Make plan for ${selectedCase || 'all cases'} requires no credentials or native executable pins`, () => {
    const directory = mkdtempSync(join(tmpdir(), 'memoir-remote-plan-'));
    try {
      const result = spawnSync('make', ['--no-print-directory', 'memoir-live-fifty-plan',
        `EVAL_CASE_ID=${selectedCase}`, 'EVAL_SOURCE_REVISION=', 'EVAL_USER_EMAIL=test@test.com',
        `ENV_FILE=${join(directory, 'absent.env')}`, `EVAL_RUN_DIR=${join(directory, 'unallocated')}`],
      { cwd: root, encoding: 'utf8' });
      assert.equal(result.status, 0, result.stderr || result.stdout);
      const plan = JSON.parse(result.stdout);
      assert.equal(plan.storage_backend, 'remote_supabase');
      assert.equal(plan.user_email, 'test@test.com');
      assert.equal(plan.source_revision, spawnSync('git', ['rev-parse', 'HEAD'], {cwd: root, encoding: 'utf8'}).stdout.trim());
      assert.deepEqual(plan.case_ids, selectedCase ? [selectedCase] : caseIds);
      assert.equal(plan.rounds_per_case, 50);
      assert.equal(plan.checkpoints.length, 10);
      assert.equal(plan.browser_started, false);
      assert.equal(plan.local_postgres_started, false);
      assert.equal(plan.actual_upstream_provider_requests, null);
      assert.equal(plan.max_backend_requests, selectedCase ? 20000 : 100000);
      assert.equal(plan.codex_binary, undefined);
      assert.throws(() => statSync(join(directory, 'unallocated')), { code: 'ENOENT' });
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });
}

for (const [exitCode, startBackend] of [[0, 1], [3, 0]]) {
  test(`remote Make live renders retained receipt and preserves exit ${exitCode}`, () => {
    const directory = mkdtempSync(join(tmpdir(), 'memoir-remote-live-'));
    try {
      const { plan, receipt } = remoteFixture();
      const bin = join(directory, 'bin');
      mkdirSync(bin);
      writeFileSync(join(directory, 'plan.json'), JSON.stringify(plan));
      writeFileSync(join(directory, 'receipt.json'), JSON.stringify(receipt));
      writeFileSync(join(bin, 'python3'), `#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');
const args = process.argv.slice(2);
const fixture = process.env.MEMOIR_REPORT_TEST_FIXTURE;
const directory = args[args.indexOf('--run-dir') + 1];
fs.writeFileSync(path.join(fixture, 'args.json'), JSON.stringify(args));
fs.mkdirSync(directory);
for (const name of ['plan.json','receipt.json']) fs.copyFileSync(path.join(fixture, name), path.join(directory, name));
process.exit(Number(process.env.MEMOIR_REPORT_TEST_EXIT));
`, {mode: 0o700});
      const result = spawnSync('make', ['--no-print-directory', 'memoir-live-fifty-test',
        `EVAL_RUN_ID=${plan.run_id}`, `EVAL_RUN_DIR=${join(directory, 'run')}`,
        'EVAL_CASE_ID=harbour-copper-notebook', 'EVAL_USER_EMAIL=test@test.com', `EVAL_START_BACKEND=${startBackend}`],
      {cwd: root, encoding: 'utf8', env: {...process.env, PATH: `${bin}:${process.env.PATH}`,
        MEMOIR_REPORT_TEST_FIXTURE: directory, MEMOIR_REPORT_TEST_EXIT: String(exitCode)}});
      assert.equal(result.status, exitCode === 0 ? 0 : 2, result.stderr || result.stdout);
      const args = JSON.parse(readFileSync(join(directory, 'args.json'), 'utf8'));
      assert.equal(args[0], 'scripts/run_memoir_supabase_evaluation.py');
      assert.ok(args.includes('--execute') && args.includes('--create-confirmed-test-user'));
      assert.equal(args.includes('--start-backend'), !!startBackend);
      assert.equal(args[args.indexOf('--case-id') + 1], 'harbour-copper-notebook');
      assert.equal(args[args.indexOf('--user-email') + 1], 'test@test.com');
      assert.match(readFileSync(join(directory, 'run', 'report.md'), 'utf8'), /remote Supabase; projects retained/);
    } finally {
      rmSync(directory, {recursive: true, force: true});
    }
  });
}

test('backend target starts only backend services from cached images', () => {
  const result = spawnSync('make', ['--no-print-directory', '-n', 'memoir-live-fifty-backend'], {cwd: root, encoding: 'utf8'});
  assert.equal(result.status, 0);
  assert.match(result.stdout, /--no-build.*api codex-worker photo-worker worker temporal/);
  assert.doesNotMatch(result.stdout, /\bweb\b|postgres|db-truncate/);
});

for (const selectedCase of ['', ...caseIds]) {
  test(`Make plan discovers local metadata for ${selectedCase || 'all five cases'} without executing binaries`, () => {
    const directory = mkdtempSync(join(tmpdir(), 'memoir-plan-defaults-'));
    try {
      const bin = join(directory, 'bin');
      mkdirSync(bin);
      const executable = '#!/bin/sh\necho must-not-execute >&2\nexit 99\n';
      for (const name of ['codex', 'temporal']) writeFileSync(join(bin, name), executable, { mode: 0o700 });
      const runDirectory = join(directory, 'unallocated');
      const result = spawnSync('make', ['--no-print-directory', 'memoir-live-fifty-disposable-plan',
        'EVAL_SOURCE_REVISION=', 'EVAL_CODEX_BINARY=', 'EVAL_CODEX_SHA256=',
        'EVAL_TEMPORAL_BINARY=', 'EVAL_TEMPORAL_SHA256=', `EVAL_CASE_ID=${selectedCase}`,
        `EVAL_RUN_DIR=${runDirectory}`, `ENV_FILE=${join(directory, 'absent.env')}`,
      ], { cwd: root, encoding: 'utf8', env: { ...process.env, PATH: `${bin}:${process.env.PATH}` } });
      assert.equal(result.status, 0, result.stderr || result.stdout);
      const plan = JSON.parse(result.stdout);
      const head = spawnSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).stdout.trim();
      assert.equal(plan.source_revision, head);
      assert.equal(plan.local_checkout_source.head, head);
      assert.match(plan.local_checkout_source.snapshot_sha256, /^[a-f0-9]{64}$/);
      assert.equal(plan.codex_binary, join(bin, 'codex'));
      assert.equal(plan.temporal_binary, join(bin, 'temporal'));
      assert.equal(plan.codex_sha256, createHash('sha256').update(executable).digest('hex'));
      assert.equal(plan.rounds_per_case, 50);
      assert.equal(plan.execution_started, false);
      assert.deepEqual(plan.case_ids, selectedCase ? [selectedCase] : caseIds);
      assert.deepEqual(plan.checkpoints, [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]);
      assert.equal(plan.max_client_requests, selectedCase ? 569 : 3000);
      assert.equal(plan.max_elapsed_seconds, selectedCase ? 7200 : 36000);
      assert.equal(plan.max_case_client_requests, selectedCase ? 569 : 600);
      assert.throws(() => statSync(runDirectory), { code: 'ENOENT' });
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });
}

test('Make refuses unknown case IDs and unknown source modes before execution', () => {
  const unknown = spawnSync('make', ['--no-print-directory', 'memoir-live-fifty-disposable-plan',
    'EVAL_CASE_ID=unknown'], { cwd: root, encoding: 'utf8' });
  assert.equal(unknown.status, 2);
  assert.match(unknown.stderr, /Unknown EVAL_CASE_ID/);
  const invalid = spawnSync('make', ['--no-print-directory', 'memoir-live-fifty-disposable-test',
    'EVAL_SOURCE_MODE=unknown', 'EVAL_CASE_ID=harbour-copper-notebook'], { cwd: root, encoding: 'utf8' });
  assert.equal(invalid.status, 2);
  assert.match(invalid.stderr, /EVAL_SOURCE_MODE must be local or reviewed/);
});

for (const [exitCode, selectedCase, defaults = false, sourceMode = 'local'] of [
  [0, ''], [3, ''], [0, caseIds[0]], [3, caseIds[0]],
  ...['', ...caseIds].map(id => [0, id, true]), [0, caseIds[0], false, 'reviewed'],
]) {
  test(`Make live renders ${selectedCase || 'all cases'} with ${defaults ? 'discovered' : 'explicit'} pins in ${sourceMode} mode and preserves exit ${exitCode}`, () => {
    const directory = mkdtempSync(join(tmpdir(), 'memoir-make-live-'));
    try {
      const { plan, receipt } = fixture();
      const head = spawnSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).stdout.trim();
      const python = spawnSync('python3', ['-c', 'import sys; print(sys.executable)'], { encoding: 'utf8' }).stdout.trim();
      if (defaults) plan.source_revision = receipt.source_revision = head;
      if (selectedCase) {
        plan.case_ids = [selectedCase];
        plan.cases = { [selectedCase]: plan.cases.harbour };
        receipt.evaluation.cases[0].case_id = selectedCase;
      }
      receipt.status = exitCode === 0 ? 'completed' : 'incomplete';
      writeFileSync(join(directory, 'fixture-plan.json'), JSON.stringify(plan));
      writeFileSync(join(directory, 'fixture-receipt.json'), JSON.stringify(receipt));
      const bin = join(directory, 'bin');
      mkdirSync(bin);
      writeFileSync(join(bin, 'python3'), `#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');
const args = process.argv.slice(2);
if (args[0] === '-c') {
  const result = require('node:child_process').spawnSync(process.env.MEMOIR_REPORT_TEST_PYTHON, args, { stdio: 'inherit' });
  process.exit(result.status ?? 99);
}
const fixture = process.env.MEMOIR_REPORT_TEST_FIXTURE;
const directory = args[args.indexOf('--run-dir') + 1];
fs.writeFileSync(path.join(fixture, 'args.json'), JSON.stringify(args));
fs.mkdirSync(directory, {recursive: true});
fs.copyFileSync(path.join(fixture, 'fixture-plan.json'), path.join(directory, 'plan.json'));
fs.copyFileSync(path.join(fixture, 'fixture-receipt.json'), path.join(directory, 'receipt.json'));
process.exit(Number(process.env.MEMOIR_REPORT_TEST_EXIT));
`, { mode: 0o700 });
      const executable = '#!/bin/sh\necho must-not-execute >&2\nexit 99\n';
      for (const name of ['codex', 'temporal']) writeFileSync(join(bin, name), executable, { mode: 0o700 });
      const runDirectory = join(directory, 'saved run');
      const result = spawnSync('make', ['--no-print-directory', 'memoir-live-fifty-disposable-test',
        `EVAL_SOURCE_REVISION=${defaults ? '' : plan.source_revision}`, `EVAL_SOURCE_MODE=${sourceMode}`,
        `EVAL_CODEX_BINARY=${defaults ? '' : '/synthetic/codex'}`,
        `EVAL_CODEX_SHA256=${defaults ? '' : 'b'.repeat(64)}`, `EVAL_TEMPORAL_BINARY=${defaults ? '' : '/synthetic/temporal'}`,
        `EVAL_TEMPORAL_SHA256=${defaults ? '' : 'c'.repeat(64)}`, `EVAL_RUN_ID=${plan.run_id}`,
        `EVAL_CASE_ID=${selectedCase}`,
        `EVAL_RUN_DIR=${runDirectory}`, `ENV_FILE=${join(directory, 'absent.env')}`,
      ], { cwd: root, encoding: 'utf8', env: { ...process.env, PATH: `${bin}:${process.env.PATH}`,
        MEMOIR_REPORT_TEST_FIXTURE: directory, MEMOIR_REPORT_TEST_EXIT: String(exitCode),
        MEMOIR_REPORT_TEST_PYTHON: python } });
      assert.equal(result.status, exitCode === 0 ? 0 : 2, result.stderr || result.stdout);
      if (exitCode) assert.match(result.stderr, /Error 3/);
      assert.match(readFileSync(join(runDirectory, 'report.md'), 'utf8'), /Run status:/);
      const args = JSON.parse(readFileSync(join(directory, 'args.json'), 'utf8'));
      assert.equal(args[0], 'scripts/run_issue14_subscription_evaluation.py');
      assert.equal(args[args.indexOf('--evaluation-profile') + 1], 'subscription_fifty');
      assert.ok(args.includes('--execute-existing-subscription'));
      assert.equal(args.includes('--local-checkout'), sourceMode === 'local');
      if (defaults) {
        assert.equal(args[args.indexOf('--source-revision') + 1], head);
        assert.equal(args[args.indexOf('--codex-binary') + 1], join(bin, 'codex'));
        assert.equal(args[args.indexOf('--temporal-binary') + 1], join(bin, 'temporal'));
        assert.equal(args[args.indexOf('--codex-sha256') + 1], createHash('sha256').update(executable).digest('hex'));
      }
      if (selectedCase) {
        assert.equal(args[args.indexOf('--case-id') + 1], selectedCase);
        assert.equal(args[args.indexOf('--max-client-requests') + 1], '569');
        assert.ok(result.stderr.includes(`Case ${selectedCase}, 50 rounds`));
      } else {
        assert.ok(!args.includes('--case-id'));
      }
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });
}
