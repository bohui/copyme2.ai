# Login recovery and progressive memoir diagnosis

Observed locally on 7 October 2026. This records the reported login incident,
the recovery repairs, and the separately approved provider configuration.

## What happened

- The existing-account transfer for `project_bcb409cf0566` committed at
  `2026-10-07T09:43:41.690004Z`. All 11 guest rounds and their original sources
  were preserved. The account already had 10 rounds, so its combined allowance
  usage became 21 and the 20-round sample gate appeared.
- The interview adapter lived in the API's in-memory store. After a restart,
  the old URL could no longer load that adapter. Starting again created a new
  project and cleared the visible chat without hydrating the persisted history.
  `project_c0974e03084f` had no canonical sources or manuscript.
- The Temporal worker lacked `SUPABASE_URL` and `SUPABASE_SECRET_KEY`. Its
  runtime skipped shared memoir lane dispatch. The original interview's
  timeline and composer lanes were pending with no successful cursor or draft.

## Repairs applied to Memoir

- Return the latest saved interview ID with account history, resume that ID,
  and load history before the sample gate. Discard recovery responses after an
  account switch.
- Recreate a missing local adapter only after checking the original project
  against authenticated, owner-scoped Supabase records. Preserve its project ID
  and saved profile; repeated recovery does not create additional projects.
- Configure shared-lane dispatch on the Temporal worker. An empty project now
  returns insufficient context instead of a nonexistent job to poll.
- Give author-timeline extraction a separate low reasoning setting and log
  safe failure classes, HTTP status and elapsed time.
- Preserve a verbatim original date anchor during event extraction. Do not
  synthesize a period expression from separate quotations. Preparation must
  copy canonical evidence without adding inferred attribution or offsets.
- Draft with the exact canonical evidence spans, leave image metadata empty
  when no assets exist, and preserve the narrator's meaning without adding
  sensory details, emotions or lyrical conclusions unsupported by testimony.

These follow [Issue #6](https://github.com/bohui/copyme2.ai/issues/6): canonical
events drive five-round private checkpoints, one active run owns each lane,
and an eligible validated draft remains immediately readable during updates.

## Approved provider repair

The live provider logged `requested_effort=low enforced_effort=max`. Read-only
inspection identified the shared upstream key as `trading-gpt56-luna`, with
`enforced_reasoning_effort=max`. Both `gpt-5.6-luna-pooled` and
`legal2ai-luna-low` used `CODEX_LB_API_KEY`, so changing an application
effort or the alias alone does not bypass that policy. Three recovered timeline
attempts each timed out at about 120 seconds; a separate full-input probe using
the low alias also timed out at 180 seconds.

Applied with user authorization:

1. Created a dedicated Memoir background key for the same pooled
   `gpt-5.6-luna` model, enforcing `low` reasoning and retaining the authorized
   account scope.
2. Added a `memoir-luna-low` gateway alias using
   `CODEX_LB_MEMOIR_BACKGROUND_API_KEY` and the existing pooled backend.
3. Added that alias to the existing Memoir consumer's model allowlist and
   configured author-timeline and composer work to use it. The Temporal worker
   uses the same model setting for checkpoint fingerprints.
4. Reloaded the local services and retried the original lanes through their
   authenticated retry operations. Upstream records confirm effective `low`
   reasoning. The shared trading key retains its `max` policy.

The gateway configuration is reviewable in
[provider PR #7](https://github.com/seed2ai/llm_provider/pull/7). Credentials stay
in ignored local environment files. The user merged the provider changes to
main during verification.

The initial low-effort extraction returned in about 63 seconds but failed the
strict date-evidence check. A private diagnostic replay identified synthesized
date expressions. After clarifying the prompt, all 11 original sources advanced
the timeline cursor and eight canonical events were committed. Composer
preparation calls returned in approximately 7–18 seconds; a further private
replay identified inferred attribution, which the preparation prompt now
explicitly forbids.

Draft retries exposed whole-source citations instead of event-approved spans,
an unresolved source and nonempty image metadata on prose. A later candidate
passed schema and canonical-evidence validation, but editorial review found
unsupported embellishment and a paraphrase that changed the recollection's
meaning. It correctly remained unready. The drafting instructions now make
these evidence and empty-metadata requirements explicit.

During this verification the user intentionally reset the local containers/
volumes and Supabase application data, then asked to skip the old data check.
A read-only check found zero sources,
events, lanes, checkpoints and manuscripts for the original project. The final
drafting instructions therefore have not been verified on that live history,
and no ready saved sample was observed before the reset. The code and fixture
verification remain reviewable.

## Verification

- 108 real PostgreSQL/Temporal Issue #6 workflow checks passed using the
  disposable Apple Container PostgreSQL harness. The native PostgreSQL harness
  failed during initialization; it was not an application test failure.
- After integrating main at `b1db6a9`, 151 focused API/configuration/mobile
  checks passed. The 36-operation mobile OpenAPI snapshot matches. Three date
  evidence regression cases and the worker/model/logging checks also passed.
- 25 JavaScript history, recovery, auth reminder and preview polling checks
  passed on the isolated PR contents.
- Two browser recovery checks passed against the rebuilt frontend and real
  recovery/history/sample routes, with fixtures for external auth/storage.
  Eligible saved-sample responses took 7.3 ms and 3.8 ms in those fixtures.
- The production frontend build passed. API/frontend and internal worker
  connectivity returned HTTP 200 after the local stack was recreated together.
- After the final drafting-instruction change, 74 preview, canonical-provenance
  and lane-logging checks passed.

The fixture timings verify immediate saved-draft retrieval, not live model
generation latency. This incident required a first catch-up run because no
earlier five-round checkpoint had been dispatched. Future accepted inputs use
the existing progressive lane and saved eligible drafts remain readable during
updates.

## Review repairs on main

After PR #27 was merged, independent review reproduced private-profile access
through the local account header and failure to resume attachment-only legacy
history. The user requested these repairs directly on main, preserving the
merged voice work and without further live/provider/data-reset actions.

- Recovery uses the verified Supabase principal for ownership and restricts
  restored interviews to that storyteller. Recovered self interviews enforce
  that identity on project and indirect resource access, including audio,
  order and supplier-update routes. Valid audio-share tokens and verified payer
  access retain their existing contracts.
- Every explicitly bearer-created adapter retains its authentication contract.
  Family adapters allow verified members; recovery itself still requires exact
  immutable owner equality when a local ID already exists. Unbound local ID
  collisions fail without copying a private profile or overwriting local work.
- Creation replay cannot bypass identity through the idempotency cache. Request
  identities are isolated between concurrent requests and prototype cookies
  cannot replace Supabase authentication.
- Owned conversation attachments are accepted as legacy recovery evidence.
  The frontend sends the current session for protected adapters, recovers an
  authenticated cached link, and avoids carrying that token into fresh adapter
  creation or prototype authentication requests.
- The mobile OpenAPI snapshot now matches the already-merged voice DTOs, whose
  optional voice/instructions fields permit null and use configured defaults.

Verification: the first ownership suite reproduced 18 failures before the
repair. The final ownership/recovery suite passed 39 checks; 182 broader API,
acceptance, security, speech and mobile-contract checks passed, as did all 160
JavaScript checks and the production frontend build. Browser recovery covers
both saved links and the landing page for canonical memories and legacy
attachments, without forwarding synthetic credentials on behalf of the UI.
These checks use fixtures and do not assert restored live history or provider
generation latency after the intentional reset.
