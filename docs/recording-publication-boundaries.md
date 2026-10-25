# Original-recording JSON publication boundaries

This inventory covers application-generated original-recording descriptors:
`descriptor(record)` and the `recordings` projections returned by
`read_user_source_recordings` / `read_user_interview_turn`. It follows their
producers through the API response adapters. Paths below are suffixes of
`/api/v1/memoir`; existing `/v1` equivalents use the same handlers.

Recording consent can change without changing a lifetime execution/read fence.
A lookup, frozen JSON body, or queued event therefore does not authorize its
later publication. The current recording authority must remain locked through
the actual ASGI header and body sends.

| JSON egress | Descriptor location / request variants | Publication boundary |
| --- | --- | --- |
| `POST /agent/turn`, including cached replay | Top-level `recordings` in ordinary JSON | `GovernedJSONResponse` and `TransactionalPublication`: original execution fence plus current recording authorization on the same transaction. |
| Streamed turn events | `data.recordings` in `source_accepted`, `result`, `reply_complete` when present, and `conversation_saved` | `send_governed` follows descriptor lists independently of event name or `more_body`. Both conversation modes retain their existing envelopes. |
| `GET /agent/turns/{turn}?project_id=...` | Top-level receipt `recordings` | Mapped reads use `ReadJSONResponse` / `ReadPublication`, preserving the original database-issued read fence. |
| `GET /user/projects/{project}/sources/{source}` | Top-level source-detail `recordings` | Same mapped read boundary; source text and citation/version checks remain in place. |
| `GET /user/projects/{project}/history` | `items[*].recordings` across the existing page | Same mapped read boundary; lock unique recording IDs in global order, retain the 20-recording bound per turn, and preserve page/order/cursor fields. |
| Owned **unmapped** variants of the preceding three reads | Same receipt/source/history fields | `RecordingReadSnapshot` / `RecordingReadPublication` add recording locks to the existing owner/project-scoped read. They create no lifetime identity or generation lease and reject a project that has become mapped before publication. |
| `GET /story/recordings/{recording}` | Singular `recording`, plus saved `asr_result` | `RecordingJSONResponse` reuses `OriginalContentResponse`'s current `recording_server_operation('read')` guard. Withdrawal before publication produces the existing recording-unavailable 404. |
| `GET /story/recordings/by-upload/{key}` | Singular `recording` | Same original-recording send guard after the existing upload-key/owner lookup. |
| `POST /story/transcriptions`: fresh upload | Audio payload, optional upload key; result has `recording`, text and source metadata | Same original-recording send guard after preservation/transcription completes. Provider and Storage authorization remain separate and unchanged. |
| `POST /story/transcriptions`: upload-key retry | Repeated audio payload and the same upload idempotency key | Same boundary; successful retries keep the recording identity and response schema. |
| `POST /story/transcriptions`: recording-ID transcription/retry | `recording_id`, including an already saved ASR result | Same boundary; cached success cannot bypass current consent at send time. |

`ReadSnapshot` / `RecordingReadSnapshot` and producer payloads remain immutable.
Filtering uses current authorized descriptors while preserving list order, other
fields, UTF-8 JSON and NDJSON framing. Response headers are sent only once the
authorized JSON length is known. Timeout, cancellation and send errors close the
owning transaction; producer work and provider requests do not run inside these
publication transactions.

Standalone recording JSON has a two-second publication deadline, leaving three
seconds for rollback/close and scheduling before consent revoke's unchanged
five-second SQL deadline. JSON close runs in a shielded task and finishes even
under repeated cancellation. The audio response keeps its existing five-second
publication deadline and cleanup behavior.

The following responses do not carry a readable recording descriptor or content
link and keep their existing authorization and recovery behavior:

- Recording-consent status/grant/revoke results contain consent state and revision.
- Delete/cancel results contain identity and cleanup acknowledgements; they must
  remain usable to remove media after withdrawal.
- Upload/transcription error details and pending-turn/replay input may retain
  `recording_id` / `recording_ids` as immutable request-recovery identities. They
  do not grant recording reads or expose a descriptor/content URL.
- Internal Storage/RPC results feed the serializers listed above and are not
  additional application JSON response handlers.

`GET /story/recordings/{recording}/content` is an audio response, not a JSON
descriptor egress. Its existing `OriginalContentResponse` send guard and the
separate Storage-read/provider guards are retained.

Native regressions live in `tests/test_recording_consent.py`,
`tests/test_recording_read_publication.py`,
`tests/test_recording_json_publication.py`, and
`tests/test_recording_legacy_publication.py`. They use disposable PostgreSQL,
synthetic WebM/M4A/WAV and controlled provider/Storage transports. Transport
regressions cover empty/missing/partially available descriptor lists, immutable
snapshots, JSON lengths, NDJSON framing, and cleanup. Existing owner, source,
policy, original-byte and retry regressions remain applicable.
