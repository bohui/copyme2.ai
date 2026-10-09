"""Explicit native-owned browser producer for the fifty-round profile.

Import/admission is offline. Native execution requires existing hash-pinned
Python, Node, Chromium, Next and Playwright, plus the entire tracked frontend.
No install, browser download, login, production edit or response replay occurs.
The default observes saved real API reads only. The separate explicit turn mode
submits original text with the real UI into the API's one-shot admitted handler.
Neither mode grants semantic acceptance or a full-E2E pass.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import zlib
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
CONFIG_SCHEMA = 'memoir-fifty-browser-config/1'
LIFE_STAGES = ('baby', 'toddler', 'childhood', 'adolescence', 'young_adulthood', 'midlife', 'later_life')
# These are the exact versioned visualization URLs in the reviewed frontend.
# Optional fonts, maps, photos, telemetry, and authentication CDNs stay blocked.
PUBLIC_ASSETS = (
    'https://unpkg.com/d3@7.9.0/dist/d3.min.js',
    'https://unpkg.com/family-chart@0.9.0/dist/styles/family-chart.css',
    'https://unpkg.com/family-chart@0.9.0/dist/family-chart.min.js',
    'https://unpkg.com/vis-timeline@7.7.3/styles/vis-timeline-graph2d.min.css',
    'https://unpkg.com/vis-timeline@7.7.3/standalone/umd/vis-timeline-graph2d.min.js',
)
_PIN_FIELDS = ('node_executable', 'python_executable', 'chromium_executable',
               'playwright_module', 'next_cli', 'next_cli_docs')
_REQUIRED = frozenset(('schema_version', 'source_revision', 'source_root', 'output_root',
    'node_modules', 'binary_sha256', 'frontend_sha256', *_PIN_FIELDS))
_OPTIONAL = frozenset(('max_requests', 'public_asset_urls', 'allow_browser_turns'))
_TERM_GRACE_SECONDS = 3
_KILL_GRACE_SECONDS = 2
_READ_PATHS = frozenset(('/agent/config', '/agent/profile', '/agent/place-journey',
    '/agent/family-context', '/story/state', '/story/readiness', '/story/private-draft',
    '/story/events', '/user/profile', '/user/projects'))


def _assert_session(session):
    from scripts.issue14_subscription_session import assert_owned_subscription_session
    assert_owned_subscription_session(session)
    if session.evaluation_profile != 'subscription_fifty':
        raise ValueError('An issued fifty-round session is required')


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ordinary(path):
    path = Path(path)
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ValueError('An absolute ordinary existing file is required')
    # Reject parent symlink traversal too; native owner supplies resolved paths.
    if path.resolve() != path:
        raise ValueError('Resolved ordinary paths are required')
    return path


def _tracked_frontend(root):
    value = subprocess.check_output(['git', 'ls-files', '-z', '--', 'apps/web'], cwd=root,
        env={'PATH': os.defpath, 'LC_ALL': 'C', 'GIT_NO_LAZY_FETCH': '1', 'GIT_TERMINAL_PROMPT': '0'})
    names = value.decode().split('\0')
    result = tuple(sorted(name for name in names if name))
    if not result or len(result) != len(set(result)):
        raise ValueError('Complete tracked frontend inventory is required')
    return result


def validate_browser_config(config, *, source_revision, source_root=ROOT):
    """Validate and detach native pins; never allocate services or executors."""
    if type(config) is not dict or set(config) - _REQUIRED - _OPTIONAL or not _REQUIRED <= set(config):
        raise ValueError('Exact browser config fields are required')
    value = deepcopy(config)
    if (value['schema_version'] != CONFIG_SCHEMA or value['source_revision'] != source_revision
            or not isinstance(source_revision, str) or not re.fullmatch(r'[0-9a-f]{40}', source_revision)):
        raise ValueError('Browser source revision differs')
    root = Path(value['source_root'])
    if not root.is_absolute() or root.resolve() != Path(source_root).resolve() or root.resolve() != root:
        raise ValueError('Browser source root differs')
    output = Path(value['output_root'])
    deps = Path(value['node_modules'])
    if (not output.is_absolute() or output != output.resolve() or output.exists()
            or not deps.is_absolute() or not deps.is_dir() or deps != deps.resolve()
            or output.is_relative_to(root / 'apps/web') or output.is_relative_to(deps)):
        raise ValueError('A fresh private output and existing resolved dependencies are required')
    pins = value['binary_sha256']
    paths = {value[key] for key in _PIN_FIELDS}
    if type(pins) is not dict or set(pins) != paths or len(paths) != len(_PIN_FIELDS):
        raise ValueError('Exact installed runtime pins are required')
    for key in _PIN_FIELDS:
        path = _ordinary(value[key])
        if not re.fullmatch(r'[0-9a-f]{64}', str(pins[str(path)])) or _sha(path) != pins[str(path)]:
            raise ValueError('Installed runtime hash differs')
        if key.endswith('_executable') and not os.access(path, os.X_OK):
            raise ValueError('Installed executable is not executable')
    if not all(Path(value[key]).is_relative_to(deps) for key in ('next_cli', 'next_cli_docs')):
        raise ValueError('Next CLI and its local docs must be in the installed dependencies')
    docs = Path(value['next_cli_docs']).read_text()
    if not all(flag in docs for flag in ('next dev', '--hostname', '--port', '--webpack')):
        raise ValueError('Installed Next CLI documentation must verify the exact launch flags')
    manifest = value['frontend_sha256']
    if type(manifest) is not dict or set(manifest) != set(_tracked_frontend(root)):
        raise ValueError('Full tracked frontend manifest is required')
    for name, digest in manifest.items():
        path = _ordinary(root / name)
        if (not path.is_relative_to(root / 'apps/web') or '/node_modules/' in name
                or '/.next/' in name or path.name == '.env' or path.name.startswith('.env.')
                or not re.fullmatch(r'[0-9a-f]{64}', str(digest)) or _sha(path) != digest):
            raise ValueError('Frontend source hash or inventory differs')
    package = json.loads((root / 'apps/web/package.json').read_text())
    if package.get('scripts', {}).get('dev') != 'next dev':
        raise ValueError('Reviewed existing Next dev command is required')
    if 'MEMORY_SPARK_API_ORIGIN' not in (root / 'apps/web/next.config.mjs').read_text():
        raise ValueError('Reviewed loopback API rewrite is required')
    maximum = value.setdefault('max_requests', 256)
    if type(maximum) is not int or not 16 <= maximum <= 512:
        raise ValueError('Browser request cap must be an integer from 16 through 512')
    assets = value.setdefault('public_asset_urls', list(PUBLIC_ASSETS))
    if type(assets) is not list or len(assets) != len(set(assets)) or not set(assets) <= set(PUBLIC_ASSETS):
        raise ValueError('Only exact reviewed public visualization assets are permitted')
    if 'allow_browser_turns' in value and type(value['allow_browser_turns']) is not bool:
        raise ValueError('Explicit browser turn choice must be boolean')
    return value


def _copy_frontend(plan):
    root, output = Path(plan['source_root']), Path(plan['output_root'])
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    web = output / 'frontend'
    web.mkdir(mode=0o700)
    for name, digest in plan['frontend_sha256'].items():
        source = _ordinary(root / name)
        if _sha(source) != digest:
            raise ValueError('Frontend source hash changed before copy')
        destination = web / Path(name).relative_to('apps/web')
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
        if _sha(destination) != digest:
            raise ValueError('Frontend private copy hash differs')
    (web / 'node_modules').symlink_to(plan['node_modules'], target_is_directory=True)
    (output / 'tmp').mkdir(mode=0o700)
    return web


def _child_environment(output):
    # Do not pass the owner's HOME, PATH, proxies, auth, NODE_OPTIONS or .env.
    return {'PATH': os.defpath, 'LANG': 'en_US.UTF-8', 'LC_ALL': 'C',
        'TMPDIR': str(output / 'tmp'), 'NEXT_TELEMETRY_DISABLED': '1',
        'PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD': '1', 'CI': '1'}


def _api_paths(project_id):
    paths = set(_READ_PATHS)
    paths.update({f'/projects/{project_id}', f'/projects/{project_id}/journey',
                  f'/user/projects/{project_id}/history'})
    paths.update(f'/projects/{project_id}/{part}' for part in
                 ('memories', 'sources', 'chapters', 'people', 'relationships', 'timeline'))
    return sorted('/api/v1/memoir' + path for path in paths)


def _safe_local_path(path):
    """Allow only bracket escapes for complete Next dynamic-route segments.

    Never generally URL-decode a path: encoded dots, separators, percent signs
    and malformed escapes remain refused. Catch-all dots are valid only inside
    a well-formed route segment beneath the existing Next static boundary.
    """
    if '\\' in path or any(part in ('.', '..') for part in path.split('/')):
        return False
    if '%' not in path and '..' not in path:
        return True
    if not path.startswith('/_next/static/'):
        return False
    decoded = re.sub(r'%5[bBdD]', lambda match: '[' if match.group().lower() == '%5b' else ']', path)
    if '%' in decoded:
        return False
    for part in decoded[len('/_next/static/'):].split('/'):
        if not part or part == '.':
            return False
        if ('..' in part or '[' in part or ']' in part) and not re.fullmatch(
                r'(?:\[(?:\.\.\.)?[A-Za-z0-9_-]+\]|\[\[\.\.\.[A-Za-z0-9_-]+\]\])', part):
            return False
    return True


def request_policy(method, url, *, frontend_origin, project_id, public_asset_urls=PUBLIC_ASSETS):
    """Pure reference policy mirrored by the browser's fail-closed route guard."""
    denied = {'allowed': False, 'synthetic_auth': False}
    try:
        if any(ord(char) <= 32 or ord(char) == 127 for char in url):
            return denied
        parsed, origin = urlsplit(url), urlsplit(frontend_origin)
        if method not in ('GET', 'HEAD') or parsed.username or parsed.password or parsed.fragment:
            return denied
        if url in public_asset_urls:
            return {'allowed': True, 'synthetic_auth': False}
        if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1'
                or parsed.netloc != origin.netloc or origin.hostname != '127.0.0.1'
                or not _safe_local_path(parsed.path) or '\\' in url):
            return denied
        api = parsed.path in _api_paths(project_id)
        if api:
            query = parse_qs(parsed.query, keep_blank_values=True)
            if (set(query) - {'project_id', 'language', 'limit', 'cursor'}
                    or any(len(values) != 1 for values in query.values())
                    or 'project_id' in query and query['project_id'] != [project_id]):
                return denied
            return {'allowed': True, 'synthetic_auth': True}
        allowed = (parsed.path == f'/memoir/interview/{project_id}'
            or parsed.path.startswith('/_next/static/') or parsed.path.startswith('/static/'))
        return {'allowed': allowed, 'synthetic_auth': False}
    except (ValueError, TypeError):
        return denied


def _visible_reply(value):
    # The same two public presentation filters as cleanAssistantText in client.js.
    value = re.sub(r'\[\[MEMORY_SPARK_PROFILE\]\].*?\[\[/MEMORY_SPARK_PROFILE\]\]', '', value, flags=re.S)
    value = re.sub(r'<!--\s*profile\s*:.*?(?:-->|$)', '', value, flags=re.S | re.I)
    return ' '.join(value.split())


def _png_receipt(path, root):
    path = _ordinary(path)
    if not path.is_relative_to(root):
        raise ValueError('Screenshot escaped the owned output')
    raw = path.read_bytes()
    if (len(raw) < 45 or len(raw) > 20_000_000 or raw[:8] != b'\x89PNG\r\n\x1a\n'
            or raw[12:16] != b'IHDR' or raw[-12:] != b'\x00\x00\x00\x00IEND\xaeB`\x82'):
        raise ValueError('A real bounded PNG screenshot is required')
    width, height = int.from_bytes(raw[16:20], 'big'), int.from_bytes(raw[20:24], 'big')
    if not 0 < width <= 10000 or not 0 < height <= 50000:
        raise ValueError('PNG dimensions exceed the owned capture limit')
    offset, chunks, compressed = 8, [], bytearray()
    while offset < len(raw):
        if offset + 12 > len(raw):
            raise ValueError('PNG chunk is truncated')
        length = int.from_bytes(raw[offset:offset + 4], 'big')
        kind = raw[offset + 4:offset + 8]
        end = offset + 8 + length
        if end + 4 > len(raw) or zlib.crc32(raw[offset + 4:end]) != int.from_bytes(raw[end:end + 4], 'big'):
            raise ValueError('PNG chunk checksum differs')
        chunks.append(kind)
        if kind == b'IDAT':
            compressed.extend(raw[offset + 8:end])
        offset = end + 4
    if (chunks[0] != b'IHDR' or chunks[-1] != b'IEND' or b'IDAT' not in chunks
            or raw[24] != 8 or raw[25] not in (2, 6) or raw[26:29] != b'\0\0\0'):
        raise ValueError('Unsupported or incomplete screenshot PNG')
    expected = (width * (3 if raw[25] == 2 else 4) + 1) * height
    if expected > 100_000_000:
        raise ValueError('PNG decoded pixels exceed the owned capture limit')
    try:
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(compressed, expected + 1)
        if len(pixels) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('PNG pixel payload differs')
    except zlib.error:
        raise ValueError('PNG pixel payload is corrupt') from None
    return {'path': str(path.relative_to(root)), 'sha256': hashlib.sha256(raw).hexdigest(),
            'bytes': len(raw), 'width': width, 'height': height}


# Runs only through the pinned Node binary. It connects to Chromium launched by
# this Python owner, so Playwright never creates a detached browser process.
BROWSER_SCRIPT = r'''
"use strict";
const fs = require("fs"), path = require("path"), crypto = require("crypto");
const c = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const {chromium} = require(c.playwright_module);
const sha = x => crypto.createHash("sha256").update(x).digest("hex");
const stages = ["baby", "toddler", "childhood", "adolescence", "young_adulthood", "midlife", "later_life"];
const report = {schema_version:"memoir-fifty-browser-observation/1", case_id:c.case_id,
  project_id:c.project_id, ordinal:c.turn?.ordinal || null, mode:c.turn ? "ui_original_turn" : "saved_readback",
  status:"started", original_turn_submission:c.turn ? "browser_form" : "not_performed",
  network:[], page_errors:[], console_errors:[], views:[], checks:{}, e2e_passed:false};
const responses = [], apiBodies = new Map(); let browser, context, page, cdp, sent = false, attempts = 0;
const allowedAssets = new Set(c.public_asset_urls), readPaths = new Set(c.api_paths);
const origin = new URL(c.frontend_origin); let lastActivity = Date.now(), inflight = 0;
function safeLocalPath(rawPath) {
  if (typeof rawPath !== "string" || rawPath.includes("\\") || rawPath.split("/").some(part => part === "." || part === "..")) return false;
  if (!rawPath.includes("%") && !rawPath.includes("..")) return true;
  if (!rawPath.startsWith("/_next/static/")) return false;
  const decoded = rawPath.replace(/%5[bBdD]/g, escape => escape.toLowerCase() === "%5b" ? "[" : "]");
  if (decoded.includes("%")) return false;
  return decoded.slice("/_next/static/".length).split("/").every(part => part && part !== "." &&
    (!(part.includes("..") || part.includes("[") || part.includes("]")) || /^(?:\[(?:\.\.\.)?[A-Za-z0-9_-]+\]|\[\[\.\.\.[A-Za-z0-9_-]+\]\])$/.test(part)));
}
function decision(request) {
  const raw = request.url(), method = request.method();
  if (++attempts > c.max_requests) { report.request_budget_exhausted = true; return {ok:false, reason:"request_cap"}; }
  if (/[\x00-\x20\x7f]/.test(raw)) return {ok:false, reason:"URL_scope"};
  const u = new URL(raw);
  if (u.username || u.password || u.hash || raw.includes("\\")) return {ok:false, reason:"URL_scope"};
  if (["GET", "HEAD"].includes(method) && allowedAssets.has(raw)) return {ok:true, api:false};
  // URL() normalizes dot segments. Inspect the untouched path before admitting
  // its normalized pathname, so traversal cannot collapse into an allowed URL.
  const rawPath = raw.match(/^http:\/\/[^/?#]*([^?#]*)/)?.[1];
  if (u.origin !== origin.origin || u.hostname !== "127.0.0.1" || u.protocol !== "http:" || !safeLocalPath(rawPath)) return {ok:false, reason:"origin_scope"};
  if (method === "POST" && u.pathname === "/api/v1/memoir/agent/turn" && !u.search && c.turn && !sent) {
    let body; try { body = request.postDataJSON(); } catch { return {ok:false, reason:"turn_payload"}; }
    const keys = new Set(["text","conversation_text","source_kind","client_turn_id","project_id","language","first_reply_localization","uploaded_photo_ids","photo_selection"]);
    if (!body || Object.keys(body).some(k => !keys.has(k)) || !c.turn.allowed_texts.includes(body.text)
        || body.conversation_text !== c.turn.text || body.project_id !== c.project_id
        || body.language !== c.language || body.source_kind !== "narrator_chat"
        || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(body.client_turn_id || "")
        || typeof body.first_reply_localization !== "boolean" || body.first_reply_localization && c.turn.ordinal !== 1
        || (body.uploaded_photo_ids || []).length || body.photo_selection) return {ok:false, reason:"turn_payload"};
    sent = true; report.turn_submission = {client_turn_id:body.client_turn_id, text_sha256:sha(body.conversation_text), provider_input_sha256:sha(body.text), method:"POST", path:u.pathname};
    return {ok:true, api:true};
  }
  if (!["GET", "HEAD"].includes(method)) return {ok:false, reason:"mutation_denied"};
  if (readPaths.has(u.pathname)) {
    const keys = [...u.searchParams.keys()];
    if (keys.some(k => !["project_id","language","limit","cursor"].includes(k) || u.searchParams.getAll(k).length !== 1)
        || u.searchParams.has("project_id") && u.searchParams.get("project_id") !== c.project_id) return {ok:false, reason:"project_scope"};
    return {ok:true, api:true};
  }
  return {ok:u.pathname === c.interview_path || u.pathname.startsWith("/_next/static/") || u.pathname.startsWith("/static/"), api:false, reason:"route_scope"};
}
async function quiet(page) {
  const start = Date.now();
  while (Date.now() - start < Math.min(5000, c.timeout_ms / 4)) {
    if (inflight === 0 && Date.now() - lastActivity > 250) return;
    await page.waitForTimeout(50);
  }
}
async function capture(page, name) {
  await quiet(page);
  const dom = await page.evaluate(() => ({url:location.href, language:document.documentElement.lang,
    users:[...document.querySelectorAll("#chat-history .user-message .message-text")].map(n => n.innerText),
    assistants:[...document.querySelectorAll("#chat-history .assistant-message .message-text")].map(n => n.innerText),
    workspace:document.querySelector("#workspace-detail")?.innerText || "",
    family:[...document.querySelectorAll(".family-chart-adapter [data-family-person]")].map(n => n.innerText || n.textContent),
    timeline:[...document.querySelectorAll(".timeline-row strong")].map(n => n.innerText),
    places:[...document.querySelectorAll(".place-journey-heading h2, [data-place-choice] span")].map(n => n.innerText),
    draft:document.querySelector(".private-draft-status")?.innerText || "",
    renderers:[...document.querySelectorAll("[data-renderer]")].map(n => ({renderer:n.dataset.renderer, status:n.dataset.rendererStatus || "fallback"})),
    life_stages:[...document.querySelectorAll("[data-life-stage-tab]")].map(n => ({stage:n.dataset.lifeStageTab, selected:n.getAttribute("aria-pressed")})),
    images:[...document.images].map(n => ({src:n.currentSrc || n.src, loaded:n.complete && n.naturalWidth > 0})),
    alerts:[...document.querySelectorAll("[role=alert]")].map(n=>n.innerText)}));
  const filename = name + ".png";
  await page.screenshot({path:path.join(c.output_dir, filename), type:"png", fullPage:false});
  const raw = fs.readFileSync(path.join(c.output_dir, filename));
  report.views.push({name, dom, dom_sha256:sha(JSON.stringify(dom)), screenshot:{path:filename,sha256:sha(raw),bytes:raw.length}});
}
(async () => {
 try {
  browser = await chromium.connectOverCDP(c.cdp_origin, {timeout:c.timeout_ms});
  context = await browser.newContext({viewport:{width:1440,height:1100}, locale:c.language,
    serviceWorkers: "block", acceptDownloads:false});
  if (typeof context.routeWebSocket !== "function") throw new Error("Installed Playwright must support blocking WebSockets");
  await context.routeWebSocket("**/*", ws => { report.websockets_blocked = (report.websockets_blocked || 0) + 1; ws.close(); });
  await context.route("**/*", async route => {
    const request = route.request();
    let scoped = false;
    try { scoped = !!page && request.frame() === page.mainFrame(); } catch {}
    const policy = decision(request);
    if (!scoped) { policy.ok=false; policy.api=false; policy.reason="unsupported_target"; }
    if (report.network.length < c.max_requests + 1) report.network.push({method:request.method(),url:request.url(),allowed:policy.ok,reason:policy.ok ? null : policy.reason,synthetic_auth:!!(policy.ok && policy.api)});
    if (!policy.ok) return route.abort("blockedbyclient");
    const headers = {...request.headers()};
    for (const key of Object.keys(headers)) if (["authorization","cookie","x-csrf-token","proxy-authorization"].includes(key.toLowerCase())) delete headers[key];
    // This header is never a context default or attached to public CDNs.
    if (policy.api) headers.authorization = "Bearer " + c.owner_id;
    await route.continue({headers});
  });
  context.on("page", extra => { if (page && extra !== page) { report.extra_pages_blocked=(report.extra_pages_blocked || 0)+1; void extra.close(); } });
  page = await context.newPage();
  page.on("download", download => { report.downloads_blocked=(report.downloads_blocked || 0)+1; void download.cancel(); });
  // Response-stage interception runs BEFORE the browser can follow Location.
  // Deny all redirects, including approved-URL redirects. No redirected request
  // can inherit synthetic headers or bypass the pre-send request counter.
  cdp = await context.newCDPSession(page);
  cdp.on("Fetch.requestPaused", event => {
    const job = (async () => {
      const redirect = [301,302,303,307,308].includes(event.responseStatusCode);
      if (redirect) {
        report.redirects_blocked=(report.redirects_blocked || 0)+1;
        await cdp.send("Fetch.failRequest", {requestId:event.requestId,errorReason:"BlockedByClient"});
      } else await cdp.send("Fetch.continueRequest", {requestId:event.requestId});
    })();
    job.catch(async () => { report.response_guard_failed=true; await context.close().catch(()=>{}); });
  });
  await cdp.send("Fetch.enable", {patterns:[{urlPattern:"*",requestStage:"Response"}]});
  page.setDefaultTimeout(Math.min(c.timeout_ms, 30000));
  page.on("pageerror", error => report.page_errors.push(String(error.message).slice(0,2000)));
  page.on("console", message => { if (message.type() === "error" && report.console_errors.length < 100) report.console_errors.push(message.text().slice(0,2000)); });
  page.on("request", () => { inflight++; lastActivity = Date.now(); });
  page.on("requestfinished", () => { inflight = Math.max(0,inflight-1); lastActivity = Date.now(); });
  page.on("requestfailed", req => { inflight = Math.max(0,inflight-1); lastActivity = Date.now(); const row = report.network.findLast(n=>n.url===req.url() && !n.failure); if(row) row.failure = req.failure()?.errorText || "failed"; });
  page.on("response", response => {
    const job = (async () => {
      const row = report.network.findLast(n=>n.url===response.url() && n.status===undefined);
      if (row) row.status = response.status();
      const u = new URL(response.url());
      if (u.origin !== origin.origin || !readPaths.has(u.pathname) || !response.ok()) return;
      const raw = await response.body();
      if (raw.length > 4000000) throw new Error("API evidence size exceeds cap");
      if (row) { row.response_sha256=sha(raw); row.response_bytes=raw.length; row.fixture=response.headers()["x-evaluation-fixture"] || null; }
      try { const body=JSON.parse(raw.toString("utf8")); apiBodies.set(response.url(),body); } catch { throw new Error("Owned read response was not JSON"); }
    })();
    responses.push(job); job.catch(()=>{});
  });
  await page.goto(c.frontend_origin + c.interview_path, {waitUntil:"domcontentloaded", timeout:c.timeout_ms});
  await page.locator("#chat-input").waitFor({state:"visible", timeout:c.timeout_ms});
  await quiet(page);
  if (c.turn) {
    await page.waitForFunction(() => !document.querySelector(".message-streaming") && !document.querySelector(".thinking") && !document.querySelector("#chat-form button[type=submit]")?.disabled, null, {timeout:c.timeout_ms});
    report.before_turn_counts={users:await page.locator("#chat-history .user-message").count(),assistants:await page.locator("#chat-history .assistant-message").count()};
    await page.locator("#chat-input").fill(c.turn.text);
    const reply = page.waitForResponse(r => r.url() === c.frontend_origin + "/api/v1/memoir/agent/turn" && r.request().method() === "POST", {timeout:c.timeout_ms});
    const [result] = await Promise.all([reply, page.locator("#chat-form button[type=submit]").click()]); if (!result.ok()) throw new Error("Admitted browser turn failed");
    await result.finished();
    await page.waitForFunction(() => !document.querySelector(".message-streaming") && !document.querySelector("#chat-form button[type=submit]")?.disabled, null, {timeout:c.timeout_ms});
    report.checks.ui_form_submitted_once = sent;
  }
  const history = page.locator('[data-action="toggle-chat-history"]');
  if (await history.count() && await history.getAttribute("aria-expanded") === "false") await history.click();
  await capture(page,"history");
  if (!c.turn) {
    const workspace = page.locator('[data-action="toggle-workspace"]');
    if (await workspace.count() && await workspace.first().getAttribute("aria-expanded") === "false") await workspace.first().click();
    for (const tab of ["memoir","family","timeline"]) {
      const button = page.locator('[data-workspace-tab="' + tab + '"]');
      if (!(await button.count())) { report.checks[tab + "_view"]="unavailable"; continue; }
      await button.first().click();
      const details=page.locator('.private-draft-status details:not([open]) summary');
      if (await details.count()) await details.first().click();
      await capture(page,tab); report.checks[tab + "_view"]="observed";
    }
    for (const stage of stages) {
      const button=page.locator('[data-life-stage-tab="' + stage + '"]');
      if (!(await button.count())) { report.checks[stage + "_view"]="unavailable"; continue; }
      await button.first().click(); await capture(page,"stage-" + stage);
      report.checks[stage + "_view"]="observed";
    }
  }
  await Promise.all(responses);
  const norm = value => String(value || "").replace(/\s+/g," ").trim();
  const allViews=report.views.map(v=>v.dom), users=allViews[0]?.users || [];
  if (c.turn) {
    const assistants=allViews[0]?.assistants || [];
    report.checks.ui_original_text_visible=users.length === report.before_turn_counts.users + 1 && norm(users.at(-1)) === norm(c.turn.text);
    report.checks.ui_new_reply_visible=assistants.length > report.before_turn_counts.assistants && !!norm(assistants.at(-1));
  }
  const histories=[...apiBodies.entries()].filter(([url])=>new URL(url).pathname.endsWith("/history")).map(([,body])=>body);
  const historyTexts=histories.flatMap(body=>(body.items || []).map(item=>item.narrator_text).filter(Boolean));
  report.checks.saved_history_api_observed=histories.length > 0;
  report.checks.saved_history_dom_matches=historyTexts.length > 0 && historyTexts.every(text=>users.some(user=>norm(user)===norm(text)));
  const allText=norm(allViews.map(v=>[v.workspace,v.draft,...v.family,...v.timeline,...v.places].join(" ")).join(" "));
  for (const [suffix,field,pluck] of [["/family-context","family",b=>(b.family_context?.people || []).map(p=>p.name)], ["/events","timeline",b=>(b.events || []).map(e=>e.title)], ["/private-draft","draft",b=>b.preview?.text ? [b.preview.text] : []]]) {
    const data=[...apiBodies.entries()].filter(([url])=>new URL(url).pathname.endsWith(suffix)).flatMap(([,b])=>pluck(b)).filter(Boolean);
    report.checks[field + "_api_items"]=data.length;
    report.checks[field + "_dom_matches"]=data.length ? data.every(text=>allText.includes(norm(text))) : null;
  }
  const places=[...apiBodies.entries()].filter(([url])=>new URL(url).pathname.endsWith("/user/profile"))
    .flatMap(([,body])=>(body.memory_places || []).map(p=>p.place)).filter(Boolean);
  report.checks.place_api_items=places.length;
  report.checks.place_dom_matches=places.length ? places.every(text=>allText.includes(norm(text))) : null;
  const ownedResponses=report.network.filter(n=>n.response_sha256);
  report.checks.api_responses_are_owned=ownedResponses.length > 0 && ownedResponses.every(n=>n.fixture === c.expected_api_fixture);
  report.checks.page_errors_absent=report.page_errors.length === 0;
  report.request_count=attempts;
  report.requests_forwarded=report.network.filter(n=>n.allowed).length;
  report.checks.terminal_network_scope_valid=!report.request_budget_exhausted && !report.response_guard_failed;
  report.status=report.checks.terminal_network_scope_valid ? "observed" : "incomplete";
 } catch (error) { report.status="incomplete"; report.failure=String(error.message).slice(0,2000); }
 finally {
  report.context_closed=!context;
  if (context) { try { await context.close(); report.context_closed=true; } catch { report.context_cleanup_failed=true; report.status="incomplete"; } }
  if (browser) { try { await browser.close(); report.browser_disconnected=true; } catch { report.browser_disconnected=false; report.status="incomplete"; } }
  fs.writeFileSync(c.receipt_path,JSON.stringify(report,null,2),{flag:"wx",mode:0o600});
 }
})().catch(()=>{process.exitCode=1;});
'''


class OwnedFiftyBrowserReadback:
    """Own the API, private frontend, Chromium and bounded per-operation workers."""
    def __init__(self):
        raise TypeError('Use admit() with an issued session and native pins')

    @classmethod
    def admit(cls, session, config):
        _assert_session(session)
        plan = validate_browser_config(config, source_revision=session.run.source_revision,
                                       source_root=ROOT)
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True,
            env={'PATH': os.defpath, 'LC_ALL': 'C', 'GIT_NO_LAZY_FETCH': '1', 'GIT_TERMINAL_PROMPT': '0'}).strip()
        if head != session.run.source_revision:
            raise ValueError('Actual browser source HEAD differs from the admitted revision')
        if Path(plan['python_executable']).resolve() != Path(sys.executable).resolve():
            raise ValueError('The current native owner must be the pinned Python executable')
        from scripts.memoir_fifty_browser import OwnedFiftyBrowserAPI
        self = object.__new__(cls)
        self._session, self._config = session, plan
        self._plans = deepcopy(session.case_plans)
        self._api = OwnedFiftyBrowserAPI.build(session)
        if plan.get('allow_browser_turns', False):
            self._api.enable_turns()
        self._closed, self._busy = False, False
        self._api_cleanup_complete = False
        self._web = self._case = self._frontend = self._chromium = None
        self._processes, self._observations, self._cleanup = [], [], []
        self._startup_requests = []
        self._turn_ordinals, self._observed_cases = {}, set()
        self._pid = os.getpid()
        return self

    @property
    def turns_enabled(self):
        return self._config.get('allow_browser_turns', False)

    def _remaining(self, case):
        _assert_session(self._session)
        if self._closed or case not in self._plans:
            raise ValueError('Owned browser producer is closed or case differs')
        active = getattr(self._session.run, '_active_case', None)
        if not active or active.get('case_id') != case:
            raise ValueError('Browser work requires the same original active case')
        remaining = self._session.run.remaining_seconds()
        if remaining <= 0:
            raise ValueError('Original case deadline exhausted')
        return remaining

    def _check(self, case):
        if os.getpid() != self._pid or self._session.case_plans != self._plans:
            raise ValueError('Browser producer ownership changed')
        self._api._check()
        return self._remaining(case)

    async def _spawn(self, command, *, cwd, env, kind):
        async def allocate():
            process = await asyncio.create_subprocess_exec(*command, cwd=cwd, env=env,
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
            self._processes.append((kind, process))
            return process
        # Cancellation cannot discard a newly spawned child before its handle
        # enters the owned registry used by the caller's finally cleanup.
        return await self._join_cleanup(asyncio.create_task(allocate()))

    async def _join_cleanup(self, task):
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                # Repeated cancellation is recorded, never passed into owned
                # process cleanup. It is re-raised only after the join finishes.
                cancelled = True
        result = task.result()
        if cancelled:
            raise asyncio.CancelledError
        return result

    async def _stop(self, kind, process):
        if process is None:
            return
        await self._join_cleanup(asyncio.create_task(self._stop_owned(kind, process)))

    async def _stop_owned(self, kind, process):
        loop = asyncio.get_running_loop()
        record = {'kind': kind, 'pid': process.pid, 'joined': False, 'group_gone': False}
        self._cleanup.append(record)
        def exists():
            try:
                os.killpg(process.pid, 0)
                return True
            except ProcessLookupError:
                return False
        try:
            # The leader exiting does not establish descendant termination.
            if exists():
                try: os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError: pass
            deadline = loop.time() + _TERM_GRACE_SECONDS
            try:
                await asyncio.wait_for(process.wait(), max(.001, deadline - loop.time()))
            except asyncio.TimeoutError:
                pass
            while exists() and loop.time() < deadline:
                await asyncio.sleep(.05)
            if exists():
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
            await asyncio.wait_for(process.wait(), max(.001, _KILL_GRACE_SECONDS))
            deadline = loop.time() + _KILL_GRACE_SECONDS
            while exists() and loop.time() < deadline:
                await asyncio.sleep(.05)
            record.update(joined=True, returncode=process.returncode, group_gone=not exists())
            if not record['group_gone']:
                raise RuntimeError('Owned process group remains after forced cleanup')
            self._processes = [(name, child) for name, child in self._processes if child is not process]
        except BaseException as error:
            record['failure_type'] = type(error).__name__
            raise

    async def _close_case(self):
        errors = []
        for kind, process in reversed(list(self._processes)):
            try:
                await self._stop(kind, process)
            except BaseException as error:
                errors.append(error)
        self._frontend = self._chromium = self._case = None
        if errors:
            raise errors[0]

    async def _ensure_case(self, case):
        self._check(case)
        if self._case == case:
            if self._frontend.returncode is not None or self._chromium.returncode is not None:
                raise ValueError('Owned frontend or Chromium exited')
            return
        await self._close_case()
        if self._web is None:
            # Recheck all runtime/source pins immediately before first allocation.
            validate_browser_config(self._config, source_revision=self._session.run.source_revision,
                                    source_root=ROOT)
            self._web = _copy_frontend(self._config)
            self._script = Path(self._config['output_root']) / 'browser-worker.cjs'
            self._script.write_text(BROWSER_SCRIPT)
            await self._api.start()
        await self._api.prepare_project(case)
        self._check(case)
        output = Path(self._config['output_root'])
        case_dir = output / case
        case_dir.mkdir(mode=0o700)
        self._case_dir = case_dir
        env = _child_environment(output)
        env['MEMORY_SPARK_API_ORIGIN'] = self._api.origin_for_case(case)
        marker = uuid4().hex
        marker_path = self._web / 'public' / ('owned-browser-' + marker + '.txt')
        marker_path.parent.mkdir(exist_ok=True)
        marker_path.write_text(marker)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        self._origin = f'http://127.0.0.1:{port}'
        self._frontend = await self._spawn([self._config['node_executable'], self._config['next_cli'],
            'dev', '--webpack', '--hostname', '127.0.0.1', '--port', str(port)],
            cwd=self._web, env=env, kind='frontend')
        import httpx
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
            for attempt in range(60):
                if self._frontend.returncode is not None:
                    raise ValueError('Owned private Next frontend failed to start')
                self._check(case)
                try:
                    response = await client.get(self._origin + '/' + marker_path.name,
                                                timeout=min(1, self._remaining(case)))
                    self._startup_requests.append({'case_id': case, 'method': 'GET',
                        'purpose': 'private_frontend_marker', 'status': response.status_code})
                    if response.status_code == 200 and response.text == marker:
                        break
                except httpx.TransportError:
                    self._startup_requests.append({'case_id': case, 'method': 'GET',
                        'purpose': 'private_frontend_marker', 'status': 'connection_unavailable'})
                await asyncio.sleep(.1)
            else:
                raise ValueError('Private frontend readiness request cap exhausted')
        profile = case_dir / 'chromium-profile'
        profile.mkdir(mode=0o700)
        self._chromium = await self._spawn([self._config['chromium_executable'], '--headless',
            '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0',
            '--user-data-dir=' + str(profile), '--no-first-run', '--no-default-browser-check',
            '--disable-background-networking', '--disable-component-update', '--disable-sync',
            '--disable-default-apps', '--disable-extensions', '--disable-domain-reliability',
            '--metrics-recording-only',
            '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE unpkg.com', 'about:blank'], cwd=case_dir, env=_child_environment(output), kind='chromium')
        endpoint = profile / 'DevToolsActivePort'
        while not endpoint.is_file():
            self._check(case)
            if self._chromium.returncode is not None:
                raise ValueError('Owned Chromium failed to start')
            await asyncio.sleep(.05)
        lines = _ordinary(endpoint).read_text().splitlines()
        if len(lines) != 2 or not lines[0].isdigit() or not 0 < int(lines[0]) <= 65535 or not lines[1].startswith('/devtools/browser/'):
            raise ValueError('Owned Chromium endpoint is invalid')
        self._cdp = 'http://127.0.0.1:' + lines[0]
        self._case = case

    async def _operation(self, case, *, turn=None):
        self._check(case)
        await self._ensure_case(case)
        plan = self._plans[case]
        name = 'turn-' + str(turn['ordinal']).zfill(2) if turn else 'readback'
        directory = self._case_dir / name
        directory.mkdir(mode=0o700)
        config = {'case_id': case, 'project_id': plan['project_id'], 'owner_id': plan['owner_id'],
            'language': plan['language'], 'frontend_origin': self._origin,
            'interview_path': '/memoir/interview/' + plan['project_id'], 'cdp_origin': self._cdp,
            'playwright_module': self._config['playwright_module'], 'output_dir': str(directory),
            'receipt_path': str(directory / 'receipt.json'), 'max_requests': self._config['max_requests'],
            'public_asset_urls': self._config['public_asset_urls'], 'api_paths': _api_paths(plan['project_id']),
            'timeout_ms': max(1, int(self._remaining(case) * 1000)), 'turn': turn,
            'expected_api_fixture': 'owned-fifty-armed-api' if self.turns_enabled else 'owned-fifty-readback-only'}
        config_file = directory / 'worker-config.json'
        config_file.write_text(json.dumps(config))
        config_file.chmod(0o600)
        if _sha(_ordinary(self._script)) != hashlib.sha256(BROWSER_SCRIPT.encode()).hexdigest():
            raise ValueError('Owned browser worker source hash changed')
        worker = await self._spawn([self._config['node_executable'], str(self._script), str(config_file)],
            cwd=directory, env=_child_environment(Path(self._config['output_root'])), kind='browser_worker')
        try:
            await worker.wait()
            self._check(case)
            receipt_file = _ordinary(directory / 'receipt.json')
            if receipt_file.stat().st_size > 15_000_000:
                raise ValueError('Browser receipt exceeds bounded output size')
            receipt = json.loads(receipt_file.read_text())
            if (receipt.get('case_id') != case or receipt.get('project_id') != plan['project_id']
                    or receipt.get('e2e_passed') is not False or not isinstance(receipt.get('views'), list)):
                raise ValueError('Browser receipt identity differs')
            for view in receipt['views']:
                dom_hash = hashlib.sha256(json.dumps(view['dom'], ensure_ascii=False,
                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()
                if dom_hash != view.get('dom_sha256'):
                    raise ValueError('Browser DOM receipt hash differs')
                candidate = directory / view['screenshot']['path']
                png = _png_receipt(candidate, directory)
                if png['sha256'] != view['screenshot']['sha256'] or png['bytes'] != view['screenshot']['bytes']:
                    raise ValueError('Browser screenshot hash differs')
                view['screenshot'] = {**png, 'path': str(candidate.relative_to(Path(self._config['output_root'])))}
            receipt.update(run_id=self._session.run.run_id, source_revision=self._session.run.source_revision,
                           api_receipt=self._api.receipt(), producer='native_owned_playwright_live_frontend')
            self._observations.append(receipt)
            return deepcopy(receipt)
        finally:
            await self._stop('browser_worker', worker)

    async def observe_case(self, case_id):
        if self._busy or case_id in self._observed_cases:
            raise ValueError('Browser observation cannot overlap or repeat a case')
        self._busy = True
        self._observed_cases.add(case_id)
        try:
            async with asyncio.timeout(self._check(case_id)):
                receipt = await self._operation(case_id)
                return receipt
        except BaseException as error:
            self._record_failure(case_id, None, error)
            raise
        finally:
            self._busy = False
            await self._close_case()

    async def turn(self, case_id, ordinal, text):
        if not self._config.get('allow_browser_turns', False):
            raise ValueError('Browser turns require explicit separate admission')
        if (self._busy or type(ordinal) is not int or not 1 <= ordinal <= 50
                or type(text) is not str or ordinal != self._turn_ordinals.get(case_id, 0) + 1):
            raise ValueError('Browser turns must be single-owner and sequential')
        self._busy = True
        try:
            async with asyncio.timeout(self._check(case_id)):
                await self._ensure_case(case_id)
                expected = self._api.arm_turn(case_id, ordinal)
                if expected['text'] != text:
                    raise ValueError('Only the exact original admitted input is allowed')
                receipt = await self._operation(case_id, turn={'ordinal': ordinal, 'text': text,
                    'allowed_texts': expected['allowed_texts']})
                if (receipt['status'] != 'observed' or not all(receipt.get('checks', {}).get(key) is True
                        for key in ('ui_form_submitted_once', 'ui_original_text_visible', 'ui_new_reply_visible'))):
                    raise ValueError('Original UI form submission was not observed')
                result = await self._api.wait_turn(case_id, ordinal)
                reply = result.get('reply')
                shown = receipt.get('views', [{}])[0].get('dom', {}).get('assistants', [])
                if (type(reply) is not str or not shown or not _visible_reply(reply)
                        or _visible_reply(reply) != _visible_reply(shown[-1])):
                    raise ValueError('Actual runtime reply differs from the observed browser DOM')
                self._turn_ordinals[case_id] = ordinal
                return result
        except BaseException as error:
            self._record_failure(case_id, ordinal, error)
            await self._close_case()
            raise
        finally:
            self._busy = False

    def _record_failure(self, case, ordinal, error):
        self._observations.append({'schema_version': 'memoir-fifty-browser-observation/1',
            'case_id': case, 'ordinal': ordinal, 'status': 'incomplete',
            'failure_type': type(error).__name__, 'failure': 'Owned browser operation did not finish',
            'screenshots_verified': False, 'e2e_passed': False})

    def receipt(self):
        return {'schema_version': 'memoir-fifty-browser-producer/1',
            'run_id': self._session.run.run_id, 'source_revision': self._session.run.source_revision,
            'closed': self._closed, 'allow_browser_turns': self._config.get('allow_browser_turns', False),
            'original_turn_submission': 'browser_form' if self._config.get('allow_browser_turns') else 'direct_api_not_browser',
            'observations': deepcopy(self._observations), 'cleanup': deepcopy(self._cleanup),
            'startup_requests': deepcopy(self._startup_requests),
            'startup_request_cap_per_case': 60,
            'processes_remaining': len(self._processes), 'api': self._api.receipt(), 'e2e_passed': False,
            'cleanup_complete': self._closed and not self._processes and self._api_cleanup_complete,
            'request_cap_per_operation': self._config['max_requests'],
            'maximum_operations_per_case': 51 if self._config.get('allow_browser_turns') else 1}

    async def close(self):
        if self._closed and not self._processes and self._api_cleanup_complete:
            return
        self._closed = True
        try:
            await self._close_case()
        finally:
            await self._join_cleanup(asyncio.create_task(self._api.close()))
            self._api_cleanup_complete = True
