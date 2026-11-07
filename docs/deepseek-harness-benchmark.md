# DeepSeek Harness benchmark

**Keep Codex as the production runtime for Mira and Atlas.** DeepSeek passed more Mira contract checks in this run. Its native SDK delivered Mira text later and its cold-process orchestration took longer in the scripted controls. The branch provides a benchmark-only adapter with Memoir's existing worker and publication fences.

The trial used Memoir `6f196efd`, codex-cli 0.155.1, and the published DeepSeek SDK runtime `0.2.1-rc.2` from `687f282e`. Both arms requested `gpt-6.1-sol` at `low` effort, alternating which arm ran first. [Pinned DeepSeek release](https://github.com/deepseek-ai/deepseek-harness/releases/tag/dsh-v0.2.1-rc.2)

## Native comparison

Times are medians over cases that passed in both arms and called the model. The last column is the median of the per-case DeepSeek minus Codex times. First text here means the first model text received by the worker. Completion includes subprocess teardown and the case validator. The separate endpoint measurements below cover public text.

| Live metric | Pairs | Codex | DeepSeek | Paired change |
| --- | ---: | ---: | ---: | ---: |
| Mira first text via benchmark adapter | 59 | 3.31 s | 3.44 s | +0.13 s |
| Mira first text via native SDK notifications | 59 | 3.31 s | 5.52 s | +2.24 s |
| Mira first text, English, with adapter | 29 | 3.67 s | 3.36 s | -0.55 s |
| Mira first text, Chinese, with adapter | 30 | 3.10 s | 3.68 s | +0.75 s |
| Mira completion | 59 | 5.11 s | 5.68 s | +0.04 s |
| Atlas completion | 12 | 10.71 s | 11.00 s | +0.92 s |

Mira passed **59/70 Codex** and **64/70 DeepSeek**. Atlas passed **14/14** and **14/14**, including two empty-work cases that correctly skipped the model. The two arms matched on model, effort, app instructions, initial message history, output schema, and tool declarations for all 82 model-backed first requests. Live follow-on requests can differ when the model selects different actions. The campaign made 256 gateway calls. All 242 dispatches that reported a served model named `gpt-6.1-sol`.

The relay removed Codex's permission and working-directory messages, built-in tools, and runtime cache identifiers. It aligned tool declarations to Codex's provider projection while Memoir enforced the full application constraints. DeepSeek's plugin relayed the strict Responses schema, while SDK sessions owned the tool loop and persistence. The worker used a plugin stream for early text because the SDK emits `assistant/message` after a model step. [DeepSeek adapter API](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.2.1-rc.2/docs/cookbook/adding-an-llm-adapter.md)

| Scripted metric | Pairs | Codex | DeepSeek | Paired change |
| --- | ---: | ---: | ---: | ---: |
| Mira subprocess startup | 70 | 0.15 s | 0.47 s | +0.31 s |
| Mira first text | 70 | 0.30 s | 0.56 s | +0.30 s |
| Mira completion | 70 | 0.36 s | 1.72 s | +1.35 s |
| Atlas completion | 12 | 0.50 s | 2.37 s | +1.75 s |

Both runtimes passed all 84 scripted cases. Every scripted model step matched after request normalization. The fixture used two text chunks separated by 40 ms. The test starts a fresh subprocess per connection, as the current worker does. These are single samples per case on the local machine. Pass counts cover schema, JSON framing, and the existing code checks. The run used five concurrent live case pairs and serial scripted pairs.

## Durable application checks

- Mira passed 12 HTTP runs across English and Chinese opening, follow-up, and resumed turns. The test checked public text, question validation, committed replies, idempotent replay, persisted thread reuse, and owner-scoped recall through real SQL. Both arms used controlled policy and provider responses, with early policy acknowledgement disabled.
- Atlas processed sources and released the background lease in all four durable activity runs. Codex finished in 2.00 s English and 1.57 s Chinese. DeepSeek took 2.93 s and 3.20 s. Each used three native calls and one bounded timeline extraction call.
- The two planned source-to-private-draft workflows have 2/2 passing bilingual SQL readbacks. They cover source versions, event revisions, a private checkpoint, and invalidation after withdrawal.

## All current skill scenarios

The 198-case catalog combines 84 native agent scenarios, 112 downstream scenarios, and two public discovery cases. The two private-draft workflows are additional. Retained calibration questions belong to the evaluator.

| Shared path | Controlled pass | Controlled median | Live pass | Live median | Boundary |
| --- | ---: | ---: | ---: | ---: | --- |
| author-timeline | 16/16 | 0.03 s | 10/16 | 9.67 s | Direct Responses extraction and exact source validation |
| memory-context | 16/16 | 0.17 s | 16/16 | 4.81 s | Direct Responses profile proposals with manual authority checks |
| composer | 16/16 | 1.23 s | 14/16 | 199.10 s | Direct Responses and progressive checkpoint orchestration |
| family-tree | 0/16 | — | 13/16 | 4.35 s | Proposal probes only, canonical integration unwired |
| place-photo-research | 14/16 | 0.29 s | 0/1 | — | Configured discovery and source inspection |
| historical-news-research | 14/16 | 0.41 s | 1/1 | 19.49 s | Public queries and source verification |
| story-game | 16/16 | 30.55 s | — | — | Private generation, authority, and browser fixtures |

Shared controls used scripted model or service boundaries. The configured photo outage and historical source outage each have two explicit unavailable cases. The public historical discovery verified a source. The photo discovery returned no independently verified photo. Story-game has 2/2 verified browser play cases, using a private HTML build fixture and the existing runtime. The live Composer outcomes cover 16/16 cases, including two Chinese drafts that reached the 120-second provider deadline. The family proposal checks passed 13 of 14 executable cases. The two family integration cases lack a canonical executor.

## Reproduce

Install the published runtime in an isolated environment. Export `DSH_BIN` as the absolute path to the executable returned by `resolve_bundled_launch_args()[0]` from `deepseek_harness_runtime`.

```sh
uv pip install 'deepseek-harness-sdk==0.2.1rc2'
python3 scripts/benchmark_agent_harness.py --list
python3 scripts/benchmark_agent_harness.py --dsh-bin "$DSH_BIN" --output var/harness/control.json
python3 scripts/benchmark_agent_harness.py --scope native --dsh-bin "$DSH_BIN" --live \
  --env-file "$MEMOIR_ENV_FILE" --max-calls 300 --concurrency 5 --output var/harness/live-native.json
MEMOIR_TEST_DSH_BIN="$DSH_BIN" MEMOIR_TEST_POSTGRES_BACKEND=apple-container \
  python3 -m pytest -q tests/test_deepseek_harness_benchmark.py
```

Use `--scope skills --live` for the shared model paths. Set `MEMOIR_BROWSER_URL` to a task-owned local frontend and `MEMOIR_BROWSER_EXECUTABLE` to the Chromium or Chrome executable to collect the play witnesses. The skill controls support `MEMOIR_TEST_POSTGRES_BACKEND=apple-container` with disposable loopback instances.

The opt-in benchmark suite passed all four tests. The focused Python suite passed 159 tests. The place-research target passed 766 web, 785 API, and 96 skill checks.

[Per-scenario timings, request hashes, and verification](test-evidence/deepseek-harness-20261107.json)
