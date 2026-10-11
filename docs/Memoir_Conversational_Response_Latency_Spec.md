## Problem Statement

Storytellers wait too long for meaningful text after sending an answer to Mira.
The problem is time to the first visible AI response on **every conversational
turn**, not just the first answer during onboarding. The optimization must
apply to all future generated replies in new, ongoing, and resumed memoir
conversations, including conversations created before the change.

Profiling on 11 October 2026 found that a fresh name-only turn through the web
proxy began visible text at 7.804 seconds and reached `conversation_saved` at
10.366 seconds. Preparation took approximately 1.4 seconds. Isolated story-rich
opening trials on the current collector route took 7.122–45.431 seconds to
produce a visible acknowledgement; the existing genuine low-effort route took
5.444–5.949 seconds in two trials. These are small-sample measurements, not
production service-level guarantees or evidence about later turns.

The current upstream collector key enforces maximum reasoning. Requesting low
effort at the application does not override that policy. Generation dominates
the observed long wait: one request received its first upstream event at
684 milliseconds but its first token at 44,125 milliseconds, with recorded
local bridge/gate waits of zero. The collector also receives approximately
27k characters of application instructions even for a simple introduction.

The existing HTTP/NDJSON reply stream is not the source of a fixed 15-second
delay. That polling interval belongs to background workspace refreshes. Changing
transport or animating placeholder text would not resolve the generation wait.

## Solution

Make each future Mira conversational reply begin promptly with a brief,
grounded acknowledgement, then deliver its validated follow-up and safely save
the exchange. Preserve the storyteller's language, conversation continuity,
source evidence, and control over the interview.

Use independently configurable, genuinely low-effort same-model routing for
the conversational collector, reduce irrelevant collector prompt overhead,
and remove avoidable preparation work where measurement justifies it. Apply
these changes through the shared conversational execution path on every
generated turn, not through an onboarding-only shortcut. Keep workspace work
independent and preserve the existing stream and persistence contracts.

Verify correctness primarily through the existing backend streaming interview
interface, as explicitly selected by the user. Compare representative first,
subsequent, and resumed turns before rollout. Provide a server-controlled
rollback to the previous collector configuration without changing the shared
upstream key or other agent roles.

## User Stories

1. As a storyteller, I want the first meaningful AI text to arrive promptly after every answer, so that the interview feels like a continuing conversation.
2. As a new storyteller, I want a short response to my preferred-name introduction, so that beginning my story does not involve an unnecessary wait.
3. As a storyteller, I want a faster response to my second and later answers, so that the improvement continues after onboarding.
4. As a returning storyteller, I want resumed conversations to use the optimized reply path, so that I do not need to start a new memoir to benefit.
5. As a storyteller with an existing project, I want future replies to become faster without migrating or deleting my story, so that my saved work remains intact.
6. As a storyteller, I want a name introduction containing real story details to receive an appropriate continuation, so that speed does not discard my memories.
7. As a storyteller, I want a long or emotionally significant answer to receive a grounded response, so that a shorter prompt does not make Mira careless.
8. As a storyteller, I want one useful follow-up question at a time, so that a fast response remains easy to answer.
9. As a storyteller, I want the acknowledgement to reflect something I actually said, so that apparent speed is not achieved with generic filler.
10. As a storyteller, I want Mira to remember the relevant recent exchange, so that a later reply does not repeat an already answered question.
11. As a storyteller, I want a resumed reply to retain my established name and context, so that changing a model route does not restart the interview.
12. As a storyteller, I want meaningful text to arrive before optional workspace work completes, so that I can read while enrichment continues.
13. As a storyteller, I want reply completion and safe saving to remain distinct, so that visible text does not falsely imply that my answer is retained.
14. As a storyteller, I want the next-answer control enabled after the exchange is safely saved, so that faster acknowledgement is followed by a usable conversation.
15. As a storyteller, I want delayed chapter, timeline, family, place journey, or public reference work not to block my reply, so that optional context does not dominate response time.
16. As a storyteller, I want a minimal conversational reply to avoid unnecessary extraction, so that latency and model work remain proportional to the message.
17. As a storyteller, I want new memory clues in any turn to continue through normal extraction, so that optimization does not silently lose useful testimony.
18. As a storyteller, I want corrections to retain their effect on future replies and workspace processing, so that a faster route does not preserve a superseded version.
19. As a storyteller, I want pauses and requests to stop respected promptly, so that optimization does not force another question.
20. As a Chinese-speaking storyteller, I want Chinese replies and exact original names preserved, so that lower effort does not reduce language fidelity.
21. As an English-speaking storyteller, I want the same latency improvements, so that this is not a Chinese-onboarding-only feature.
22. As a bilingual storyteller, I want explicit conversation-language changes respected on later turns, so that optimization does not freeze the initial language.
23. As a storyteller discussing a photograph, I want associations grounded in my current identification and supplied metadata, so that faster generation does not invent what an image shows.
24. As a storyteller, I want public references kept separate from personal evidence, so that a shorter prompt does not turn a reference into a biographical fact.
25. As a storyteller, I want a place cue and place journey treated as conversational context rather than proof of residence, so that speed preserves the project's meaning of those terms.
26. As a Family storyteller, I want entitled family context considered when it is relevant, so that prompt reduction does not remove permitted continuity.
27. As a storyteller, I want payment, recall limits, and ownership checks retained, so that faster preparation does not bypass application policy.
28. As a storyteller, I want malformed or unsupported model proposals corrected or rejected before their question is exposed, so that faster replies remain trustworthy.
29. As a storyteller, I want a retry to recover the accepted or saved exchange without duplicating my answer, so that a network failure does not generate a second question unnecessarily.
30. As a storyteller, I want existing saved replies replayed without being regenerated by the optimization, so that my history remains stable.
31. As a storyteller, I want disconnect and save-failure behavior to remain clear, so that partial text is not presented as durable success.
32. As a storyteller, I want private context isolated to my authorized account and project, so that faster execution preserves access controls.
33. As an operator, I want collector model routing and reasoning effort configurable independently, so that reply latency can be tuned without changing workspace or composition behavior.
34. As an operator, I want the effective upstream reasoning policy verified, so that requesting low effort is not mistaken for actually running at low effort.
35. As an operator, I want existing sessions to use the current collector configuration on their next generated turn, so that persisted threads do not silently retain obsolete routing.
36. As an operator, I want the shared maximum-effort key left unchanged, so that unrelated applications are not affected by a Memoir optimization.
37. As an operator, I want a reversible collector configuration, so that a quality or latency regression can be rolled back without rewriting story data.
38. As an operator, I want bounded behavior when the selected route is unavailable or misconfigured, so that an optimization does not create uncontrolled retries or silent fallback.
39. As an operator, I want first visible text, validated question completion, and conversation saving measured separately, so that an early acknowledgement does not conceal a slower usable reply.
40. As an operator, I want preparation, dispatch, first raw model delta, effective route, retries, and final outcome recorded safely, so that the source of a slow reply can be identified.
41. As an operator, I want first, subsequent, and resumed turns represented in latency reports, so that an opening-only benchmark cannot satisfy an all-conversation requirement.
42. As an operator, I want latency distributions and failure counts reported together, so that failed or unusually slow calls are not hidden by averages.
43. As a maintainer, I want collector prompt reduction to preserve essential interview contracts, so that brevity is validated by behavior rather than a character-count target alone.
44. As a maintainer, I want independent context reads optimized without weakening cancellation settlement or fenced writes, so that lower preparation time does not introduce races.
45. As a maintainer, I want deterministic backend streaming tests at the existing interface, so that correctness does not depend on live provider timing.
46. As a maintainer, I want isolated, bounded live measurements using synthetic storytellers, so that evaluating performance does not modify customer memoirs or run an unlimited campaign.
47. As a reviewer, I want a documented quality and latency comparison before enabling the optimized default, so that a few successful opening examples are not treated as sufficient release evidence.
48. As a reviewer, I want baseline and candidate configuration versions recorded, so that later measurements can be reproduced and compared fairly.

## Implementation Decisions

- **Every-turn scope:** optimize the shared conversational collector module used by all future generated Mira replies. Include first answers, subsequent answers, rich stories, and resumed conversations created before rollout. Include server-owned conversational actions when they generate a collector reply. The fixed, no-model introduction remains unchanged. Saved-result replay is not new generation and must remain idempotent.
- **Primary performance definition:** time to first visible text means elapsed time from submitting the conversational request to receiving its first meaningful public `text_delta`. Track acknowledgement, validated chosen-question availability, and `conversation_saved` separately. Initial headers, `started`, progress, heartbeats, JSON fragments, and generic filler do not count as a response. Browser rendering is a separately labelled observation, not interchangeable with HTTP receipt.
- **Collector-specific configuration:** introduce server-owned collector route and reasoning-effort overrides within the existing conversational module configuration. Preserve legacy configuration behavior when overrides are absent. Resolve the chosen configuration consistently for local and private-worker execution and on every new or resumed turn; caller-facing interview requests do not gain model, key, or effort controls.
- **Genuine low-effort routing:** use a dedicated same-underlying-model route whose upstream key permits or enforces low effort. The existing `memoir-luna-low` route is a measured candidate, not an assumed final default. Verify effective provider policy during deployment/evaluation; a requested effort value alone is not evidence. Do not alter the shared maximum-effort key. Keep workspace, memory-context, author-timeline, organiser, and composer configuration unchanged unless already separately configured.
- **Existing-thread compatibility:** apply current collector routing/effort to the next generated turn in persisted sessions without dropping the authorized conversation history. If provider thread compatibility requires a refreshed execution thread, retain authoritative accepted narration, relevant prior exchanges, and saved planning context. Do not reset the interview, misclassify the turn as an opening, or re-run previously committed turns.
- **Controlled rollout and rollback:** keep the candidate route/prompt version reversible through server configuration. Enable the optimized default only after the matched latency/quality comparison passes. Rollback affects future execution, not narrator sources, saved replies, event identities, or workspace revisions. Route failure must remain bounded and explicit; do not silently retry indefinitely or claim low-effort success after falling back to an enforced-max route.
- **Collector-only prompt reduction:** remove redundant instructions and responsibilities unrelated to visible interviewing from the conversational prompt. Retain evidence grounding, narrator voice and uncertainty, language provenance and explicit overrides, topic/privacy controls, one-question behavior, photo/public-reference distinctions, candidate retention/selection, pause handling, and the structured work decision. Use the same reduced contract for subsequent and resumed turns; do not optimize only the small opening prompt.
- **Preserve necessary context:** always retain the entire accepted current narrator source. Supply relevant authorized recent exchanges, saved profile, active canonical events, selected photo metadata, current planning context, and entitled family context as needed. Bound or deduplicate unrelated historical summaries rather than arbitrarily truncating current testimony or removing the facts needed for the next question. Keep original source versions and canonical identifiers intact.
- **No shortcut classifier:** retain a single normal collector pass to choose `reply_only` or `extract` from the full message and available context. A short birthplace clue may require extraction; a name plus a long story must not become a name-only reply. Do not add an extra pre-reply model classifier, surname heuristic, artificial acknowledgement, or fixed earliest-memory question on later turns.
- **Preserve structured publication:** keep the complete acknowledgement's existing safety validation before display. Publish the chosen question only after complete proposal validation and the existing required plan persistence. Preserve the bounded corrective-proposal behavior and controlled failure contract. Never expose private JSON, planning fields, unsupported candidate metadata, or private reasoning in order to improve a timing number.
- **Smaller preparation optimization:** avoid fetching the same entitlement redundantly within one fenced turn when the same authorized result can be reused safely. Consider bounded parallel or batched independent context reads only after measuring their contribution. Preserve dependency ordering for acceptance, locale/profile updates, quota checks, and generation; never cache entitlement or ownership across unrelated turns as a performance shortcut.
- **Lease and cancellation safety:** preserve per-conversation serialization, cross-replica lease checks, write fencing, and private worker tenant identities. Any parallel reads must settle outstanding I/O on error or cancellation before the storage client closes or the lease releases. Lease loss must prevent plan/reply commits. This optimization does not introduce concurrent writes to a shared collector thread or runtime home.
- **Existing delivery contract:** retain streamed POST with HTTP/NDJSON and existing reply/save/workspace event semantics. Do not make chat wait for a private-draft, timeline, family, place journey, or public-reference poll. Keep optional workspace work independent and preserve the next-answer readiness decision at durable conversation save. No new public endpoint or database schema is expected solely for this optimization.
- **Safe measurement:** extend the existing diagnostic/profiling interfaces rather than create a second generation harness. Record allowlisted timings, role, route/version, requested and effective effort where available, terminal status, and application/provider retry counts without credentials, narrator content, generated private planning, or reasoning text. Distinguish one app-server turn from multiple upstream requests. Identify unavailable provider metrics as unavailable, not zero.
- **Matched comparison:** compare baseline routing/prompt, routing-only change, prompt-only change where feasible, and the combined candidate on the same representative synthetic case set and application revision. Fix sample counts, deadlines, and call budget before dispatch. Exercise both supported languages and first, subsequent, resumed, simple, and story-rich turns. Record actual provider policy, input/cache token counts, provider load observations, and retries; acknowledge route-specific context and cache differences as confounds.
- **Acceptance and release evidence:** require all deterministic behavioral regressions to pass and a documented improvement in first-visible response latency across the representative conversational workload, including subsequent/resumed turns. Report median, tail percentiles when sample size supports them, validated-question completion, saved-reply latency, and failures together. Do not enable a candidate merely because its acknowledgement is faster if it loses testimony, lowers contract correctness, or conceals worse completion/save behavior. No absolute numerical service-level objective was agreed in this conversation; do not invent one or claim a small-sample maximum is a production p95.

## Testing Decisions

- **Confirmed primary seam:** use the existing backend streaming interview interface with normal turn orchestration and persistence behavior. The user selected this instead of the browser as the primary seam. Exercise the same streamed request that the web proxy forwards and substitute controlled provider/storage adapters only at existing external seams. Prefer this one high backend seam to tests spread across newly exposed private helpers.
- **Good tests assert external behavior:** observe accepted-source identity, meaningful `text_delta`, the validated visible question, saved state, `conversation_saved`, permitted next-turn execution, and any controlled error. Use test-controlled barriers/events to delay generation, persistence, or workspace completion. Do not assert an exact prompt string, private helper call sequence, fixed live-model wall-clock threshold, or predetermined valid wording when equivalent grounded replies are acceptable.
- **All-conversation scenarios:** cover a name-only opening, a short factual clue, a mixed name-and-story introduction, a long first story, second and later turns, corrections, pauses, photo discussion, language changes, and a resumed pre-rollout session. Verify later/resumed turns continue the relevant memory, retain useful unasked candidates, and do not use generic opening behavior.
- **Configuration scenarios:** cover absent collector overrides, an enabled dedicated route, local/private-worker parity, new and resumed thread execution, route unavailability, explicit bounded failure, and rollback. Verify the effective upstream effort through a read-only provider receipt in live tests, rather than treating the submitted `low` option as proof. Verify other roles retain their own behavior/configuration.
- **Streaming and saving scenarios:** delay optional workspace work and show that meaningful text, a validated question, and `conversation_saved` remain available independently. Delay durable saving and show that partial text is visible without reporting success or permitting overlapping accepted turns. Test split JSON/UTF-8 delivery, idle heartbeats, invalid proposals, bounded correction, failure after partial text, and disconnects before and after save.
- **Persistence and safety scenarios:** retain exact original narration, source versions, canonical event/photo identities, preferred names, language provenance, extraction decisions, quota/entitlement policy, and ownership isolation. Repeated client turn IDs must not duplicate accepted sources, committed replies, charged rounds, or model execution after a saved result. Exercise cancellation with pending reads and lease loss to ensure no post-release I/O or unfenced commit.
- **Prior art:** extend existing turn-stream, name-only opening, interview-photo planning, workspace-latency, worker-isolation, lease-failure, and profiler tests. Existing coverage already checks partial text before save, saved replies before workspace completion, one collector pass for a minimal introduction, extraction for rich introductions, idempotent retries, and I/O settlement before lease release. Keep those behaviors rather than replace them with mocks that bypass the conversational implementation.
- **Secondary browser coverage:** keep a small smoke check through the real web proxy that public deltas render promptly, the completed reply is not duplicated, and next-answer readiness follows saving. Use the existing interview browser harness; do not add a browser framework or make browser timing the primary acceptance seam.
- **Bounded live performance/quality acceptance:** use fresh isolated synthetic identities where needed, the deployed API/private-worker/proxy path, both languages, and representative multi-turn/resumed cases. Collect first-text and completion/save distributions plus validation, retry, extraction, and grounding outcomes. Do not use customer memoirs. Record sample limitations and any failed/timed-out cases; schema validation alone is not a comprehensive semantic-quality score.
- **Rollout regression:** verify an existing conversation's next turn uses the chosen configuration and preserved context, then verify rollback on a subsequent turn without rewriting or losing history. A benchmark limited to first answers cannot pass this specification.

## Out of Scope

- Limiting the optimization to onboarding, the first user answer, new projects, or newly created execution threads.
- Replacing HTTP/NDJSON with SSE or WebSocket, or changing the 15-second background workspace polling interval.
- Changing the fixed introductory greeting, adding fake typing/filler, hardcoding follow-up questions, or bypassing model validation/persistence to appear faster.
- Rewriting narrator sources, re-generating saved historical replies, migrating customer memoirs, or changing canonical event/photo association and question-pool semantics.
- Changing shared upstream key policies, unrelated applications, workspace/composer model choices, family entitlements, commercial rules, or service-role access.
- A broader timeline/family tree/chapter-generation optimization, realtime voice work, a new workflow platform, or a general-purpose model benchmark.
- Unbounded live campaigns, rerunning the existing large acceptance datasets as an incidental step, or promising a sub-second/fixed-latency guarantee not established by the discussion.

## Further Notes

This specification synthesizes the conversation, current memoir terminology,
existing backend streaming execution, and the profiling report dated
11 October 2026. The user explicitly clarified that the optimization applies
to **all future chats/replies**, not only the first user's response, and selected
**backend streaming tests as the primary seam**.

The twelve isolated collector trials all passed application validation. The
genuine low-route openings selected the expected work mode, preserved the
introduced name, and produced valid candidate counts. However, only two
genuine low-route trials were run for each opening case; subsequent/resumed
performance and comprehensive semantic quality remain to be established.
Different provider input/cache token counts and one upstream retry also limit
causal attribution. These findings motivate the optimization without proving
its final default is ready.

Preserve the ongoing photo/event association and consistent next-question pool
work tracked in [Issue 41](https://github.com/bohui/copyme2.ai/issues/41), and the
independent progressive memoir persistence in
[Issue 6](https://github.com/bohui/copyme2.ai/issues/6). This specification neither
closes those issues nor changes their acceptance criteria.

Tracking uses GitHub Issues for `bohui/copyme2.ai` and the existing
`ready-for-agent` label. The specification task authorizes publication, not
implementing, deploying, or changing the running collector.
