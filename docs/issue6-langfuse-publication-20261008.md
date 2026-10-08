# Issue 6 Langfuse asset publication

The reviewed semantic fixture and application evaluator are already in Git.
They do not create managed Langfuse evaluators. This publication command exports
those synthetic cases, exact application instructions and managed definitions
for the existing local project `memior` (`cmut9t75w00071z02n8bdv7it`).

Status on 2026-10-08: the user explicitly authorized asset publication. The
export and offline boundary checks are ready. Actual publication and server
read-back are blocked because the existing project credential file is not
available in this execution environment. No asset, experiment, trace or score
has been published by this change. A request for the file path remains pending;
key values must not be sent in chat, logs or artifacts.

## Assets and boundaries

| Asset | Count | Version / purpose |
| --- | ---: | --- |
| Synthetic datasets | 4, with 28 items | Reviewed `20261008-v1` fixture and its SHA-256 |
| Text prompts | 5 | Timeline and composer prepare/index/draft/review instructions, exact application bytes |
| Managed code evaluators | 4 | One definition per dataset dimension; staged until callback and review |
| Evaluation rules | 4 | Disabled; each scoped to its dataset, experiment roots and `issue6-synthetic-evaluation` |

Names use `memoir/issue6/20261008-v1/`. Prompts receive only the
`issue6-evaluation` label. The application still loads its reviewed Git builders.
No production label, application configuration, worker, service, provider route,
database migration or entitlement is changed. This is a bounded first group of
assets, not a migration of every repository instruction or dataset.

Each dataset item retains its input, proposed expected output, language/pair
identity, rubric and content hash. Stable item IDs allow recovery from partial
uploads. Source, validator, stage vocabulary, prompt instructions and schemas
are pinned. A changed reviewed source requires a reviewed publication version.

The publisher verifies the exact project before any asset operation, preflights
all conflicts before writes, creates only absent matching names/IDs and reads
back every payload. It stops on conflicting assets, duplicate evaluator names,
unexpected dataset items, unsupported APIs, HTTP errors or unknown outcomes.
It never updates/deletes existing assets or silently retries a create. An
explicit resume first reads existing state; matching assets are reused.

The receipt records dataset item timestamps and the maximum item timestamp for
the hosted snapshot, dataset/item hashes, prompt versions, evaluator IDs/versions
and code hashes, and disabled-rule filters. Missing server timestamps remain
unavailable. HTTP errors omit bodies and authentication. The client uses only
the fixed loopback origin, with proxies and redirects disabled.

## Evaluation contract

Timeline managed code consumes `issue6_application_receipt` from server-owned
observation metadata. The importable `application_receipt` helper calls the
reviewed public `score_events` function, which uses the application's extraction
validator and retained proposals. It does not duplicate that validator in the
managed standard-library runtime.

A future callback must obtain successful worker completion and exact original
source-version coverage from the application. The managed definition requires
those facts and compares receipt input, output, expected output and item
provenance against the selected experiment. Missing, incomplete or stale
receipts return TEXT `unavailable`; they cannot earn numeric credit. An actual
completed empty proposal can earn the applicable code scores. Empty placement
gold remains `not_applicable`. This metadata is an application attestation, not
a cryptographic signature, and must never be supplied by the model.

Factual entailment remains `human_review_required`. Chapter transitions,
chronology, natural prose and bilingual equivalence also require review against
the proposed rubric. The staged definitions do not implement those semantic
judgments, create model judges or certify acceptance. No actual evaluator
dispatcher execution has been verified on the local Langfuse server.

## Reproduction

Use Python 3.11+ and the declared core/test dependencies. The verified task
environment has pytest 9.1.1. No new shared package installation is required.

```sh
python -m pytest -q tests/test_issue6_langfuse_publication.py tests/test_issue6_semantic_evaluation.py
python scripts/issue6_langfuse_publication.py --export /tmp/issue6-publication.json
```

After the existing credential-file path is supplied, publication uses only
`LANGFUSE_COPYME2AI_PUBLIC_KEY` and `LANGFUSE_COPYME2AI_SECRET_KEY` privately from
that file, with interpolation disabled:

```sh
python scripts/issue6_langfuse_publication.py \
  --export /tmp/issue6-publication.json \
  --publish --credential-file /path/to/existing/provider.env \
  --receipt /tmp/issue6-publication-receipt.json
```

Do not substitute another project/account, create credentials, enable rules or
start experiments to resolve missing access. Never use the credential file as
an export or receipt destination.

TDD receipts are retained in the task artifact directory for export creation,
missing-output handling, application receipt propagation, project selection,
idempotent publication, missing-key handling and credential-file preservation.
Final focused validation: **30 passed, zero failures/errors/skips**. Of these,
17 are the existing controlled semantic regressions and 13 exercise publication
and the managed function contract. HTTP responses use an explicitly labeled
external API double; managed code executes through Node locally. These results
are not server publication, hosted dispatcher, live model or human calibration
evidence. Real server health was observed as HTTP 200 / Langfuse 4.21.0 only.

Live experiments still require the separately reviewed Issue 14 provider
binding/accounting and numerical budget, an application/worker callback, native
synthetic execution and a named calibrated human reviewer. The complete Issue 6
acceptance map, historical failures and operator deferral remain unchanged.

Langfuse's [code-evaluator contract](https://langfuse.com/docs/evaluation/evaluation-methods/code-evaluators)
requires a configured dispatcher for hosted execution and a standard-library
runtime. The definitions remain disabled until that runtime and callback are
verified within the authorized test environment.
