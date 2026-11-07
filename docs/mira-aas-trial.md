# Mira on advanced_aas

Memoir sends reviewed text turns through the existing `POST /v1/agent/turn` route. The private worker can send the governed Responses request to a loopback Node process running `@aas/core`’s `query()`. Each AAS turn starts from authorized PostgreSQL dialogue and the current source. This works after a sidecar restart because Memoir owns the committed history.

The sidecar can call `memoir_read_context` through the private worker. Memoir checks the publication fence at the initial handoff and again when sending each bounded tool result, then uses its existing validators and commit. The AAS process aborts the gateway connection and outstanding tool callbacks when the worker disconnects. Mira allows four recall calls per attempt under the existing byte and deadline limits.

`MEMOIR_MIRA_AAS_URL` enables the AAS text path. Photo and transcription turns and revisable replies use Codex. Atlas’s normal path uses its existing Temporal and Codex workflow. The benchmark injects AAS at Atlas’s activity runner for comparison.

## Follow-up and resumed recall

The controlled benchmark measures four matched cases through the real HTTP turn and disposable PostgreSQL commit. Each reply used two provider requests with matched `gpt-6.1-sol`, requested low reasoning, Mira system prompt and strict output schema. A scripted tool request drove the real recall lookup, and the continuation received the exact earlier source from the correct owner. Replays returned the same committed reply without calling the provider. The resumed case recreated the worker and restarted the AAS process. Codex resumed its committed native thread.

| Controlled case | First text, Codex → AAS | Durable save, Codex → AAS |
| --- | ---: | ---: |
| English follow-up | 0.862 → 0.416 s | 0.984 → 0.505 s |
| English resumed | 0.633 → 0.374 s | 0.783 → 0.451 s |
| Chinese follow-up | 0.700 → 0.315 s | 0.860 → 0.414 s |
| Chinese resumed | 0.618 → 0.391 s | 0.750 → 0.488 s |

Each row has one observation per runtime. The provider fixture holds the recall request and reply fixed. Codex carries its native transcript, while AAS reconstructs authorized dialogue and context. This comparison matches the prompt and schema and exercises those distinct history mechanisms.

The live run held the recall decision fixed, executed the actual scoped lookup, and sent the continuation to the configured gateway. All eight final replies used the same wire model, system prompt, requested reasoning and output schema, returned the recalled fact, saved and replayed. Privacy review used the controlled response in both arms.

| Live final after recall | First text, Codex → AAS | Durable save, Codex → AAS |
| --- | ---: | ---: |
| English follow-up | 12.624 → 8.906 s | 14.934 → 10.413 s |
| English resumed | 7.036 → 6.399 s | 8.979 → 9.099 s |
| Chinese follow-up | 9.385 → 5.839 s | 10.467 → 7.087 s |
| Chinese resumed | 6.093 → 5.303 s | 7.222 → 5.992 s |

Gateway load, caching and effective upstream reasoning were uncontrolled. The live follow-up replies become part of each arm’s resumed dialogue. These eight live requests test final replies after tool use. The benchmark scripts the model’s decision to call the tool. Redacted timing and wire receipts are in `var/mira-aas-trial/mira-recall-controlled.json` and `var/mira-aas-trial/mira-recall-live.json`.

## Atlas activity

The controlled benchmark starts at `execute_background_agent` and ends after the durable finish RPC. Each arm reads the same timeline skill, selects and processes one source, and finishes. Three orchestration requests and one nested extraction request used the scripted provider. Every arm persisted successful source processing and released its claim.

| Locale | Activity to durable finish, Codex → AAS |
| --- | ---: |
| English | 1.754 → 1.523 s |
| Chinese | 1.508 → 1.244 s |

Atlas’s orchestration model, requested reasoning, system prompt and strict schema matched exactly. The nested extraction schema binds the authorized source UUID in three fields. The test verifies those values against each arm’s database record and normalizes them for comparison. All other schema fields match. The receipt includes both scoped wire hashes and normalized hashes. The timings cover one activity per arm and language with scripted output, after dispatch from the queue. `var/mira-aas-trial/atlas-controlled.json` contains the redacted receipt.

## Initial opening-turn results

Three controlled pairs ran through the existing endpoint, using the installed Codex CLI `0.155.1`, `advanced_aas` `d3bfc91`, and a disposable PostgreSQL 18.3 container. The fixture streamed identical output in both arms. All six requests matched `gpt-6.1-sol`, requested low effort, the compiled Mira system prompt, and the strict output schema at the provider wire. All six replies committed and replayed without another provider request. The AAS arm used its separate execution ID in PostgreSQL. The baseline used a fresh native thread, while the sidecar process stayed up across all three AAS turns.

| Median from HTTP submission | Codex | advanced_aas |
| --- | ---: | ---: |
| Source accepted | 0.208 s | 0.230 s |
| First meaningful text | 0.997 s | 0.427 s |
| Validated question | 1.255 s | 0.496 s |
| Durable conversation save | 1.409 s | 0.534 s |

The first Codex sample also had slower database preparation. The median from source acceptance to first text was 0.802 s with Codex and 0.197 s with AAS. These three synthetic pairs measure this local execution path. Codex advertises its recall tool and the AAS trial uses an empty registry. The benchmark leaves Atlas undrained and disables native runtime-home backups in the disposable worker.

One live pair on 7 November 2026 used the configured `gpt-6.1-sol` gateway route. Both wire contracts matched the controlled runs. Both replies validated, committed and replayed after one submission per arm.

| Live pair from HTTP submission | Codex | advanced_aas |
| --- | ---: | ---: |
| Source accepted | 1.931 s | 0.778 s |
| First meaningful text | 21.220 s | 11.205 s |
| Validated question | 23.162 s | 14.742 s |
| Durable conversation save | 23.300 s | 14.974 s |

Codex ran first in the live pair. Provider load, caching, effective upstream reasoning and local database preparation were uncontrolled. The one live pair measures delivery through the configured gateway on that run. The controlled pairs give a separate estimate with fixed provider output. The redacted timing receipts and prompt/schema hashes are in `var/mira-aas-trial/controlled.json` and `var/mira-aas-trial/live.json`.

## Run the trial

The installed trial build is in `var/mira-aas-dependency`. To rebuild the reviewed `d3bfc91` revision, use Node 22 or newer and pnpm from the Memoir checkout.

```sh
aas_build="$PWD/var/mira-aas-dependency"
mkdir -p "$aas_build"
git -C /Users/bohuihan/ai/advanced_aas archive d3bfc91 | tar -xf - -C "$aas_build"
(
  cd "$aas_build"
  pnpm --filter @aas/core... install --frozen-lockfile --ignore-scripts
  pnpm --filter @aas/core build
  node scripts/fix-esm-extensions.mjs packages/core/dist
)

MEMOIR_TEST_AAS_CORE="$aas_build/packages/core" \
MEMOIR_TEST_MIRA_AAS_PAIRS=6 \
python3 -m pytest -q -s tests/test_mira_aas_trial.py
```

On macOS, set `MEMOIR_TEST_POSTGRES_BACKEND=apple-container` to use the disposable PostgreSQL container fixture. `MEMOIR_TEST_NODE` selects an explicit Node binary. Each pair uses two fresh synthetic projects in that database and alternates the order of the two workers. The test runs the installed Codex binary, the AAS core, the real FastAPI routes, and the existing PostgreSQL commit. It checks model, requested effort, system prompt and output schema at the provider wire and verifies that replay uses the saved reply.

Run `python3 -m pytest -q -s tests/test_mira_aas_recall_benchmark.py` with the same core and PostgreSQL environment to compare bilingual recall and the Atlas activity. Set `MEMOIR_TEST_MIRA_AAS_RECALL_LIVE_ENV` to the existing gateway environment file to let the configured model generate the eight final Mira replies after the same scripted recall decision and real SQL lookup. The opt-in sends one live reply per locale, phase and runtime. Atlas’s comparison uses the scripted provider.

The default provider emits the same scripted SSE response for both arms. For one live pair, set `MEMOIR_TEST_MIRA_AAS_PAIRS=1` and `MEMOIR_TEST_MIRA_AAS_LIVE_ENV` to the existing environment file containing `MEMORY_SPARK_LLM_API_KEY`. This explicitly permits two synthetic Mira generations through the local gateway at `127.0.0.1:4000`, one per arm. Privacy review uses the same controlled response in both modes. Gateway load, caching and runtime-supplied tools can affect live results.

For an isolated development worker, launch `node mira-aas/server.mjs "$aas_build/packages/core"` with `MEMORY_SPARK_LLM_BASE_URL`, `MEMORY_SPARK_LLM_API_KEY` and a random `MEMOIR_MIRA_AAS_SECRET` of at least 32 characters. Give the worker the same secret and set `MEMOIR_MIRA_AAS_URL=http://127.0.0.1:8780/v1`. Run both in the same network namespace. The sidecar listens on loopback and the existing worker still authenticates requests from Memoir’s API.
