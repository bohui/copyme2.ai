# Memoir Pydantic AI benchmark

**AAS led the Mira comparison.** Pydantic AI cut runtime overhead relative to Codex and finished Atlas slightly sooner in the live sample. AAS passed five more live Mira cases than Pydantic AI and completed the queued burst sooner. The controlled SQL tests passed across the three runtimes.

The branch uses Memoir `6f196efd` with the benchmark fixture revision `eaae3434`. The native run used adapter commit `cd85f576`, Codex CLI `0.155.1`, AAS core `0.1.1` from `d3bfc91`, Node `24.0.0`, Pydantic AI `2.0.0`, and OpenAI Python `3.46.0`. All runs requested `gpt-6.1-sol` at low effort. The three-way live run rotated runtime order across five concurrent case groups.

## Native scenario results

All three runtimes passed **84/84 scripted cases**. The model, effort, instructions, strict output schema, input history, and tool declaration hashes matched on each of the 112 scripted provider steps per arm. The live campaign ran all 84 cases and made 393 provider dispatches. All 376 terminal receipts identified the served model as `gpt-6.1-sol`. All 82 model-backed first dispatches per candidate matched Codex. Later live requests can differ when the model selects different tools. Both empty-work Atlas cases skipped generation in all arms.

| Live contract passes | Codex | AAS | Pydantic AI |
| --- | ---: | ---: | ---: |
| Mira English | 29/35 | 34/35 | 29/35 |
| Mira Chinese | 30/35 | 32/35 | 32/35 |
| Atlas English and Chinese | 14/14 | 14/14 | 14/14 |

The live pass counts cover schema, framing, and the existing scenario checks. Codex had 11 JSON decode errors. AAS had three application validation errors and one incomplete stream. Pydantic AI had eight connection errors before a terminal provider receipt and one application validation error. The case receipts retain those failures separately from timings of passing cases.

All eight Pydantic AI connection-error cases passed in a separate serial retry with the same initial request hashes. The retry made eight dispatches. The original stream failures did not recur, so their cause remains unresolved.

| Median time on matched passing cases | Cases | Codex | AAS | Pydantic AI |
| --- | ---: | ---: | ---: | ---: |
| Scripted Mira first runtime text | 70 | 0.362 s | 0.056 s | 0.070 s |
| Scripted Atlas completion | 12 | 0.549 s | 0.264 s | 0.404 s |
| Live Mira first runtime text | 57 | 3.091 s | 2.335 s | 2.391 s |
| Live Mira completion | 57 | 5.266 s | 4.582 s | 4.733 s |
| Live Atlas completion | 12 | 14.573 s | 13.904 s | 13.631 s |

First runtime text is the first text delta delivered by the runtime to the worker. Endpoint events are measured separately. Across the 57 matched Mira cases the gateway reported 92,099, 92,142, and 90,596 total tokens for Codex, AAS, and Pydantic AI respectively. Across the 12 matched Atlas cases it reported 198,531, 203,064, and 203,064.

The relay removes Codex runtime metadata and builtin tools, normalizes message framing and the terminal prompt newline, and requests sequential tool calls across all three arms. It retains the governed prompt text and schema fields, including `$defs` and bounds. Pydantic AI's actual `Agent` drives the loop with registered Memoir tools and the exact output schema. AAS's `query()` drives the loop in a warm Node process. Both candidates rebuild context from authorized history. Codex starts the existing app-server subprocess.

## HTTP, SQL, and isolation

- Mira completed **18/18** public HTTP turns against disposable PostgreSQL. Each arm passed English and Chinese opening, follow-up, and resumed recall, with streamed text, validated questions, durable save, and cached replay. The resumed test recreates the worker. Codex resumed its committed native thread. The two embedded candidates rebuilt the conversation from the committed SQL record.
- All **six** foreign-owner replay probes returned HTTP 409 at the conversation mapping boundary, before another model dispatch. Recall returned the correct source and excluded the other seeded source IDs. The test binds synthetic authenticated identities to real SQL roles and publication fences.
- Atlas completed **six** bilingual activity runs through the worker and durable finish RPC. Each processed the authorized source and released the claim. The shared extraction path used the same controlled Responses provider.
- A separate callback test rejected a bearer token belonging to another exchange and rejected an AAS callback with the correct service secret and a foreign turn scope. The authorized callback still completed its tool round.

## Simultaneous load

Each wave starts 50, 100, or 300 Mira jobs alongside eight Atlas jobs. The load generator uses the same runtime adapters and a scripted local Responses stream with 100 ms per text chunk. The run shared a host with the other benchmark worktrees. The percentiles measure observed local burst performance, including wait time, on successful jobs. The SQL and public HTTP checks above run separately.

| Default worker, Mira finished | Codex | AAS | Pydantic AI |
| --- | ---: | ---: | ---: |
| 50 offered | 10/50 | 10/50 | 10/50 |
| 100 offered | 10/100 | 10/100 | 10/100 |
| 300 offered | 10/300 | 4/300 | 10/300 |

The default admits four active turns total, including up to two Atlas jobs, with a queue of eight per lane. In the 300-turn burst, every arm rejected 290 Mira submissions at the queue boundary. Six more AAS submissions expired while queued. Atlas completion in that wave was 2/8 Codex, 2/8 AAS, and 8/8 Pydantic AI. These are single waves under co-load.

| Client queue, p95 Mira completion | Codex | AAS | Pydantic AI |
| --- | ---: | ---: | ---: |
| 50 offered | 8.96 s | 2.41 s | 8.71 s |
| 100 offered | 17.29 s | 6.91 s | 12.83 s |
| 300 offered | 52.29 s | 8.85 s | 30.48 s |

The client queue admits up to 12 Mira and four Atlas executions and absorbs the rest of the burst. All three finished every submitted job. At 300, the observed peak process-tree RSS above each arm's idle level was approximately 1,319 MiB for Codex, 96 MiB for AAS, and 103 MiB for Pydantic AI. The measurements include the local runner and relay.

The 300-turn pooled repeat after the parallel load waves also completed every Mira and Atlas job. Mira p95 completion was 29.80 s for Codex, 6.58 s for AAS, and 10.85 s for Pydantic AI.

| Uncapped warm runtime, p95 Mira completion | AAS | Pydantic AI |
| --- | ---: | ---: |
| 50 active plus Atlas | 2.12 s | 3.55 s |
| 100 active plus Atlas | 15.78 s | 14.53 s (98/100) |
| 300 active plus Atlas | 25.33 s | 20.47 s |

The uncapped profile reached 308 concurrent executions in each warm runtime at the largest burst. All 300 Mira and eight Atlas executions completed in both arms. The 100-turn Pydantic AI wave had two failed turns. This profile measures embedded-runtime pressure with scripted responses and excludes Codex subprocesses and the application admission cap. The queued profile is the three-way comparison. The figures do not establish provider capacity or a production 300-turn service-level target.

The uncapped 100-turn repeat completed all 100 Mira and eight Atlas jobs in both warm runtimes. Mira p95 completion was 1.13 s for AAS and 2.30 s for Pydantic AI.

## Parallel candidates

Each candidate ran in a dedicated worktree and passed all 84 scripted cases with the matched Codex and AAS requests. The live candidate runs reused the three-way Codex and AAS receipts from the earlier window. Every candidate matched all 82 model-backed initial requests. Stream failures before a terminal receipt affected all three later windows, and the bounded diagnostic subsets recovered. Keep the original outcomes and use the separately reported retries to assess the instability.

| Local branch | Mira first-pass live | Atlas first-pass live | Diagnostic retry pass |
| --- | ---: | ---: | ---: |
| `codex/strands-benchmark` | 41/70 | 10/14 | 3/3 |
| `codex/pi-benchmark` | 44/70 | 13/14 | 7/7 |
| `codex/deep-agents-benchmark` | 56/70 | 14/14 | 12/12 |

## Reproduce

Use the benchmark virtual environment on top of Memoir's dev dependencies. Set `AAS_CORE` to the built `packages/core` from the pinned AAS revision and `NODE_BIN` to a Node 22 or later executable. The AAS pilot report on `codex/advanced-aas-benchmark` documents the build procedure.

```sh
uv venv --system-site-packages var/pydantic-benchmark/.venv
bench_python=var/pydantic-benchmark/.venv/bin/python
uv pip install --python "$bench_python" 'pydantic-ai-slim[openai]==2.0.0' 'openai==3.46.0'
"$bench_python" scripts/benchmark_pydantic_ai.py --aas-core "$AAS_CORE" --node "$NODE_BIN" \
  --output var/pydantic-benchmark/replay-controlled.json
"$bench_python" scripts/benchmark_pydantic_ai.py --aas-core "$AAS_CORE" --node "$NODE_BIN" \
  --live --env-file "$MEMOIR_ENV_FILE" --concurrency 5 --max-calls 450 \
  --output var/pydantic-benchmark/replay-live.json
MEMOIR_TEST_POSTGRES_BACKEND=apple-container MEMOIR_TEST_AAS_CORE="$AAS_CORE" MEMOIR_TEST_NODE="$NODE_BIN" \
  "$bench_python" -m pytest -q tests/test_deepseek_harness_benchmark.py tests/test_pydantic_benchmark_security.py \
  -k 'bilingual_endpoint or atlas_activity or other_exchange'
"$bench_python" scripts/benchmark_pydantic_load.py --aas-core "$AAS_CORE" --node "$NODE_BIN" \
  --output var/pydantic-benchmark/replay-load.json
```

Native PostgreSQL hit the host shared-memory limit. The two SQL checks passed with the repository's disposable Apple container fixture. The focused relay security test and 56 conversation and evaluation checks passed. The broader suite's 24 failed test cases also failed on the fixture base revision.

[Per-case results and receipt hashes](test-evidence/pydantic-ai-20261108.json)
