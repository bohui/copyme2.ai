# Fast conversational streaming with independent workspace updates

Status: reviewable draft; testing-seam confirmation pending before issue publication.

## Problem Statement

Mira takes too long to ask the next question after a storyteller sends a message. Streaming transport exists, but the same model turn generates conversational prose and hidden profile, place-journey, and Family metadata. Context reads and Codex startup precede generation; artifact synchronization and workspace persistence precede the final turn result. The browser treats that result as the end of the operation and only then applies workspace changes and starts public-reference photo lookup.

The storyteller should not have to wait for a map, photos, or profile processing before continuing the conversation. Faster token animation alone does not solve the delay before the first meaningful response or the blocked interval after the question appears.

## Solution

Stream one brief, grounded acknowledgement and one natural follow-up question through a dedicated conversational path. Process workspace enrichment independently from the same accepted storyteller message. Show place journeys, public references, and other permitted workspace updates as they become ready, without interrupting the response or the next answer.

For example, after a storyteller mentions 承德, Mira can ask about a remembered street while an approximate place journey and public reference pictures load beside the conversation. The reply must not claim that an image or map is already displayed before the workspace confirms it.

## User Stories

1. As a storyteller, I want the fixed introduction to stream immediately, so that opening a conversation does not wait for an agent turn.
2. As a storyteller, I want meaningful reply text to begin promptly after I send an answer, so that the interview feels responsive.
3. As a storyteller, I want one concise follow-up question, so that I can stay with my memory without processing several questions at once.
4. As a storyteller, I want the question grounded in my latest message and relevant conversation history, so that speed does not make Mira generic or repetitive.
5. As a storyteller, I want the reply to stream progressively, so that I can start reading before generation finishes.
6. As a storyteller, I want map preparation to continue while Mira replies, so that place processing does not delay the conversation.
7. As a storyteller, I want public reference pictures to arrive independently, so that a slow image search does not hold up a question.
8. As a storyteller, I want profile extraction to happen quietly in the background, so that the interview does not become a form.
9. As a storyteller, I want to send my next answer once the previous exchange is safely saved, so that unfinished workspace work does not block me.
10. As a storyteller, I want Mira to understand my newest answer even if background extraction is incomplete, so that conversational continuity is preserved.
11. As a storyteller, I want incoming workspace updates to preserve my draft, so that I do not lose the answer I am typing.
12. As a storyteller, I want incoming workspace updates to preserve focus and reading position, so that they do not interrupt the conversation.
13. As a storyteller, I want a small loading indication in the relevant workspace area, so that I can distinguish pending content from an empty result.
14. As a storyteller, I want the reply to stop showing as generating when its text is complete, so that workspace processing is not confused with Mira thinking.
15. As a storyteller, I want earlier useful workspace content to remain visible while replacement content loads, so that the workspace does not flash empty.
16. As a storyteller, I want a newer place cue to stay selected when an older lookup finishes, so that late results do not take me back to the wrong place.
17. As a storyteller, I want corrections to supersede older extracted information, so that background completion order does not undo what I just said.
18. As a storyteller, I want results restricted to their conversation, so that switching projects does not show unrelated places or pictures.
19. As a storyteller, I want saved workspace results to survive reloads, so that I do not need to repeat a place cue.
20. As a storyteller, I want reconnecting to recover accepted work, so that a temporary network failure does not duplicate my answer or lose saved context.
21. As a storyteller, I want workspace failures to leave a successful reply intact, so that an optional lookup does not make the interview appear to have failed.
22. As a storyteller, I want failed workspace work to be retryable without resending my story, so that I do not receive duplicate questions.
23. As a storyteller, I want an actual reply or save failure to be clearly distinguished from a photo failure, so that I know whether my exchange was retained.
24. As a bilingual storyteller, I want original place names preserved in place cues, so that 承德 is not rejected merely because Mira replies in English.
25. As a storyteller, I want public references labelled with their source and available date information, so that I do not mistake them for personal evidence or exact-period photographs.
26. As a storyteller, I want ambiguous places clarified, so that a fast response does not invent a location.
27. As a Family storyteller, I want eligible family and timeline updates to arrive independently, so that their processing does not delay my interview.
28. As a storyteller, I want private context and workspace results restricted to my authorized account, so that background execution preserves existing privacy boundaries.
29. As a keyboard or assistive-technology user, I want stable controls and restrained progress announcements, so that streaming and workspace updates remain usable.
30. As an operator, I want separate measurements for first text, completed question, saved exchange, and workspace readiness, so that I can identify the actual source of delay.
31. As an operator, I want bounded, deduplicated background work, so that retries and rapid turns do not create unlimited model calls or duplicated results.
32. As an operator, I want timing and failure evidence from the deployed container stack, so that a passing test against a different local process does not conceal a production-path regression.

## Implementation Decisions

The following decisions specify the proposed implementation synthesized from this discussion; they are not a claim that it has already been built.

- **Two independent paths:** accept and identify the storyteller turn once, then schedule conversational generation and workspace enrichment independently. Workspace analysis must not depend on the completed assistant question, and conversational generation must not wait for enrichment output.
- **Conversation scope:** the fast request generates visible interview prose only. Supply the current original message, a bounded recent conversation, and relevant already-available context. Exclude workspace extraction contracts and large unrelated context from this request. Preserve conversation language, low-pressure interviewing, and one-question behavior.
- **Required context:** retain any context necessary to answer correctly. For a normal follow-up question, pending map, photo, profile, or Family extraction is optional. If the storyteller explicitly asks about a pending tool result, acknowledge that dependency rather than fabricate an answer before it exists.
- **Worker execution:** preserve the private Codex worker boundary. Independent model jobs must not concurrently write the same Codex thread or mutable runtime home. Introduce separately owned execution state for enrichment, or a stateless provider execution path behind the same private boundary. Reusing a shared per-user lock that serializes both paths would defeat the feature and is not acceptable.
- **Conversation ownership:** conversational turns remain serialized within the applicable conversation/session boundary. A completed and durably saved exchange releases its conversational lease without waiting for enrichment. The next request includes authoritative recent messages even when extracted profile state lags behind.
- **Durable acceptance and enrichment:** assign a server turn ID and monotonic conversation sequence to accepted input. Persist enrichment intent durably so disconnects or restarts cannot silently discard it. Reuse existing task infrastructure where appropriate, but do not disguise model extraction as a deterministic artifact task. Add explicit enrichment job kinds, ownership, retries, and status.
- **Persistence boundaries:** the current fenced turn commit couples conversational memory with artifact references. Separate durable exchange acceptance/save from asynchronous artifact and workspace completion using explicit statuses and recoverable job intent. Do not acknowledge an exchange as saved based solely on streamed text, and do not hold the conversation lease until every artifact upload finishes. Document the transaction/reconciliation boundary if Supabase exchange state and the existing local task store cannot be committed atomically; enqueueing failure must remain discoverable and retryable.
- **Event contract:** extend the current NDJSON transport with distinct events for accepted turn, text delta, reply completion, conversation save, workspace update, and workspace failure. Every event carries its project and turn identity; persisted workspace events also carry a component revision and source-turn sequence. Reply completion denotes complete text; conversation save denotes durable success. Neither denotes completion of every workspace component.
- **Delivery after reply:** workspace delivery must remain available after the conversational request ends. Provide an authenticated project-scoped update stream with a replay cursor and a snapshot/status fallback. The browser subscribes independently of submitting a new turn. Reconnect from the last applied cursor and reconcile against the persisted snapshot when replay history is unavailable.
- **Incremental rendering:** deliver a validated, saved place journey as soon as it is ready and trigger public-reference lookup independently. Profile and entitled Family updates can arrive separately. No combined final workspace payload should delay an already-ready component.
- **Stale completion handling:** enforce revision/source-turn checks in persistence as well as in the browser. Older results may enrich their original history entry, but may not replace newer current selections or overwrite newer explicit corrections. Apply profile updates by validated fields and source versions, not whole-profile replacement.
- **Ownership and ordering:** deduplicate jobs and delivery using owner, project, source turn, component, and processing version. Retry an existing operation rather than create duplicate messages or model jobs. Validate project ownership and Family entitlements at execution and delivery; never accept an owner identifier from model output.
- **UI state:** keep reply generation, conversation saving, and workspace processing separate. Enable sending after conversation save, even while workspace work continues. Pending workspace status belongs in the affected panel. A workspace failure must not mark a successful assistant reply as failed. Existing draft text, focus, scroll, and user-selected history remain stable during background renders.
- **Place and reference continuity:** preserve the existing distinction between place cue, place journey, workspace, and public reference. Keep the place label grounded in the original current-message script, including Chinese input with an English response. Do not activate a new project from an unrelated saved user-level place. Retain attribution and indicate when public images are broader place references rather than exact-period matches.
- **Failure and lifecycle:** give enrichment bounded timeouts and retries, and recover accepted jobs after process restarts. Navigation cancels the page's subscription, not already-accepted durable work. Logout removes local access; background execution must use an authorized durable execution mechanism rather than depending indefinitely on an expiring browser token. Do not broaden service-role access as an incidental shortcut.
- **Latency measurement:** record input accepted, conversational dispatch, first model delta, first rendered text, reply complete, conversation saved, and each workspace component ready/applied. Compare first-text and question-completion distributions against the current implementation on the same model, deployment, and representative inputs. Demonstrate zero dependency on artificially delayed enrichment. No absolute millisecond target or replacement model has been agreed; record baseline and measured improvement before selecting further startup, context, or model optimizations.
- **Deployment:** ship matching API, private-worker, and web event contracts together or preserve backward compatibility during rollout. Verify the running container versions and avoid parallel temporary processes occupying the same host ports. Preserve the existing fixed introduction and its zero-agent-call behavior.

## Testing Decisions

- **Proposed primary seam, awaiting confirmation:** the existing interview browser journey against the real web/API streaming boundary, with controlled model and enrichment executors at external boundaries. This is the highest seam covering both perceived response speed and correct workspace behavior. Extend the existing test harness instead of introducing a separate UI framework.
- **Good tests assert observable behavior:** hold enrichment behind a test-controlled barrier; emit conversational text; assert that text becomes visible, the reply completes, the exchange saves, and a second message can be sent before releasing the barrier. Use synchronization signals rather than long sleeps or fragile live-model timing thresholds.
- **Prior art:** existing browser streaming checks already hold the final result while inspecting partial text and split UTF-8 chunks. Interview workspace checks cover draft preservation, place history, navigation, and asynchronous photos. Place-photo browser checks cover reload recovery. Extend those behaviors with real application orchestration instead of fulfilling the complete turn response with a canned success payload.
- **Primary scenarios:** fixed opening without an agent request; partial text before enrichment; next turn while old enrichment waits; independently arriving map and photos; delayed profile and Family updates; unchanged draft/focus/scroll; repeated delivery; older-place completion after a newer correction; project switch; reload/reconnect; optional workspace failure; reply failure; and conversation-save failure.
- **Grounding scenarios:** repeat the reproduced Chinese-input/English-response case with 承德, alongside English place input and ambiguous locations. Verify the saved place journey and actual public-reference rendering; assistant prose promising a map is insufficient evidence.
- **Lower seams only where needed:** use existing authenticated API and durable-task tests for owner isolation, entitlement changes, idempotency, restart recovery, write fencing, and expired execution authorization. These cover correctness that browser visibility alone cannot establish. Do not mirror private helper implementation in tests.
- **Live acceptance:** run a bounded synthetic test against the actual localhost container stack. Confirm progressive text, a usable next-turn control before delayed workspace completion, visible place and loaded images, and persistence after reload. Record timing measurements separately from deterministic test results; external model/network speed is not a unit-test guarantee.

## Out of Scope

- Reopening the resolved place/picture regression as an unrelated UI redesign.
- Generating fake conversational filler or hardcoded follow-up questions to conceal model latency.
- Changing the fixed introductory wording, interview product flow, payment gates, or Family entitlements.
- Realtime voice transport, speech synthesis streaming, barge-in, or new speech providers.
- Selecting a different model, promising a sub-second service level, or performing a broad provider benchmark without measurements.
- Parallel mutation of a shared Codex thread/home, unlimited background agents, or a new general-purpose workflow platform.
- Changing organiser/book-generation behavior or treating public references as biographical evidence.

## Further Notes

This spec synthesizes the streaming discussion and repository state inspected on 2026-09-28. It uses the project glossary and existing Codex/Supabase and collection-task architecture. The current system already forwards model text before final persistence; the remaining proposal is to separate generation responsibilities, readiness states, and durable background execution. Merely moving photo fetches or renaming the final event would not satisfy it.

GitHub Issues for bohui/copyme2.ai is available and has the ready-for-agent label. Publish this complete specification there after the testing-seam check required by the invoked to-spec skill. No application implementation is included in this specification task.
