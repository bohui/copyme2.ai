# Native contracts and domain boundaries

Baseline: `662f3563824e8c6d0a7ef5a41fa84c1e07886c7c`. The native packages preserve the existing Python routes and share the additive bearer-authenticated recovery projections introduced with this implementation. They contain no web rendering, browser storage, cookies, provider credentials, or second server receipt ledger.

## Packages

- `@memoir/contracts`: Zod runtime schemas, request/response types, stream-event validation, decimal-string positions, life-stage/locale values
- `@memoir/api-client`: injected fetch/token transport, lossless JSON integer decoding, bounded NDJSON parser, safe error mapping, retry-delay decisions
- `@memoir/memoir-domain`: pure turn reducer, owner/project/attempt fencing, immutable logical-turn outbox helpers, locale/stage/date/sequence helpers, allowlisted deep-link resolution

All packages export `src/index.ts` for Metro/TypeScript. Incoming response objects retain optional extensions. Unknown stream event types are ignored. Known malformed events fail validation, leaving reconciliation responsible for finding authoritative state. Request schemas validate the actual accepted fields rather than manufacturing proposed endpoints or receipt fields.

## API surface

Configure `createMemoirApi({baseUrl,fetch,getToken})` with the deployed canonical base, normally `https://<origin>/api/v1/memoir`. Methods append `/agent`, `/story` and `/user` paths. Existing web `/v1` aliases remain server-owned. HTTPS is mandatory unless the app explicitly enables development HTTP. Tokens are acquired afresh for each request and never stored by the client.

| Method                                                    | Relative path                                                                  | Notes                                                                 |
| --------------------------------------------------------- | ------------------------------------------------------------------------------ | --------------------------------------------------------------------- |
| `config`                                                  | GET `/agent/config`                                                            | Public config, no bearer required                                     |
| `profile`, `updateProfile`                                | GET/PATCH `/agent/profile`                                                     | Dedicated explicit conversation-language/profile settings             |
| `workspaceProfile`                                        | GET `/user/profile`                                                            | Account-wide workspace snapshot                                       |
| `projects`                                                | GET `/user/projects`                                                           | Canonical saved project snapshots, decimal positions and policy epoch |
| `history`                                                 | GET `/user/projects/{project}/history`                                         | Authorized exchanges, opaque older-page cursor                        |
| `sourceDetail`                                            | GET `/user/projects/{project}/sources/{uuid}?expected_version=…`               | Current authorized narrator evidence; revoked 410, stale citation 409 |
| `turnReceipt`                                             | GET `/agent/turns/{client_turn_id}?project_id=…`                               | Read-only recovery projection, no new ledger                          |
| `turn`, `streamTurn`                                      | POST `/agent/turn`                                                             | Same current TurnInput body                                           |
| `greeting`, `streamGreeting`                              | POST `/agent/greeting`                                                         | Bounded `begin` / `continue`, assistant-only                          |
| `conversations`                                           | GET `/user/conversations`                                                      | Existing compatibility attachment/account view                        |
| `storyState`, `readiness`                                 | GET `/story/state`, `/story/readiness`                                         | Server quota/entitlement, project readiness                           |
| `privateDraft`, `retryPrivateDraft`                       | GET `/story/private-draft`, POST `/story/private-draft/retry`                  | Canonical host-authorized composer lanes                              |
| `collection`, `updateCollection`                          | GET/PUT `/agent/collection/{project}`                                          | Revision-fenced collection, account-wide authorized sources           |
| `organiseCollection`, `collectionTask`, `task`            | Existing `/agent/collection/{project}/organise`, `/tasks`, `/agent/tasks/{id}` | Explicit readiness and server entitlement                             |
| `transcribe`, `questionAudio`                             | POST `/story/transcriptions`, `/story/question-audio`                          | Current bounded base64 compatibility APIs                             |
| `prepareTransfer`, `attachTransfer`                       | POST `/user/conversation-transfer`, `/attach`                                  | Existing idempotent guest capability protocol                         |
| `placeJourney`, `familyContext`, `events`, `correctEvent` | Existing agent/story paths                                                     | Server-authorized workspace/read and event correction                 |
| `placePhotos`                                             | GET `/agent/places/{project}/photos`                                           | Shared v8 photo pipeline; metadata preserved verbatim                 |

Profile preferences and workspace state have different semantics. No generic workspace write is substituted for the explicit profile-language route. Collection sources are account-wide by current design: a native project filter must not silently narrow or relabel the server's available source set. Readiness measures context volume, not truth, quality, completion, or consent.

## Streaming and authoritative save

`streamTurn(command, {onEvent, signal?})` resolves a `{terminal: 'result' | 'error' | 'eof', result?}` outcome. It does **not** automatically retry a mutation. JSON fallback is validated and emitted as one `result`. NDJSON handles arbitrary byte fragmentation, split Chinese/emoji, CRLF and a final complete line without newline. The defaults bound each line to 1 MiB, the whole stream to 32 MiB and events to 20,000. Malformed UTF-8, malformed known events, oversized streams and incomplete JSON all fail closed. EOF has no save meaning.

Capture `{ownerId,projectId,clientTurnId,generation}` when admitting each request and pass that exact context with every reducer action. New account/project/attempt state invalidates older callbacks. Server project and runtime turn IDs are checked additionally when present. `generation` is a client attempt fence, not a server sequence.

- `text_delta` updates provisional display
- `reply_complete` closes the displayed reply but does not mark saved
- `conversation_saved` establishes durable conversation commit independently of enrichment
- `place_preview` remains ephemeral and never mutates committed workspace state
- `workspace_update` merges optional enrichment; older exact source positions cannot overwrite later ones
- `workspace_error` never retracts a saved conversation
- A full successful result with durable memory, or cached `conversation_saved:true`, is authoritative; a quota result with `reply:null` is not
- A receipt's `server_turn_id` is a saved memory ID and differs from the stream runtime `turn_id`
- Source acceptance without saved exchange stays uncertain
- A withdrawn source or a source version above 1 sets `replayBlocked:true`; controllers must stop before sending the old outbox command. Tombstones and corrections cannot be undone by a retry
- A saved receipt can have `reply:null` after a source correction/revocation. The reducer clears the displayed reply and sets `contentUnavailable:true` while retaining the durable commit state

Stopping a stream is not a rollback. Reconcile using the scoped receipt and refreshed authorized history before offering a replay. `not_found` is a point-in-time read, not proof that server generation has stopped. Existing server replay does not yet provide atomic whole-body hash admission; the native client therefore enforces immutable original command replay but does not advertise stronger server guarantees.

## Exact integers and dates

Wire JSON is scanned before native `JSON.parse` converts numbers: oversized integer lexemes become strings. This preserves existing nanosecond `source_sequence` values. Sequence comparison uses decimal length/lexical ordering, never `Number`, and rejects already-rounded unsafe numeric input. Other integer fields such as revision reject unsafe values instead of guessing.

`formatDateExpression` is a characterized port of the web pure date helper. Exact machine dates are localized; expressions such as “the late 1960s”, ranges and uncertain dates remain unchanged. Display formatting must never be written back as invented source precision. UI locale and interview language remain separate choices.

## Outbox and errors

`createTurnOutboxItem` requires an owner, matching project, stable client UUID and injected SHA-256 function. The item retains both parsed command and canonical payload JSON/hash. `assertReplayPayload` rejects any command change after process restart. `SecureOutboxStore` requires an owner/environment-scoped encrypted adapter; the domain package does not pretend ordinary SQLite/AsyncStorage is encrypted. Persist before first send. Bearer tokens are absent from the item and acquired only at execution.

401 pauses for authentication; 409 requires snapshot/receipt reconciliation; 422 requires input correction; 429 honors `Retry-After`. Bounded jittered backoff is available only for explicitly idempotent operations. Error objects retain safe codes/request IDs, not raw provider messages, bodies or story text. The transport deliberately performs no hidden retry, including quota/provider setup failures.

## Native turn controller

`TurnController.enqueue(command)` resolves only after a durable outbox write. Clear the composer after that boundary, then call `runQueued(item)`. The `send(command, {onQueued})` convenience method provides the same ordering. Same-project pending work blocks new logical commands, and `hasPending(projectId)` exposes that guard to the UI. Concurrent enqueue calls are serialized; reusing an ID with changed content cannot overwrite the original.

`check(item)` is for launch/foreground recovery and only reads the receipt; it never sends another model request. `retry(item)` is an explicit user action, reads the latest durable retry metadata, then reconciles before at most one transmission. Duplicate retries share one operation. `source_accepted` is not account-save success; a changed/withdrawn source or mismatching narrator body blocks replay. Persisted `nextAttemptAt` enforces Retry-After even if the UI supplies an old copy of the item.

At `conversation_saved`, the controller immediately persists committed state and invokes `onSaved(item, reply, state)` without waiting for enrichment. A null/withheld receipt clears content and signals `contentUnavailable`; the UI must refresh history rather than reappend old narrator text. Terminal/revoked queue items need an explicit discard control before composing a new logical turn. `dispose()` and `cancel(operationId)` stop local delivery and preserve uncommitted work, never promise rollback, and suppress stale callbacks even if a transport ignores abort.

## Deep links

`resolveDeepLink` accepts only configured HTTPS hosts or the configured app scheme, known route shapes and allowlisted query keys. File/javascript URLs, credentials, fragments, token-bearing URLs, arbitrary redirect targets and invalid project paths are rejected. Resolution produces navigation intent only; the app must refresh owner authorization/entitlements. A payment return can only trigger a refresh. Auth callback handling additionally validates expected state, expiry and one-time consumption before a native PKCE exchange.

## Verification

`node --import tsx --test tests/mobile-domain/*.test.ts` covers byte-split Chinese/emoji, CRLF and EOF, bounded/malformed transport, exact large integers, uncommitted EOF, saved conversation plus failed enrichment, duplicate/equal/older enrichment, all context fences, 401/409/429/422, stable restart replay, revoked receipt content, unknown additive events, current API payload/path/token behavior, date characterization and hostile/deep-link callback inputs.

Native streaming, encrypted storage/key-loss behavior, microphone/media behavior and actual-device interruption/accessibility checks remain app/device gates. Passing these portable tests does not establish those native behaviors.
