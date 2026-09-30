# CopyMe2 — Progressive Memoir Composer

**Version 1.0.0 • Created 30 September 2026**

A reusable skill for the CopyMe2 memoir harness: organise memories and chat history into a chronological main storyline, give chapters meaningful titles, compose source-backed prose with eligible personal pictures, and enrich it over later runs. **Every chapter has a hard maximum of 7,000 words.**

The first output can be small. More context should improve an existing memoir, not create a new unrelated book each time.

## The two primary triggers

| Application event | Result |
|---|---|
| Five free primary Memory Sparks are complete | A focused **sample chapter** if material centres on one period, or a **sample storyline + proposed chapter outline** if it spans several periods |
| Storyteller says they are basically finished and ready to compose | A chronological **formal memoir draft**, with chapters, photographs, evidence references and review metadata |

`new_context` and `manual_revision` support later enrichment. “Basically finished” does not require every period of life to be covered. The application records consent/authorisation and the storyteller's readiness confirmation; the model must not infer permission from silence or a score.

## Install in Memoir

This repository-owned skill lives at:

```text
skills/memoir-composer/SKILL.md
```

From the Memoir repository root, package it into the managed API and Codex
worker images and recreate those services with:

```sh
SKILLS="memoir-composer" make install_skill
```

This is a Memoir repository install, not a personal Codex-home installation.
The command makes the bundle available to the worker; it does not by itself
add the application's composition trigger or persistence adapter.

Then explicitly invoke:

```text
$memoir-composer

Use the authorised request.json snapshot for this project.
Read the packet, select the correct trigger mode, summarise the source material,
save a chronological outline, draft the supported content, attach only eligible
registered photographs, and validate every chapter against the 7000-word cap.
Preserve approved edits and save a progressive revision rather than overwrite them.
```

The bundle sets `allow_implicit_invocation: false`: dispatch it explicitly from
the application's composition event handler or your own request. It does not
run automatically just because it is packaged into the worker image.

For a custom harness such as your `advanced_aas`, load `SKILL.md` through its existing skill mechanism and map the logical capabilities in `references/runtime-contract.md` to your actual tools. No specific unverified framework method or endpoint is assumed.

## What is included

```text
memoir-composer/
├── SKILL.md                         Agent workflow and boundaries
├── README.md                        Installation and usage
├── TEST_REPORT.md                   Local test result and limitations
├── agents/openai.yaml               Optional Codex metadata
├── references/
│   ├── runtime-contract.md          Inputs, tools, persistence and output
│   ├── workflows.md                 Triggers, coverage and progressive updates
│   ├── editorial-and-length.md      Narrative rules and word counting
│   ├── editorial-review.prompt.md   Separate evidence-to-prose review pass
│   └── sources.md                   Baseline and official documentation
├── schemas/
│   ├── request.schema.json
│   └── draft.schema.json
├── scripts/
│   ├── memoir.mjs                   CLI: plan, count, validate, render
│   ├── lib.mjs                      Dependency-free guardrails
│   └── build-examples.mjs           Regenerate synthetic fixtures locally
├── tests/
│   ├── fixtures.mjs
│   └── composer.test.mjs
└── examples/
    ├── focused_trial/
    ├── broad_trial/
    ├── formal_memoir/
    ├── progressive_update/
    ├── protected_update/
    └── chinese_preview/
```

Each example folder includes an input packet, candidate draft, selected plan, validation report, reader draft, source summary and structured manuscript. Examples are deliberately brief and synthetic. The photo example uses a clearly identified **asset slot**; no real family photo is bundled or fabricated.

## Run the executable checks

Requirements: Node.js 22+ with full ICU and `Intl.Segmenter`. No npm dependencies or API keys are needed for the included utilities and tests. Use a current, security-patched runtime in deployment and keep its segmentation version consistent.

```sh
cd skills/memoir-composer
npm test
```

The bundled JSON examples contain the Node/ICU fingerprints from the build environment. On a different runtime, regenerate **only the synthetic examples** before running the following demonstration:

```sh
node scripts/build-examples.mjs

node scripts/memoir.mjs plan \
  --request examples/focused_trial/request.json

node scripts/memoir.mjs validate \
  --request examples/focused_trial/request.json \
  --draft examples/focused_trial/draft.json

node scripts/memoir.mjs render \
  --request examples/focused_trial/request.json \
  --draft examples/focused_trial/draft.json \
  --out-dir /tmp/copyme2-focused-preview
```

Use a new output directory for a changed run. The CLI refuses to overwrite differing files; replaying identical artifacts is allowed. If interrupted during file creation, rerun with the same inputs. Files remain staging artifacts until the host commits a complete manifest.

To count a text file independently:

```sh
node scripts/memoir.mjs count --file chapter.txt --locale en-AU
node scripts/memoir.mjs count --file chapter-zh.txt --locale zh-CN
```

For a chapter's authoritative count, validate its structured candidate so titles, captions, alternative text and sidebars are included. Counting a standalone body-text file alone is not the full chapter check.

Exit codes: `0` means the requested local operation passed; `2` means an invalid/blocked plan or draft; `1` means command/input/file execution failed. A zero validation result is **not** an editorial approval or a publishing permission.

## How a live composition run works

1. The host receives a confirmed event and freezes an authorised project snapshot.
2. The agent retrieves original chat/recording/diary content and source-linked memories; it builds a deduplicated event index.
3. `plan` checks the trigger and selects the preview or formal mode.
4. The agent summarises the evidence, saves a chronological outline, and writes chapter candidates with asset references.
5. A separate editorial pass checks whether the actual prose is supported by its cited sources.
6. `validate` enforces structural checks, source resolution, exact quotes, update protections and measured length.
7. `render` emits review-only Markdown/HTML/JSON. The host saves them with expected-revision and current-permission checks.
8. After user review, the existing app pipeline can build a PDF/EPUB edition. Publication and printing require separate approval.

The Node scripts do not call an LLM and cannot write a memoir by themselves. They supply deterministic controls around the agent's writing. This is intentional: model creativity must not control entitlements, approval state or access rights.

## Length policy

**Hard maximum:** 7,000 words per chapter, including title/subtitle, headings, prose, quotations, captions, credits, alt text, sidebars and visible notes.

**Soft planning ceiling:** 6,000 words. There is no minimum. Sample chapter and overview ranges are gentle defaults, not targets to pad toward.

**Chinese:** use locale-aware word segmentation, not spaces and not a silent conversion of 7,000 words to 7,000 characters. Reports include character counts too. The exact Node/ICU counter fingerprint is recorded. `Intl.Segmenter` is documented for locale-sensitive segmentation, including languages without spaces [S3].

If a chapter is too long, condense or propose a chronological split. Keep unused memories in the source/event ledger. Never truncate mid-sentence, discard source material, or make captions/appendices a loophole.

## Progressive persistence

Use stable chapter IDs and immutable source versions. Later runs send only changed chapter candidates and explicit unchanged chapter IDs; a full outline preserves the readable order. Event dispositions show what was included, deferred, unplaced or excluded.

Approved or human-locked chapters receive replacement proposals, not direct updates. A corrected source or revoked photo can block reuse even when old prose is protected. A lock never overrides privacy. An approved edition remains immutable; new evidence belongs to a new draft/edition workflow.

The provided fingerprint includes source/media content, policy, preferences, glossary version, previous chapter state and the counter runtime. The backend must still detect all changed sources, maintain dependencies, reject stale commits and deduplicate event delivery. The CLI does not implement your database or event bus.

## Integration status and limits

This bundle is installed in the Memoir repository under `skills/memoir-composer`
and is included by the repository skill packager. The current Memoir worker
still needs an explicit composition trigger and adapter bindings for retrieval,
media registry, model execution, workflow storage, source permissions and edition
rendering; packaging alone does not replace the app's existing preview or
organisation paths.

Automatic checks do not prove semantic entailment, title suitability, historical truth, complete event deduplication, legal rights or whether a memoir feels good to read. The package includes an editorial-review prompt for that separate pass and requires user review before release.

Neither the package nor its examples contacts a supplier, charges a customer, downloads external media, changes Figma or modifies the existing specification files. All product routes stay under the previously selected `copyme2.ai/memoir/*` namespace; `/voice/*` remains a different product.

Sources [S1]–[S3] and the project baseline are documented in `references/sources.md`.
