# Langfuse prompt structure and usage audit

Status: code and prompt composition refactor on 18 October 2026. The registry
now manages 80 prompt sources after removing five unused browser prompts and
adding six shared components. The [individual usage audit](Langfuse_Prompt_Usage.md)
classifies every name and records its consumer. Registration alone does not
establish a model invocation or live traffic.

## Removed workflows

The application now executes conversations through `run_lifetime_turn`, with
canonical collector, lane and job contracts. The following retired code has
been removed before pruning its prompts:

- Combined journalist/marker prompts, private workspace extraction and focused
  marker recovery, legacy timeline marker sanitization, and synthetic loop traces.
  None had an application caller. The canonical source-clause and user-veto
  parsers are retained because MemoryEvent validation and conversation
  attribution still import them.
- The unused collection-task prompt builder and organiser-task prompt builder.
  The current organiser uses bounded leaf/merge jobs.
- The uncalled collector retry loop. Canonical governed execution owns retries.
- Missing-file fallback instructions for the removed marker workflow.
- The old worker branch for unbounded timeline/composer jobs; the worker now
  requires the canonical page protocol before dispatch.
- The noncanonical composer transport and draft selection. Composer calls now
  require a canonical lane and select the canonical draft instructions.
- The old direct-collector and conversation comparison profiling modes, one-time
  Issue 6 publisher/evaluator setup, and completed prompt-name migration script.
  The streaming adapter still used by the canonical controlled profiler was moved
  into that profiler. `scripts/profile_first_reply.py first-turn` is retained:
  it measures the current HTTP conversation path without retired prompt builders.
- The ignored `deprecated-app-auto-localization` bundle and its stale registry
  record. A recovery copy is outside the source tree under `var/retired-skills/`.
  Current application localization remains in the app.

Collector prompt configuration now accepts `compact-v1` (the default) and
`two-lane-v1`. The unsupported `legacy` value is rejected. Container copies,
source mounts, exporter aliases and examples no longer refer to the retired
journalist file.

## Removed prompt names

The 28 names below lost their consumers and were removed from the registry,
repo artifacts and Memoir Langfuse project. All 29 remote versions were backed
up first in `var/langfuse-retired-workflows-backup-20261018T002423Z.json`.
This first cleanup left 79 names. The subsequent code-path audit removed five
browser templates that never reached the model, then introduced six shared
components. Remote names now exactly match the 80 retained registry names.

| Retired group | Names below `memoir/` |
| --- | --- |
| Full journalist | `interview/journalist` |
| Collection task markers | `interview/collection-task/base`, `interview/collection-task/with-sources` |
| Old conversation assembly | `interview/breadth/{default,checkpoint,pending-plural,pending-singular}`, `interview/response-contract`, `interview/photo/{header,guidance}` |
| Old collector retry | `interview/collector-repair` |
| Old marker extraction | `memory/profile-intake`, `memory/marker/{location-identity,place-grounding,family-context}` |
| Old workspace recovery | `memory/workspace/{canonical,extraction,family-focused,family-recovery,place-recovery,timeline-claim,timeline-recovery}` |
| Fallbacks | `memory/fallback/{author-timeline,family-tree,place-journey}` |
| Old composer/organiser | `composer/draft`, `composer/organiser-task` |
| Legacy timeline marker | `skills/memoir-author-timeline/legacy-marker` |

The five earlier `memoir/issue6/20261008-v1/prompts/*` copies were already
removed after verifying their text is preserved as version 1 of stable names.
The old Issue 6 datasets still exist alongside their stable copied datasets;
this prompt cleanup does not remove dataset or experiment history.

## Remaining consumers

Normal application requests read checked-in prompt artifacts and validate their
numeric Langfuse version receipts. They do not fetch Langfuse text at request
time. This is a code-path audit; actual frequency needs runtime traces.

| Group | Count | Consumer |
| --- | ---: | --- |
| `interview` | 18 | Canonical collector/governed execution, shared guidance, strategy selection and greetings. Browser instruction construction and its generated module are removed. |
| `memory` | 13 | Canonical timeline/two-lane extraction, shared grounding, summary, attribution, and bounded lane context. |
| `composer` | 11 | Canonical preparation/draft/review, batch composition, organiser leaf/merge jobs and shared job policy. `index` is an older compatibility/benchmark seam, not a normal canonical phase. |
| `research` | 1 | Historical discovery provider, when that feature is enabled. |
| `speech` | 3 | Speech instructions by locale or default voice. |
| `skills` | 24 | Six runtime components, eight evaluation-only inputs and ten packaged/manual skill guides. Package installation, links and cache hashing do not prove model use; see each row in the individual audit. |
| `evaluation` | 10 | Live-skill probes and five-case/trajectory judges, only when those evaluation commands run. |

The `skills` and `evaluation` groups have deliberate callers outside an ordinary
storyteller turn. They remain managed. A disabled production binding, such as
story-game execution, does not make its active evaluation harness unused.
The detailed audit finds 51 runtime or conditional/shared runtime sources,
18 evaluation-only inputs, ten packaged/manual guides and one compatibility
index. This replaces the earlier, overly broad claim that every registered
prompt was actively used by the application.

## Shared composition in code

`apps/api/prompt_composition.py` is the common builder used by runtime loaders,
dataset evaluations, and export validation. Templates refer to a curated set of
repo components using `{{prompt:component_name}}`; they cannot read arbitrary
paths. Both templates and components remain independently versioned in Langfuse.
The checked-in receipts pin all source versions. Evaluation preflight records
component versions/hashes and the compiled SHA-256.

| Task templates | Shared sources now loaded once from their authority |
| --- | --- |
| Timeline and derived timeline | Author-timeline skill, service contract and grounding rules |
| Default collector and three strategies | Collector behavior guidance |
| Three strategy variants | Immediate selection/work-hint rules |
| Canonical draft and review | Narrative-enrichment reference; review also includes the editorial-review reference |
| Two lane-context locales | Shared evidence/privacy context |
| Four organiser phase/locale variants | Shared prefix and reference/size policy |

All fourteen compiled task inputs remain byte-for-byte identical to their
previous inputs. The source refactor removes 57,061 copied characters. Updating
a component through Langfuse and exporting its new pin now reaches every
consumer through this builder.

The code audit also found two implementation issues. The browser constructed
instructions that the backend discarded in favour of original narration; that
construction and five prompts are removed. The organiser duplicated the lane's
HTTP body initializer and omitted `_after_send`; it now uses the shared
initializer while retaining its distinct typed job fence. These changes address
execution code as well as the storage of prompt text.

The timelines are two schemas in one extraction lane, the strategies are
variants in one collector, and draft/review are deliberate phases over the same
canonical events. Their shared policy does not imply another execution of the
same work. The older `composer/index` compatibility path is explicitly listed
separately; it must not be presented as current canonical traffic.

## Stable naming proposal

Names describe a job and contain no issue number, release date or extra
`prompts` segment. Langfuse numeric versions record revisions. Keep datasets at
`memoir/evaluation/<suite>` and use dataset versions and experiment runs for
history.

```text
memoir/
  interview/
  memory/
  composer/
  research/
  speech/
  skills/<skill>/instructions
  skills/<skill>/references/<name>
  evaluation/
```

The `/instructions` leaf remains a possible navigation change for skill roots.
The current refactor preserves existing active names and removes copied policy
through shared composition. Runtime/evaluation ownership is recorded separately
from the Langfuse folder used to navigate a source.
