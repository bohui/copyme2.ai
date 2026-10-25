# Composer-only GPT-5.6 Sol routing

This delta follows the independently reviewed offline v3 head
`8533062ee4ba66c2d1cb7a7b5376896c4a2ed501`. It changes application routing and
tests, without changing managed prompt sources, review schema or SQL. The running
checkout, its bind mounts, containers, credentials and database were not changed.

## Selection and compatibility

`MEMOIR_COMPOSER_MODEL` defaults to the exact `gpt-5.6-sol` alias;
`MEMOIR_COMPOSER_REASONING_EFFORT` defaults to explicit `high`. They affect only
composer model preparation, drafting and separate review. Eligible lossless
preparation remains a host operation. The existing shared
`MEMORY_SPARK_MEMOIR_COMPOSER_MODEL` and effort settings retain their defaults and
consumers: timeline, policy and story-game planning. Collector/profile policies
also retain their own settings.

Selection is resolved for composer execution rather than changing a global
provider or collector default. Unknown aliases and invalid/blank effort fail
closed. Only low/medium/high effort is accepted; high is the selected default.
Compose's `:-` interpolation supplies these defaults for empty host variables;
an application process receiving an explicit blank value rejects it.
Existing reviewed Luna aliases remain available as explicit operator rollback
choices, never an automatic fallback. API and worker model disagreement rejects
the request before generation. A shared worker effort override cannot lower
composer high effort. Model and effort both enter composition/preparation
fingerprints, so their changes require new reviewed writing rather than reuse of
a cached composition. Changes to unrelated shared model settings do not
invalidate composer caches.

API, Codex worker and checkpoint worker receive both dedicated environment
settings through Compose. Existing running containers keep their current
environment and mounted sources because this task does not pull or restart the
serving checkout. Old API/new worker model disagreement fails closed; future
activation must update the code and dedicated settings together. This routing
delta requires no SQL migration. The earlier v3 quality change still requires
its separately documented schema/code/pin activation plan.

## Advertised route, not a generation measurement

Read-only inspection at **2026-10-25 09:37:22 UTC** used the existing Memoir
consumer key for `GET /v1/models` (HTTP 200). The catalog exposed `gpt-5.6-sol`.
The provider configuration SHA-256 was
`c105059b0f75082ddbe1746db024ab0c35bed620ebc38df7cde2e6eb642a88b2`.
The exact entry targets `openai/gpt-5.6-sol` at the existing codex-lb endpoint
reference, requests high effort, specifies zero outer retries and has no route
or router fallback entries. It declares 272,000 input/128,000 output capacity and
zero token prices for subscription spend tracking. The provider README states
this route uses the subscription pool with no paid OpenAI fallback. No new
credential, access grant, service or paid subscription was created.

These are configuration/catalog observations. The actual served upstream model,
effective effort, opaque pool account attempts and actual billing remain
unobserved without generation. Future receipts must retain those distinctions
and stop on an unexpected route or uncertain paid fallback. The application
still admits only its explicit reviewed model set and conservatively counts
serialized instructions, packet, schema and framing using UTF-8 bytes. Sol
retains at most 131,072 context, 98,304 input and 16,384 output, with at least
2,048 framing reserve and the existing total-window constraint. Sol is not
admitted by this change to timeline/profile lanes. No retries, concurrency,
timeouts or repair allowances were expanded.

## Evidence and pending work

TDD receipts are retained under ignored
`var/composer-response-optimization/20261025-sol-routing/`: initial canonical
selection failed on Luna, worker fallback failed, cache tests exposed the old
shared fingerprint, invalid configuration/budget cases failed, and Compose/live
runner tests failed before their corresponding changes. Green tests exercise
canonical and worker HTTP boundaries with controlled synthetic provider output,
including real disposable PostgreSQL admission, phase proofs and durable ready
state. They do not establish Sol semantic quality or latency.

The historical Luna baseline (24 submissions) and failed-quality candidate
(14 submissions) remain immutable. They are not a matched Sol comparison. The
new exploratory design remains six frozen bilingual checkpoints per arm, n=1,
24 baseline/18 candidate maximum including repair, 30 minutes per arm and no
paid judges, with the same v3 quality/craft gates on both arms and only lossless
preparation differing. No new Sol submissions have been made.

Source-only PR #133 at reviewed `1ea036011a75b34de3419e126c9b576715b5709a`
was marked ready. Its exact-head merge and the single authorized retry were
rejected by automatic approval review because the review prerequisite could not
be verified from the delegated report. The supported review-task reader also
returned `Codex app tool request failed`. Neither merge attempt executed; no
alternative route was used. Scoped publication remains paused. This delta needs
independent review before live work. Combined PR #132 remains draft
until matched live quality, fidelity, craft and persistence acceptance and final
independent review pass.

The expanded collector/canary check has 35 failures at both reviewed `8533062`
and this routing delta: identical failing test IDs and normalized reasons
(32 references to removed legacy methods and three retired noncanonical input
contracts). No new failures were added or assertions weakened; raw JUnit/logs
and the comparison are retained separately. An incomplete cached-photo fixture
also failed at reviewed `8533062`; its setup now obtains a complete reviewed
bundle through canonical composition before asserting unchanged-photo reuse
with zero further model calls. The composer effort expectations were updated
from the superseded shared low default to dedicated high, retaining timeline
low and explicit blank rejection checks.

Final validation uses controlled synthetic providers, not live Sol:

| Check | Recorded result |
| --- | --- |
| Combined routing, v3 quality, SQL, privacy, restart and capacity cohort | 600 passed; 11 previously established cases deselected; one container-stop teardown error; command exit 1 |
| Affected attribution case rerun with unchanged fixture timeouts | 1 passed; normal teardown; exit 0 |
| Composer evaluation contract replays | 15 passed; 26 unrelated cases deselected |
| Prompt governance | 31 passed |
| Node composer/progressive checks | 62 passed |
| Separate legacy collector/canary classification | Same 35 failures out of 38 at base and candidate; no added failures or changed normalized reasons |

The combined run's error is retained in full: the disposable PostgreSQL stop
command exceeded its ten-second deadline during teardown. A filtered inventory
then found no remaining disposable PostgreSQL containers, so no duplicate stop
was issued. The single affected case passed on rerun with its normal cleanup.
No product assertions or fixture timeouts were relaxed, and full-suite green is
not claimed. [Structured commands, source hashes and results](memoir-composer-sol-routing-20261025.evidence.json)
identify the evidence separately from the historical Luna measurements.

The ordinary production loader still rejects all three unpublished source
edits and both compiled draft/review paths. Offline tests use the repository's
explicit controlled-source adapter; no live dispatcher or publication check is
bypassed. This delta changes no managed source or receipt.

Ordinary repository inspection also found independent serving-checkout work at
local head `b9373804eac8069979c6d7dd3226bebe625649b5` (speech changes), with dirty
`.env.example`, `README.md`, lane-engine and lane-engine-test files. Those edits
admit GPT-5.6 Sol and GPT-6.1 Sol to shared lanes and suggest the legacy shared
setting. They were preserved and are excluded from this branch. Their owner and
loaded runtime state were not inferred. Coordinate the overlapping settings
before future activation; this task's reviewed intent remains composer-only
GPT-5.6 Sol. The older unique-content worktrees and the active task worktrees
remain available while review and live acceptance are pending.
