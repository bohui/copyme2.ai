# Memory Spark acceptance evidence

Generated: `2026-09-23T12:00:13.015286+00:00`

This report runs the 55 functional and adversarial acceptance cases from section 26.2 of `Memory_Spark_Full_Specification_v1.0.docx` against the credential-free local deterministic cell.

Command: `/opt/memory-spark-venv/bin/python -m pytest -q tests/test_full_acceptance.py`

Result: **55/55 acceptance cases passed**.

| Case | Scenario | Result |
|---|---|---|
| AT-001 | self and family setup allow unknown profile without debit | PASS |
| AT-002 | invitation preview acceptance expiry and replay | PASS |
| AT-003 | payment does not replace storyteller assent | PASS |
| AT-004 | recovery and support access are verified scoped and audited | PASS |
| AT-005 | standard and photo first sessions respect selection policy | PASS |
| AT-006 | helper pause resume keeps participant prompt and upload state | PASS |
| AT-007 | cue reaction without story does not create claim or charge extra | PASS |
| AT-008 | skip muted topics and private progress redaction | PASS |
| AT-009 | twenty concurrent completions consume one unit | PASS |
| AT-010 | validated upload survives session reopen without duplicate source | PASS |
| AT-011 | invalid or oversize media is rejected before processing | PASS |
| AT-012 | config exposes capture fallbacks when mic or codec is unavailable | PASS |
| AT-013 | chunk order duplicate and finalize replay are safe | PASS |
| AT-014 | source correction creates new version and preserves original | PASS |
| AT-015 | diary and photo metadata preserve source dates authorship and sides | PASS |
| AT-016 | context search sends only coarse queries and fails closed on outage | PASS |
| AT-017 | context labels keep scene date and broad match scope | PASS |
| AT-018 | embed only video is not downloadable or printable | PASS |
| AT-019 | context is capped and reactions stay project private | PASS |
| AT-020 | rights revocation blocks new editions and marks dependents | PASS |
| AT-021 | untrusted context text cannot invoke tools or cross project exports | PASS |
| AT-022 | cross project evidence is rejected at build and edit boundaries | PASS |
| AT-023 | approximate low confidence dates remain uncertain and reviewable | PASS |
| AT-024 | conflicting accounts are attributed and stale existing chapters | PASS |
| AT-025 | archival and quote blocks require provenance | PASS |
| AT-026 | people and relationships preserve unknown and adoptive semantics | PASS |
| AT-027 | person merge requires review and is reversible | PASS |
| AT-028 | hidden living relative and approximate timeline do not leak to print | PASS |
| AT-029 | outline and short chapter can publish before all allowance is used | PASS |
| AT-030 | unsupported detail is flagged then removed by editor | PASS |
| AT-031 | concurrent chapter edits require expected revision | PASS |
| AT-032 | translation preserves uncertainty and goes stale after source correction | PASS |
| AT-033 | unlicensed historical sidebar is excluded without blocking personal narrative | PASS |
| AT-034 | six prechapter completions replay and gate after first chapter | PASS |
| AT-035 | declined payment keeps preview and owned source export available | PASS |
| AT-036 | server price signed webhooks and order state are idempotent | PASS |
| AT-037 | sponsored purchase adds capacity without membership | PASS |
| AT-038 | refund revokes unused capacity and print cancellation is separate | PASS |
| AT-039 | bilingual editions freeze exact versions and render all formats | PASS |
| AT-040 | preflight blocks missing glyph layout and changed artifacts until reapproval | PASS |
| AT-041 | audio resolver checks expiry and revocation without recalling printed codes | PASS |
| AT-042 | print quotes enforce quantity supplier format and expiry | PASS |
| AT-043 | supplier file change invalidates customer proof approval | PASS |
| AT-044 | supplier package is qualified and contains only final files | PASS |
| AT-045 | unknown supplier submission blocks duplicate submit | PASS |
| AT-046 | finance operations can reconcile without editorial content access | PASS |
| AT-047 | disabling provider rights or supplier fails new work without erasing history | PASS |
| AT-048 | cross project ids sse replay and downloads do not leak private data | PASS |
| AT-049 | ssrf injection and embedded document content are denied or escaped | PASS |
| AT-050 | unapproved overseas provider is never used as fallback | PASS |
| AT-051 | deletion tombstone blocks late job writes and survives snapshot restore | PASS |
| AT-052 | operations events and audit do not target sensitive story content | PASS |
| AT-053 | nfr benchmark records real local latency evidence | PASS |
| AT-054 | recovery state keeps outbox and tombstone boundaries | PASS |
| AT-055 | concurrency and storyteller accessibility contract are exercised | PASS |

The test evidence uses deterministic providers and an explicit in-memory store. It proves the documented functional behavior, permissions, idempotency and failure guards; Supabase PostgreSQL durability is verified separately by the configured database check and is not exercised by this credential-free suite.

The full repository suite and the section 19.2 route audit are run separately by `make harness-check` through the Codex exec-server in Apple Container + Mocker.
