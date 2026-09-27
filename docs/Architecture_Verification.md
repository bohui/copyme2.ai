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
specification_sha256: 369ef019beca85f16ff480ef9cbb0cf75dbdc472820525f09727e7890efd872f
artifact_sha256: ee9e0ee5be99bbc67d7e58ed8e14716431f65f1427df7d1ee5734f4b65ebec06
validation: 9/9 showcase, 0 errors, 0 warnings
browser_evidence: passed
visual_review: passed
correction_rounds: 0
```

Specification: 5,662 bytes. HTML: 814,888 bytes.

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
