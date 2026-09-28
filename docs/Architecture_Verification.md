# Architecture diagram verification

The Archify diagram reflects the local five-service stack and the implemented
collection/organiser and deterministic-task paths. Supporting billing and media
integrations are omitted to keep this view focused.
The Codex publisher's logical enqueue arrow goes through the API's authenticated
persistence ingress. Only API and deterministic worker mount the task store;
there is no direct database mount inside the Codex container.

```text
diagram_type: architecture
output: /Users/bohuihan/memoir/memoir-architecture.html
specification_sha256: fb3c67262fd33f7e3c5df00bf596f0be2a291e9a92a901976ffad3c054d397e4
artifact_sha256: bfba2c0461c3d46ce1d786703348a772e19c9e9522cd01fb5eb98aa931a8b291
validation: 9/9 showcase, 0 errors, 0 warnings
browser_evidence: passed
visual_review: passed
correction_rounds: 0
```

Specification: 5,680 bytes. HTML: 814,918 bytes.

The automated browser receipt is
[`memoir-architecture.visual-check.json`](../memoir-architecture.visual-check.json).
It verifies desktop containment at 1440×900, 1600×1000, 1920×1080 and 2048×1320
and captures light/dark screenshots at the endpoint sizes. The automated receipt
correctly leaves perceptual review pending; that is a separate claim.

Perceptual review: the delivered 1440×900 light and 2048×1320 dark screenshots
were inspected with the image viewer. Node labels, source/result arrows, legend,
and explanatory cards were legible, without crossing routes or clipped cards.
The five-service and isolated-publisher revision passed without further visual
corrections; validation, delivery and browser checks were rerun against the
final artifact above.
