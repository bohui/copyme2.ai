# PR8, PR9 and PR10 Mac integration

The isolated candidate incorporates the verified PR8 main merge
`a4d8abf810eefa1ec36cc219710f8ac954bb52e9` (tree
`8bbcecabb43aeca01bdeb37dbe7c1f38715b99c9`) into the reviewed PR9/PR10 Mac
candidate `9359d4baa549a71458eec079ff2415f6bad7366f`.
This is a deliberate integration of the exact merged main, not a merge of the
older PR3, PR9 or PR10 heads into main.

The only conflicts were the photo skill's checksums, validation JSON and test
transcript. The combined helper retains PR9's parallel discovery/current-period
policy and PR8's reconciliation of all capture assertions, uncertainty vetoes,
publication/capture separation, month precision and sibling-source isolation.
Validation records retain both branches' earlier results as historical evidence
and use fresh combined-tree results for the current offline receipt.

On 2026-10-05, before the integration commit:

- `python -m pytest -q tests/test_llm_place_photos.py tests/test_photo_capture_assertions.py tests/test_place_photo_browser.py tests/test_place_photo_pages.py tests/test_photo_progress.py tests/test_photo_worker.py skills/place-photo-research/tests --junitxml=output/mac-validation/resume-pr8-photo.xml`: **395 passed, zero failed, zero skipped, zero errors**, seven passing subtests and one upstream Starlette/httpx warning.
- `python -m unittest discover -s skills/place-photo-research/tests -v`: **90 passed**. These overlap the pytest receipt and are not additional acceptance cases.
- `(cd skills/place-photo-research && shasum -a 256 -c SHA256SUMS)`: all 17 entries verified.

The combined photo helper SHA256 is
`9a5359f7a576f00f2d0873a50740b67af96b65b186d127146d87c467c94ab738`.
Optional Crawl4AI is not installed in this Mac environment; its provider is
mocked in the offline cases. No new live search, download or provider call was
made. These results establish the combined offline photo behavior; exact-head
native/browser/build acceptance and independent cloud review remain separate.

The preceding native runs and their failures remain recorded in
`docs/pr9-pr10-mac-validation.md`. An unchanged focused retry does not convert a
failed broad run into a pass. The resumed validation diagnoses those failures
and the lost standalone image-lifecycle receipt without modifying host limits
or unrelated services.
