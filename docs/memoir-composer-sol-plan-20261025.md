# Composer GPT-5.6 Sol selection: availability and comparison plan

The author explicitly selected **GPT-5.6 Sol for memoir-composer**. That choice
does not authorize another model, serving activation, a new credential/access
grant, paid API fallback, prompt publication or renewed live calls. No coding
agent model was changed. This document records an availability blocker, not a
working or measured Sol deployment.

## Observed route and concrete blocker

Read-only inspection on October 25 found:

- The active `llm-provider-litellm-1` container mounts
  `/Users/bohuihan/llm_provider/config.yaml`; its SHA-256 is
  `416c9ef816942cd2b47ab1e0b0c9712f837cf5ad1d18a773c12eaf155894f5e4`.
- The configured composer alias `memoir-luna-low` targets
  `openai/gpt-5.6-luna` through the existing codex-lb subscription endpoint,
  with requested low effort. It is **not Sol**.
- No Sol-named target or alias exists in that gateway configuration. Wildcard
  OpenCodex/OpenRouter routes are different providers with unverified model,
  entitlement and cost; they are not substitutes for the requested model.
- An authenticated read-only `GET /v1/models` using the existing Memoir consumer
  credential returned HTTP 200 and only `gpt-5.6-luna-pooled`,
  `legal2ai-luna-low`, `memoir-luna-low`, `gpt-5.6-luna-memoir-low`,
  `gpt-5.6-luna-memoir-high` and `gpt-6-astra`. It advertised no
  `gpt-5.6-sol` or other Sol-named route.
- The bounded lane transport has no reviewed Sol model/token-bound entry. An
  arbitrary model setting is rejected before dispatch. That guard was not
  weakened to make a nonexistent route appear usable.

**There is no verified exact Sol route available to the current Memoir consumer.**
No Sol generation was dispatched, so there is no observed served Sol model,
effective effort, successful durable Sol result or Sol latency measurement.
The catalog establishes current advertised access, not universal provider
availability. No provider account database, private session archive or story
trace was read to discover an alternate account/key.

The smallest prerequisite is an existing, authorized subscription route that
actually targets GPT-5.6 Sol and is usable by the Memoir consumer, with its
model/effort enforcement, context/output limits, retry/fallback behavior and
cost/entitlement documented. An authorized provider owner must supply or approve
that route; this task cannot create an access grant or silently use another key.
If providing it requires a gateway/security change, that change requires a
separate concrete authorization. No new subscription or paid commitment is
proposed. Sol marginal cost is currently **unknown**, not inferred from Luna's
configured zero token prices.

## Phase scope and configuration decision

The desired model scope is **composer prepare, draft and review**, including
bounded repairs and resumed reviews. Drafting and review remain separate calls.
Eligible deterministic short-batch preparation still uses zero model calls.
Policy, collector, extraction, memory context, generic structured proposals,
story-game scene/brief generation and their current models remain outside this
selection. A separate paid literary judge remains unauthorized.

Inspection found that the legacy
`MEMORY_SPARK_MEMOIR_COMPOSER_MODEL` variable is also used by timeline lanes,
generic `managed_json_request` calls and story-game work. Changing it globally
would therefore violate the requested phase scope. It was left unchanged.

Once an exact authorized route is supplied, implement and test an isolated
composer-phase selection used consistently by `composer_call`/composer lane
budgets, canonical content/checkpoint fingerprints, the composer runtime and
worker dispatch. Preserve the legacy setting for unrelated consumers. The
selected model must be bound to the current request and must fail closed on an
unavailable/mismatched route; no retry may fall back to Luna. Review Sol's
token/context contract before admitting it to the bounded transport, retaining
complete sources and all existing size/privacy/proof gates. Do not lower input
quality or truncate originals merely to fit an assumed model window.

No runtime model/default/allowlist, Compose setting, serving environment or
provider configuration was changed in this follow-up. Shipping a fake alias or
an unusable default would not fulfill the selection. Phase-isolation code and
its TDD worker/SQL tests remain dependent on the concrete route information.

## New matched Sol experiment — proposed, not authorized

The earlier Luna baseline/candidate receipts and failed-quality comparison stay
immutable. They do not establish a like-for-like Sol speedup. The pending older
16-submission candidate-only proposal is insufficient to establish a matched
Sol baseline and must not be treated as approved or silently reset.

After route, prompt-publication and budget prerequisites are separately resolved:

1. Freeze the same six bilingual checkpoint inputs, author scope, saved-draft
   restart at checkpoint 10, withdrawal/empty controls, exact published pins,
   strict version-2 review, source/privacy/SQL gates and
   [manual craft rubric v1](memoir-composer-literary-rubric-v1.md). Record hashes
   before dispatch. Hold the exact Sol route, effective effort, source windows,
   cache policy and all quality behavior constant between arms.
2. Prepare a reviewed **quality-repaired Sol baseline** with the original model
   batch-preparation path, and a matched Sol candidate with only the lossless
   preparation fast path enabled. Use an isolated task-owned source variant,
   not a global service setting. Pin both actual source heads/diffs. This
   measures the preparation optimization under Sol; it is not a measurement of
   the old production main or the isolated effect of changing Luna to Sol.
3. Use fresh disposable SQL for each arm, each arm's own prior prose and actual
   saved-draft restart, the same canonical application/worker path and durable
   reader checks. No production data, migration or browser/deployed-worker
   claim is involved. Stop on an unexpected model, route, fallback, cost or
   entitlement. Record configured target separately from observed response
   model/provider provenance; opaque internal attempts remain explicitly opaque.
4. Apply hard semantic/privacy/persistence gates first. Record craft evidence
   and stage-specific scores separately, blinded where practical. The new craft
   rubric was added after the historical Luna comparison; any retrospective
   Luna assessment must be a new sidecar, not rewritten historical acceptance.

Recommended bounded request:

| Arm | Nominal application submissions | Repair reserve | Hard maximum | Elapsed cap |
| --- | ---: | ---: | ---: | ---: |
| Repaired Sol baseline, model preparation | 18 (6 prepare + 6 draft + 6 review) | 6 | 24 | 30 minutes |
| Matched Sol candidate, eligible host preparation | 12 (6 draft + 6 review) | 6 | 18 | 30 minutes |
| Total new experiment | 30 | 12 | **42** | **60 minutes total** |

Use zero paid judges, no additional historical Luna baseline calls, at most
120 seconds per submission (bounded by the arm's remaining time), and the
existing reviewed input/output caps or lower verified Sol limits. Count every
observable provider submission, retry, repair and failover. Preparation fallback
uses the same arm cap. Cancellation, quota exhaustion and failed/censored
checkpoints remain in the denominator; completion is not guaranteed by a cap.

The historical baseline exhausted 24/24; the historical candidate used 14/24,
leaving ten unused. Those ten are untouched and do not automatically transfer
to this new model/experiment. If the user explicitly carries them forward, the
42-submission plan needs 24 new baseline submissions plus eight candidate
submissions beyond that remainder: **32 additional**, with new deadlines.
No such approval has been received. A dollar estimate and actual dispatch
remain blocked until the exact existing-provider Sol route/cost is verified.

Do not combine historical Luna timings with these future Sol rows to claim a
model or optimization percentage. A same-contract Luna/Sol model comparison
would require another explicitly approved matched arm; it is not included here.
The original incomplete Chinese-15 Luna row stays censored.
