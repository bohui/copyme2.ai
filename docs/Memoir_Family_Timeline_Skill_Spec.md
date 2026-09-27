# Family-tree and author-timeline Codex-harness skills

Status: reviewable implementation spec; the persistence contract is included
below and the GitHub issue is the delivery handoff for the remaining rollout
work.

This spec synthesizes the Family legacy package requirement, the existing
`memoir-place-journey` marker contract, the current server-controlled Stripe
entitlements, and the proposed `vis-timeline` plus `family-chart` presentation
libraries. It is a project-level Codex-harness feature, not a globally
installable Codex skill.

## Problem Statement

The Family legacy memoir package promises a family tree and life timeline, but
the connected Codex harness currently has no family/timeline extraction
contract. The browser has basic people and timeline workspace widgets, yet they
are not driven by the conversational agent and are currently visible after the
free chapter regardless of which memoir package the storyteller purchased.

The feature must be premium without trusting the browser or editable profile
state. It must also preserve the storyteller's uncertainty: a remembered
relationship, date, place, or life period is an assertion from the storyteller,
not an automatically verified fact. Family data is sensitive, especially for
living relatives, so inferred relationships and invented dates would be a
material privacy and accuracy failure.

## Solution

Add two project-level Codex-harness skills for the Family legacy package: one
for family-tree people/relationships and one for the author's life timeline
events/life periods. On each authenticated agent turn, the server reads the
existing paid entitlement and enables both skills only when the entitlement
represents the Family product backed by `STRIPE_PRICE_FAMILY`. Unpaid, pending,
revoked, electronic-only, and printed-only users receive neither premium skill
and cannot trigger either marker by editing their profile or request body.

When enabled, the family-tree skill extracts only explicit storyteller-grounded
people and relationship assertions using `MEMORY_SPARK_FAMILY_TREE`; the
author-timeline skill extracts explicit author events and life periods using
`MEMORY_SPARK_AUTHOR_TIMELINE`. The harness validates and removes each marker
from the spoken reply, atomically merges all valid domain updates into one
versioned user/project Family Context document in Supabase, and returns both the
persisted document and a typed update envelope with the changed skill names.
Invalid, ambiguous, or unsupported payloads are discarded without interrupting
the conversation.

The browser uses adapters over the canonical memoir records. `vis-timeline` is
the V1 timeline renderer and `family-chart` is the V1 genealogy renderer. The
underlying records remain independent of either library, so a later renderer
change does not require a data migration. The current list-based workspace is
the accessible and dependency-failure fallback.

## User Stories

1. As a Family legacy purchaser, I want the memoir companion to notice explicit family names and relationships, so that my family tree can grow while I tell the story.
2. As a Family legacy purchaser, I want explicit dates and date ranges to become timeline items, so that important life moments are easy to revisit.
3. As a storyteller, I want the tree and timeline to preserve phrases such as “around 1970” or “when I was young”, so that uncertainty is not rewritten as false precision.
4. As a storyteller, I want the assistant to ask one concise clarification when two people or dates are ambiguous, so that the graph does not silently attach a fact to the wrong person.
5. As a storyteller, I want the assistant to avoid inferring a relationship from a name, title, photo, or cultural convention, so that the tree reflects what I actually said.
6. As a storyteller, I want spouse, parent, child, sibling, adoption, step, and other relationship assertions to remain distinguishable, so that complex families are represented honestly.
7. As a storyteller, I want remarriage and multiple partners to be supported without flattening the graph into an org chart, so that the model matches real family structures.
8. As a storyteller, I want a person mentioned in separate turns to be reconciled only when the match is clear or I confirm it, so that similarly named relatives do not merge accidentally.
9. As a storyteller, I want each generated person, relationship, and event to retain its source memory and confidence/precision metadata, so that I can review where it came from.
10. As a storyteller, I want living-relative visibility and print inclusion to remain explicit, so that a private person is not exposed by a convenient visualization default.
11. As a non-Family purchaser, I want ordinary memoir conversation to work without family-tree or timeline extraction, so that the premium feature is not activated before purchase.
12. As a non-Family purchaser, I want the browser not to expose Family workspace tabs or premium agent markers, so that package boundaries are clear and enforceable.
13. As a purchaser whose payment is pending, failed, or revoked, I want the premium skill disabled until the entitlement is settled again, so that a redirect or stale browser state cannot grant access.
14. As a purchaser, I want a webhook-confirmed payment to activate the feature without a manual refresh of the model configuration, so that entitlement changes take effect on the next agent turn.
15. As a purchaser, I want a refund or revocation to hide new premium interactions without deleting my already-saved records, so that access control and data retention remain separate decisions.
16. As a storyteller, I want selecting a timeline event to reveal its linked people, places, memories, photos, and recording when those assets are authorised, so that the modules feel like one memoir workspace.
17. As a storyteller, I want selecting a person to reveal their confirmed and uncertain connections, so that I can correct the tree without losing the original assertion.
18. As a storyteller, I want the visualizations to have a readable list fallback when JavaScript, a third-party library, or a large graph makes the canvas unavailable, so that the information remains usable.
19. As a keyboard and screen-reader user, I want the Family and Timeline surfaces to expose names, dates, relationship labels, uncertainty, and controls in semantic HTML, so that the premium workspace is accessible beyond the diagram.
20. As a storyteller, I want empty, loading, invalid-marker, and no-entitlement states to explain what is happening without revealing internal model or payment details, so that the conversation remains calm and understandable.
21. As a developer, I want to replace `family-chart` or `vis-timeline` later without changing canonical memoir records, so that library licensing or product needs do not force a domain rewrite.
22. As an operator, I want the premium gate to be testable independently of the browser, so that a client cannot bypass the Family purchase requirement by calling the agent endpoint directly.
23. As an operator, I want the entitlement provenance to identify the configured Family Stripe price when one is present, so that a different price or forged metadata cannot activate the skill.
24. As a reviewer, I want the machine marker removed before the spoken response is stored or displayed, so that implementation details and raw structured payloads never leak into the memoir conversation.
25. As a reviewer, I want malformed or over-broad payloads rejected as a whole, so that one invalid relationship or unsafe field cannot partially mutate the family graph.
26. As a Family legacy purchaser, I want the family tree and timeline to survive a page refresh, so that the workspace reflects saved context rather than transient browser state.
27. As a Family legacy purchaser, I want the assistant to tell the workspace whether a turn changed the saved context, so that the UI can refresh only when a persisted revision changes.
28. As a storyteller, I want Family/Timeline records isolated to my authenticated account and project, so that another user or project cannot read or overwrite them.
29. As a developer, I want a versioned persisted output schema, so that the workspace can render the same document independently of the model marker and visualization libraries.

## Implementation Decisions

- Add two project-level Family legacy harness skills beside the existing
  place-journey skill: `memoir-family-tree` and `memoir-author-timeline`. They
  are loaded conditionally by the server runtime; they are not copied into the
  global Codex skill directory.
- Keep the activation decision server-controlled. The agent runtime must read
  the authenticated user's entitlement through the existing RLS-safe boundary,
  and the worker payload must carry a server-derived Family-feature flag or
  equivalent scoped capability. The browser, profile JSON, prompt text, and
  request body are never authoritative for activation.
- Treat a paid entitlement as Family-enabled only when its status is `paid`,
  its plan maps to the Family legacy package, and its payment provenance
  matches the configured `STRIPE_PRICE_FAMILY` when that price is configured.
  Credential-free local fallback may use the existing plan mapping, but live
  Stripe configuration must retain enough price provenance to distinguish the
  Family price from other products.
- Preserve the existing entitlement flags (`family_tree`, `timeline`, and
  `expanded_details`) as the public feature decision. The two Family skills
  require both tree and timeline capability; neither may infer access from a
  client copy of `payment_features`.
- Use one bounded marker per domain for the premium turn result. The
  family-tree marker is limited to people/relationships; the author-timeline
  marker is limited to timeline/life-period records. Both are additive updates,
  while the persisted response field is the canonical `family_context`
  document. The visible reply remains ordinary concise memoir prose.
- The marker schema uses storyteller-facing date expressions and precision
  values rather than forcing ISO dates. A single date, a range, an approximate
  date, an age-based expression, and an unknown date remain distinguishable.
- Person records contain a server identity, display name, optional aliases and
  family title, optional birth/death expressions, living-status metadata,
  visibility, and print-inclusion policy. Relationship records contain two
  person references, a relationship type, optional maternal/paternal label,
  assertion status, and source references. Timeline records contain a title,
  date expression, precision, optional place, linked people, visibility, and
  source references. A life period may represent a range without becoming a
  second event.
- Model-generated IDs are temporary correlation keys inside one domain marker. A
  marker can revise an existing canonical record only with an explicit
  `existing_id`; otherwise the server creates a deterministic canonical id for
  that update. The server resolves graph references, applies an idempotent
  additive update, and never merges similarly named relatives by inference.
  The skill never replaces the complete graph from one model response.
- Store one `user_family_context` document per authenticated Supabase user and
  Memoir project. The document is versioned and directly renderable with
  `schema_version`, `project_id`, `revision`, `updated_at`, `people`,
  `relationships`, `timeline`, and `life_periods`. People, relationships,
  timeline items, and life periods use canonical ids; the latter three retain
  uncertainty, visibility, and print-inclusion fields from the marker.
- Return a `family_context_update` envelope alongside the document. It carries
  `schema_version`, `project_id`, `changed`, `persisted`, `revision`, a `skills`
  array containing `family_tree` and/or `author_timeline`, and per-collection
  `added`/`updated` counts; it is `null` when a turn emits no valid domain
  marker. The workspace hydrates through the authenticated read endpoint and
  renders the returned document directly.
- Use an RLS-scoped database RPC for the write. It verifies the expected
  revision, increments the revision only when canonical records change, stamps
  the update time, and compares records without transport metadata so replayed
  turns do not duplicate data.
- Marker validation is all-or-nothing per domain and follows the place-journey
  pattern: extract the first bounded marker for each skill, parse JSON, validate
  field types, lengths, enum values, graph references, and payload size, then
  remove all control markers from the visible reply. Invalid markers are
  dropped and produce no write for that domain.
- The skill instructs the model to use only explicit storyteller statements.
  It must keep uncertainty, ask for clarification when needed, and never infer
  family relationships from public context, photographs, surnames, geography,
  or cultural assumptions. Public historical references remain separate from
  personal claims.
- The browser receives the same agent-turn response shape whether the feature
  is absent or enabled. With no entitlement, `family_context` is null and both
  Family skills are absent. With a valid entitlement, the browser hydrates the
  persisted document and exposes Family and Timeline tabs. Existing chapter,
  place, picture, and delivery surfaces are unaffected.
- Keep the existing legacy people, relationship, and timeline routes as the
  backwards-compatible domain adapter during this change. The new premium
  browser surfaces and Codex extraction are gated first; any later API-wide
  entitlement enforcement must be a separate migration with its own compatibility
  decision.
- Use `vis-timeline` and `family-chart` only as presentation adapters. The
  browser must render a semantic list fallback and preserve the current
  uncertainty labels when either dependency fails or is unavailable.
- Do not use Knight Lab TimelineJS for this feature. Do not introduce a paid
  genealogy library for V1. A later BALKAN evaluation is out of scope for the
  initial implementation.
- Keep family/timeline records private by default, preserve existing visibility
  and print-review controls, and never place raw payment identifiers or private
  addresses in the model marker or browser trace.

## Testing Decisions

- The primary test seam is the authenticated agent-turn boundary. Tests should
  exercise entitlement lookup, conditional skill inclusion, worker propagation,
  marker validation/stripping, and response fields using external behavior.
  They should not assert prompt wording beyond the presence/absence of the
  contract needed for the behavior.
- Add paid and unpaid runtime tests modeled on the existing place-journey and
  Codex worker tests. An unpaid or revoked entitlement must not receive Family
  instructions, must not return `family_context`, and must not persist a
  marker-shaped request as premium data.
- Add a webhook/entitlement test that activates Family only for a verified
  `STRIPE_PRICE_FAMILY` purchase and rejects a different or missing price
  provenance when live price configuration is enabled.
- Add parser tests for a valid mixed payload, a hierarchy with multiple spouses
  or parent branches, uncertain date expressions, ambiguous/unknown references,
  oversized fields, malformed JSON, duplicate IDs, and an unterminated marker.
  The visible reply must remain free of the marker in all valid and invalid
  cases.
- Add an idempotency test that replays the same valid marker and confirms that
  it does not duplicate people, relationships, or events.
- Add a persistence-contract test that verifies canonical ids, revision
  increments, explicit `existing_id` revisions, the update envelope, and the
  user/project read boundary. Test that a stale expected revision is rejected
  and that an unpaid request cannot read the Family document.
- Add browser contract tests at the existing workspace seam: Family and
  Timeline tabs are absent without the entitlement, appear after a confirmed
  Family state, and fall back to semantic list content when the visualization
  library cannot load.
- Add an acceptance test that selects a timeline event and verifies linked
  people/place/memory references remain within the storyteller's project and
  respect visibility/print flags.
- Preserve the existing legacy route tests while the compatibility adapter
  remains in place. New tests must make the premium activation boundary
  explicit rather than silently changing those older route assumptions.

## Out of Scope

- Creating or changing the Stripe product, price, Checkout UI, merchant
  account, refund policy, or webhook registration.
- Replacing the existing memoir domain model with a new genealogy database.
- Automatically importing a family tree from public genealogy sources,
  photographs, names, or historical context.
- Exact geocoding of homes, schools, workplaces, or other private addresses.
- Full editing, undo/redo, search, export, minimap, lazy-loading, or premium
  genealogy features beyond the V1 adapters and accessible fallback.
- A paid BALKAN FamilyTreeJS integration or a Knight Lab TimelineJS integration.
- Print-layout redesign, new publication formats, or changes to chapter
  entitlement accounting beyond the Family feature gate.
- API-wide removal or entitlement gating of the existing legacy people and
  timeline routes.
- Automatic deletion of saved family/timeline records after refund or
  revocation.

## Further Notes

- The current Family package already advertises “Family tree” and “Life
  timeline,” and the payment code already maps the package to
  `STRIPE_PRICE_FAMILY`; this work closes the gap between that commercial
  entitlement and the Codex/browser behavior.
- The place-journey marker is the transport precedent. The two Family markers
  are ephemeral until their validated payloads are applied to the authenticated
  user/project document, just as a place journey is not proof of a
  biographical address.
- The GitHub issue should use the repository's `ready-for-agent` label and
  link back to this spec as the implementation handoff.
