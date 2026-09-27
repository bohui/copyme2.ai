# Place Photo Research — a directly usable Codex skill

Version 1.0.0 · 26 September 2026

**No period mentioned → present-day photos.** A specified historical period is preserved. The skill uses Codex's native web search for discovery, its available reading tools for source inspection, and the bundled Python helper for date normalization, evidence checks, permitted local downloads and reports.

It does not require the memoir app, a custom tool host, database, MCP server or an additional Serper/SerpApi account. It does require your usual Codex access, Python 3.10+, and permitted network access. Pillow is needed for downloading/validating image files.

## Install into a project

From the project root, after saving the package as `~/Downloads/place-photo-research-codex.zip`:

```bash
mkdir -p .agents/skills
unzip -n "$HOME/Downloads/place-photo-research-codex.zip" -d .agents/skills

python3 -m venv .venv-photo-research
.venv-photo-research/bin/python -m pip install \
  -r .agents/skills/place-photo-research/requirements.txt

export PHOTO_RESEARCH_PYTHON="$PWD/.venv-photo-research/bin/python"
codex --search --sandbox workspace-write --ask-for-approval on-request
```

`unzip -n` deliberately does not overwrite an existing installation. For upgrades, review/replace the old skill intentionally rather than merging blindly. Do not check the virtual environment or private research outputs into Git; add appropriate entries to your project's `.gitignore` yourself.

Then invoke inside Codex:

```text
$place-photo-research Find 3 photographs of Chengde, Hebei, China in the 1980s. Prefer streets and everyday life. Save permitted images and a source-backed report under ./photo-research/chengde-1980s-01.
```

For a current-mode request, no date is needed:

```text
$place-photo-research Find 3 photographs of Chengde, Hebei, China. Save the permitted images, evidence and a local gallery under ./photo-research/chengde-current-01.
```

Use `/skills` or type `$` to discover/select the skill. Codex's current documentation says local skill changes are detected automatically; restart Codex if the skill does not appear.

## Optional user-wide installation

Install the same folder under `~/.agents/skills/place-photo-research` to use it across repositories. Do not install duplicate same-name copies globally and in the same repository. Point `PHOTO_RESEARCH_PYTHON` at the absolute path of a suitable environment with the requirements installed.

## Search and permissions

`--search` enables live web search. Alternatively, deliberately configure the top-level `web_search = "live"` in your Codex configuration; this package does not edit that file. The live option is useful for present-day discovery, but a live search result still does not prove a photo's capture date.

Native web search and network access for shell/Python commands are separate. Your Codex environment may request network approval for the downloader, or an administrator may disallow it. Use the normal narrow approval mechanism; do not disable sandboxing. When a source cannot be accessed or downloaded, the skill keeps an honest link/evidence result instead of claiming a saved file.

The HTML helper uses direct connections with no cookies, credentials or proxy inheritance. Environments requiring an approved HTTP proxy may block it. Use an already approved host tool or keep the result as a link; do not circumvent the proxy or security policy.

## What the skill does

1. Normalises the requested place, subject and period. Missing period becomes current in code, using a configurable 24-calendar-month preferred capture window.
2. Searches in appropriate languages and finds image pages, archives and albums through native web search.
3. Inspects original pages and image-specific captions; expands promising collections within limits.
4. Saves place/date/rights/access evidence and unresolved candidates.
5. Runs the helper's conservative audit and downloads only eligible items.
6. Builds `manifest.json`, `report.md` and a local-only `gallery.html`.

A title saying 1983 does not date every item in an album. Recent uploads do not prove recent scenes. Unlicensed matches remain in the report without automatic image downloads or remote hotlinks. The skill does not generate photographs or claim that external references are the user's family pictures.

## Package layout

```text
place-photo-research/
  SKILL.md
  README.md
  requirements.txt
  agents/openai.yaml
  scripts/photo_research.py
  references/record-format.md
  references/source-strategy.md
  examples/prompts.md
  examples/candidate-template.json
  tests/test_photo_research.py
  VALIDATION.json
  test-results.txt
  SHA256SUMS
```

The `SKILL.md` references the files directly. There are no placeholder application tool names to implement.

## Helper commands

```bash
PY="$PHOTO_RESEARCH_PYTHON"
SKILL_DIR="$PWD/.agents/skills/place-photo-research"
RUN_DIR="$PWD/photo-research/chengde-current-01"

# Codex normally performs these steps for you.
"$PY" "$SKILL_DIR/scripts/photo_research.py" init \
  --place "Chengde, Hebei, China / 河北承德" --out "$RUN_DIR"

# Record each native query before running it; this is a workflow audit log.
"$PY" "$SKILL_DIR/scripts/photo_research.py" log \
  --run "$RUN_DIR" --kind search --detail "承德 现在 街景"

# After Codex writes actual evidence and candidate records:
"$PY" "$SKILL_DIR/scripts/photo_research.py" audit --run "$RUN_DIR"
"$PY" "$SKILL_DIR/scripts/photo_research.py" download --run "$RUN_DIR"
"$PY" "$SKILL_DIR/scripts/photo_research.py" report --run "$RUN_DIR"
```

`--help` describes each command. `inspect` is a permitted-HTML fallback and requires an explicit `--access-permitted` attestation. It does not certify copyright permission.

The Python script is not an autonomous search agent. It deliberately leaves query choice and page interpretation to Codex. `examples/candidate-template.json` is an incomplete blocked template, not a discovered image; do not report it as a result.

## Result folder

```text
photo-research/chengde-current-01/
  request.json
  candidates.json
  evidence.jsonl
  search_log.jsonl
  manifest.json
  report.md
  gallery.html
  pages/       # created only when the HTML inspector is used
  images/      # created only after a successful permitted download
```

Open `gallery.html` locally or read `report.md`. The manifest distinguishes discovery, date matches, rights blocks, network failures and actual downloaded paths/hashes. Images are content-addressed by SHA-256. Existing originals are preserved; a later rights failure stops presenting that image in the refreshed report but does not silently delete user files.

## What has and has not been tested

The package includes offline unit/integration tests for temporal rules, evidence references, date/place/rights gates, public-network URL/DNS checks, robots decisions, format/decode checks, budget logging, local reports, hash deduplication and resume behaviour. Network responses in integration tests are mocked; synthetic image bytes are generated in memory.

Run them:

```bash
"$PHOTO_RESEARCH_PYTHON" -m unittest discover \
  -s .agents/skills/place-photo-research/tests -v
```

**Not verified:** live installation or activation in your Codex account; native search relevance; end-to-end real archive downloads; every website's access terms; independent authenticity of photo metadata; legal title/licensing; China/Australia production deployment. See `VALIDATION.json` for the precise local test result.

The helper enforces consistency of supplied evidence, not the truth of that evidence. Its records are editable by the same local agent/user, so it is not a hardened permission boundary. Its query budget applies to correctly logged actions, not unlogged native tool calls. Keep Codex sandbox/approvals enabled and review external source claims.

Local downloads do not automatically approve paid-app display, ebook export or printing. Those uses require their own review. No rights email, licence purchase, source-site upload or publication is performed by this skill.

## Official documentation

Checked 26 September 2026:

- Skills format, local paths and invocation: `https://developers.openai.com/codex/skills`
- Live web-search configuration: `https://developers.openai.com/codex/config-basic`
- CLI flags: `https://developers.openai.com/codex/cli/reference`
- Approvals and sandboxing: `https://learn.chatgpt.com/docs/agent-approvals-security`

OpenAI currently redirects some older developer-documentation URLs to its official ChatGPT Learn documentation. Use current documentation over stale installation-path examples.
