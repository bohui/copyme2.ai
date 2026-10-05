The configured ChatGPT account-pool route removes output-limit fields in pinned codex-lb 1.24.0. Live evaluation remains blocked. Forwarding an unsupported field, limiting visible stream text, or counting worker requests cannot prove the amount generated or the number of upstream attempts. Shared gateway changes and provider-model calls are outside this proposal.

The preferred supported candidate preserves the underlying `gpt-5.6-luna` model and current narrator/composer efforts (`max`/`low`), using a task-only adapter to the official metered OpenAI Responses API. The existing OpenAI API key is present; its validity, billing region and access to this model have not been verified. The current gateway only tracks direct OpenAI aliases for `gpt-4o` and `gpt-4o-mini`. No alias, credential, account, or shared service has been changed. API support alone does not validate compatibility with the application's app-server/tool protocol.

The official API documents `max_output_tokens` for Responses, including reasoning output. Prompt length instructions and verbosity are insufficient substitutes. See [output controls](https://help.openai.com/en/articles/5072518-controlling-the-length-of-openai-model-responses). Before contacting a provider, the task adapter must measure a conservative complete input bound, reserve its input/output/cost allowance, enforce the output field on the actual API request, disable automatic retries, and record every role/attempt/continuation. Interrupted requests retain their full reservations; client cancellation does not prove upstream generation stopped. Missing or over-bound usage blocks further calls. Wire tests and independent cloud review must pass first.

Prices checked on October 5, 2026 are standard global text API prices, per million tokens. [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna) lists $0.20 input and $1.20 output. Longer prompts above 272,000 input tokens increase the full request's rates; cache writes can increase input charges. The proposal therefore caps every measured input at 272,000 tokens, reserves all input at $0.25 per million to cover the documented cache-write multiplier, and excludes hosted tools, images, regional/fast service tiers and judges. Prices and account access must be rechecked before execution.

| Proposed ceiling | Diagnostic pilot | Five conversations and composition |
| --- | ---: | ---: |
| Visible scope | 8 source-veto inputs across 2 locales, 4 ephemeral follow-ups | 5 × 50 original rounds, 50 draft checkpoints |
| Actual upstream attempts, all roles | 80 | 2,000 |
| Complete input tokens | 400,000 | 40,000,000 |
| Output tokens including reasoning | 80,000 | 4,000,000 |
| Output tokens per attempt | 1,000 | 4,096 |
| Measured input tokens per attempt | 272,000 | 272,000 |
| Runtime / concurrency | 40 minutes / 1 | 3 hours / 1 |
| Conservative text-token reservation | $0.196 | $14.80 |
| Requested API text-charge ceiling | $0.25 | $15.00 |
| Judge, photo, geocoding, hosted-tool calls | 0 | 0 |

The reservations are calculated from the token ceilings and the stated input/output rates; they are proposals, not current enforcement or spending approvals. The rounded charge ceilings permit no additional request after remaining reservations are insufficient. They exclude account taxes/currency conversion. Reaching a ceiling leaves an incomplete receipt. Model acceptance for all seven skills still needs separately approved and bounded photo/geocoding work and accepted judge calibration.

An existing `gpt-4o-mini` direct API alias is another supported candidate, at [documented standard text rates](https://developers.openai.com/api/docs/models/gpt-4o-mini) of $0.15 input/$0.60 output per million. The same aggregate token volumes cost $0.108/$8.40 before additional services. Selecting it requires explicit model-change approval and a separately labeled evaluation variant; it does not preserve the current Luna/effort baseline. Neither candidate has been selected or contacted for generation.

After the adapter is concrete, tested and cloud-reviewed, the exact approval needed for the preferred pilot is: use the existing key privately in a task-only official OpenAI route for gpt-5.6-luna at the current efforts, authorize at most $0.25 of API text charges, and apply every pilot ceiling in the table. The full conversation/composition run needs a separate approval for its $15 ceiling and larger limits. The parent coordinates these approvals; this document does not request or infer them. A key-access read and fresh model/account metadata verification precede inference. No new credential, shared gateway restart, persistent host change or paid commitment has occurred.
