# Location identity and workspace regression checks

The existing extraction call receives compact saved-place hints and keeps the
current message's source wording. Backend identity matching then handles optional
Chinese city/province suffixes within the same full hierarchy. A second model
deduplication call is unnecessary for that rule; unfamiliar aliases or uncertain
containment remain subject to extraction and clarification.

`tests/evaluation/place_identity_cases.json` contains eight synthetic cases:
short/full city repeats, a new child place, two children in one response, the same
name in different regions, a county distinct from its city, a saved-photo response
without a location cue, and explicit location uncertainty. Inputs, prior context,
expected geographic identities and representative raw marker outputs are separate.
No private storyteller conversation is included.

The checked-in `place_identity_model_outputs.json` records actual extraction
responses from the configured `gpt-5.6-luna-pooled` model. All eight pass the
same scorer in CI. Two initial gold failures were resolved by verifying the
optional 双桥区 parent of 大石庙镇 against the dataset's government source;
the raw model responses were retained unchanged.

Run the deterministic scoring checks:

```sh
python3 -m pytest tests/test_place_identity_evaluation.py tests/test_place_geocoding.py tests/test_place_journey.py tests/test_place_groups.py -q
python3 scripts/evaluate_place_journeys.py --output output/evaluation/place-identity-recorded.json
```

The default runner replays recorded marker fixtures. That verifies parsing,
grounding, identity and the scorer; it does not establish live model quality.
The scorer also rejects missing places, fabricated saved-place cues, malformed
markers, duplicate city aliases and a city centre copied as a child pin.

Run actual model extraction through the configured production worker:

```sh
python3 scripts/evaluate_place_journeys.py --live --worker-url http://127.0.0.1:8766 --output output/evaluation/place-identity-live.json
```

Use a reachable worker URL; the local compose worker is private by default.
The worker secret and model configuration come from the environment or `.env`.
`--case-id` selects cases, `--model` compares an explicitly selected model, and
`--timeout` bounds each case. Requests run sequentially against synthetic inputs,
with no storyteller database writes, photo lookup or geocoding. The runner uses
the actual workspace extraction and its existing focused recovery path.
Receipts retain raw model responses, per-check results and the configured model.
Worker request counts measure application contacts, not upstream billing or tokens.

The browser and JavaScript regressions separately cover workspace retention during
unmapped locations, the fifth-round draft, reload, manual collapse/reopen, and
composition unlock. Google key authorization is a separate deployment setting;
provider rejection must not remove the workspace.
