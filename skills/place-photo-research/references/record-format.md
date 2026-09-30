# Records consumed by the helper

The initializer writes `request.json`. Do not reconstruct it from conversation history or insert an old period when the current request has none. It also creates an empty JSON array in `candidates.json` and an empty `evidence.jsonl`.

Write UTF-8 JSON, not Python repr or Markdown fences. One evidence object per nonempty line. Candidate order is the researcher's ranking; put the strongest eligible diverse items first. Maximum 100 candidates per run.

## Evidence record

```json
{
  "id": "ev-date-001",
  "kind": "scene_date",
  "url": "https://example.invalid/item/123",
  "locator": "Image-specific Date taken field",
  "excerpt": "EXAMPLE ONLY — replace with a short exact excerpt actually observed.",
  "observed_at": "2026-09-26T07:00:00+00:00"
}
```

Allowed kinds: `place`, `scene_date`, `license`, `access_terms`, `permission`, `creator`, `other`. Each ID must be unique and use 1–64 ASCII letters, digits, underscores or hyphens, beginning with a letter/digit. URLs are actual source URLs. Observed-at must include a timezone. A rights-holder permission document can be cited with a safe source reference; do not place private signed URLs, credentials or private grant text in public outputs. This local helper currently expects URL-backed evidence; do not invent a URL for a private contract.

## Candidate record

All URLs and values here are **non-runnable placeholders**, not an actual photograph:

```json
{
  "id": "photo-001",
  "title": "Example caption — replace with actual source title",
  "source_page_url": "https://example.invalid/item/123",
  "image_url": null,
  "observed_image_url": null,
  "creator": null,
  "collection_page_url": null,
  "authenticity": "unresolved",
  "place": {
    "label": "Requested city",
    "match": "uncertain",
    "evidence_ids": []
  },
  "scene_date": {
    "start": null,
    "end": null,
    "precision": "unknown",
    "basis": "unknown",
    "conflicting": false,
    "evidence_ids": []
  },
  "rights": {
    "license_id": "unknown",
    "license_url": null,
    "scope": "unknown",
    "download_permitted": null,
    "commercial_use_permitted": null,
    "attribution": null,
    "evidence_ids": []
  },
  "acquisition": {
    "access_permitted": null,
    "allowed_hosts": [],
    "evidence_ids": []
  },
  "notes": []
}
```

`observed_image_url` is optional provenance used by the Crawl4AI route when a source page exposes an HTTP image URL. In that case `image_url` may contain the same observed host/path with an HTTPS scheme for the HTTPS-only memory-reference surface; the original HTTP URL remains recorded in `observed_image_url`. Never invent a different path, filename or host.

For a supported scene-date range, use ISO interval bounds and preserve precision:

```json
{"start":"1983-01-01","end":"1983-12-31","precision":"year","basis":"source_caption","conflicting":false,"evidence_ids":["ev-date-001"]}
```

This represents “sometime in 1983,” not a photograph taken exactly on either endpoint.

Allowed place matches: `exact`, `broader`, `uncertain`, `wrong`. `exact` means exact at the request's resolution, not that a city caption establishes an address.

Allowed date bases: `catalogue`, `source_caption`, `provider_date_taken`, `original_exif`, `album_caption`, `unknown`, `upload_date`, `page_publication`, `visual_guess`. The last four cannot satisfy a scene-date match. Original EXIF must describe scene capture, not scanning. Any conflict sets `conflicting: true` until resolved with recorded evidence.

Set `authenticity: source_described_photograph` only after observing that the source describes an actual photograph, not a generated/re-enacted/illustrated scene. This is a limited source assertion, not forensic verification.

## Eligibility for local download

The helper requires all of:

1. Exact requested-place match with place evidence.
2. Evidence-supported scene date wholly in the requested interval; for historical-unspecified, a documented date older than the current preference window. Unknown, partial overlap, recent-not-old and future scene dates do not pass.
3. No unresolved date conflict; source-described photograph.
4. An observed direct image URL.
5. Item-scoped rights with explicit download permission, rights evidence and, for commercial-memoir sourcing, commercial-use permission.
6. A recognised licence URL plus attribution when required, or documented custom permission.
7. Explicit acquisition access with access/permission evidence and exact allowed image hosts.

Recognised built-in IDs/URLs:

```text
CC0-1.0        https://creativecommons.org/publicdomain/zero/1.0/
CC-BY-4.0      https://creativecommons.org/licenses/by/4.0/
CC-BY-SA-4.0   https://creativecommons.org/licenses/by-sa/4.0/
```

For `custom-permission`, include `permission_grant_reference` and evidence of kind `permission`. This is for an actual inspected grant, not a workaround for an unknown/noncommercial licence. The helper cannot authenticate the grant.

An image domain and any redirect/CDN host must be explicitly in `allowed_hosts` based on observed links/redirect evidence. Do not construct full-size URLs by guessing filename conventions or put wildcard domains in the record.

## Outputs and limitations

`manifest.json` includes every candidate, eligibility reasons and successful download metadata: requested/final URL, capture assertions, SHA-256, byte count, dimensions, MIME and local relative path. Its publication status is always `not_approved_by_this_local_skill`.

A blocked candidate is still reported with its source. A network/decode failure is distinct from a rights block. Downloaded originals are deduplicated by SHA-256. The gallery references local files only and does not hotlink unknown-rights previews.

These are structural and conservative decision checks, not verification of the truth of supplied evidence. Review the actual source before setting facts/permissions. Do not treat the record writer and downloader as independent security principals. Existing files are never silently deleted when a later run flags them; the updated report stops presenting them and the user must review retention.
