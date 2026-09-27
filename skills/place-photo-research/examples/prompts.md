# Invocation examples

## Historical — exact decade

```text
$place-photo-research Find 3 real photographs of Chengde, Hebei, China in the 1980s. Prioritise ordinary streets, shops and daily life over monuments. Search Chinese and English sources, inspect individual records and useful albums, and save permitted originals plus evidence and a local gallery to ./photo-research/chengde-1980s-01. Keep strong matches with unknown rights as metadata-only candidates.
```

## No period — automatically current

```text
$place-photo-research Find 3 photographs of Chengde, Hebei, China. Prefer city streets and local life. Save permitted images, evidence and a gallery to ./photo-research/chengde-current-01.
```

## Chinese explicit period

```text
$place-photo-research 帮我找河北承德1980年代的老照片，优先找街景、商店和日常生活。检查每张照片的实际拍摄年代、来源和使用许可，把可以合法下载的照片及证据保存到 ./photo-research/chengde-1980s-zh-01。
```

## Historical, period unspecified

```text
$place-photo-research Find old photographs of Chengde. Do not invent a decade. Report the supported date or uncertainty for each result and save permitted files under ./photo-research/chengde-old-01.
```

## Explicit switch to current

```text
$place-photo-research We were discussing Chengde in 1983. Now find what those streets look like today. Do not reuse historical photos as current evidence. Save a separate run under ./photo-research/chengde-today-01.
```

## Resume without resetting limits

```text
$place-photo-research Resume ./photo-research/chengde-1980s-01. Inspect its request, evidence and remaining search budget. Do not repeat successful downloads or silently change its period. Report unresolved permissions separately.
```

## Metadata-only request

```text
$place-photo-research Find photographs of Chengde in 1983, but do not download image bytes. Save the candidate list, scene-date evidence, original source pages and rights status under ./photo-research/chengde-1983-links-01. Use audit/report, not download.
```

## Expected temporal behaviour checks

| Prompt | Expected |
|---|---|
| Find pictures of Chengde | Current |
| Find pictures of Chengde after an earlier discussion of 1983 | Current; no hidden inheritance |
| Find Chengde in the 1980s | 1980–1989 |
| More photos from that same period | Resolve explicit reference and record basis |
| Show that street | Resolve place, not unstated period |
| Old photos | Historical unspecified |
| Photos from school years without confirmed dates | Historical unspecified |
| Today | Strict day interval; no default 24-month substitution |

These are invocation/behaviour examples, not results from live Codex evaluation.
