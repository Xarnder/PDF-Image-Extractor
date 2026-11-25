# Validation report

Updated on 25 November 2026 on this Apple Silicon Mac, using Python 3.12.14. The supplied UI mockup guided the three-panel editor; it was not treated as a real-document detection fixture.

## Automated checks

- **43 backend tests pass.** Native extraction and byte-for-byte JPEG passthrough; original dimensions; flattened three-image layouts; narrow gutters; white photographic backgrounds in native sources; white/dark/coloured paper; mixed headings/photos; recoverable decorative-graphic rejection; full-page and empty pages; page/image rotation; rectangular clipping and crop boxes; soft masks; reused placements; inline images; corrupted/password-protected files; RGB/CMYK/grayscale; exact/perceptual hashes; alpha-aware pixel hashes; crop export; PNG/JPEG validation; metadata preservation/removal; collision prevention; coordinate validation; edit revision conflicts; undo/redo; manual preservation during re-detection; pause/resume; checkpoint recovery; failed-page retry; low disk space; worker timeout/cancellation/recovery; pixel limits; optional model failure and device selection fallback; same-origin/Host/token controls; actual HTTP import/export; Windows helper port fallback, stale-process checks and browser fallback.
- Balanced-mode regressions cover full studio-photo boundaries, face-preserving splits, uncertain face priority, printed faces in book mockups, text/logo exclusion, photographs without faces, helper fallback, text-box unions, banner splitting and off-page inline graphics. API checks cover the active gallery filter and photo counts.
- **8 frontend tests pass.** Mapping screen positions to PDF points at six zoom levels, clamping after panning and reverse-direction crop drawing. Numerical comparisons allow floating-point tolerance; they do not round away crop precision.
- **Svelte/TypeScript: 0 errors, 0 warnings.** Production Vite build succeeds.
- **Installation:** `./setup.sh` completes against the lockfiles, including frontend checking/building and the doctor check. The core launches without PyTorch or model weights. The launcher was tested with port 8765 deliberately occupied and selected 8766 successfully. A final stop → immediate restart → stop check passed, with runtime-state cleanup verified.
- One dependency deprecation notice is emitted by Starlette's current `httpx`-based test client. It does not affect application operation or test results.

## Measured 174-page benchmark

The final measured run is retained in [benchmark.json](benchmark.json). The deterministic fixture uses seven layouts, alternating native and flattened images, narrow gutters, white/dark/coloured page backgrounds, rotations, full-page images and empty pages. Its images are synthetic textured test assets, not real photographs of people.

| Metric | Result |
| --- | ---: |
| Pages processed | 174 / 174 |
| Failed pages | 0 |
| Expected regions | 425 |
| Detected / matched regions | 425 / 425 |
| Missed regions / extra regions | 0 / 0 |
| Precision / recall on this fixture | 1.000 / 1.000 |
| Mean intersection over union | 0.99946 |
| Maximum matched edge error | 0.420 PDF points |
| Processing wall time, including forced restart | 118.64 s |
| Processing throughput | 1.47 pages/s |
| Peak combined server + worker RSS | 1091.3 MB |
| Local health API latency, 95th percentile | 10.48 ms |
| Local health API latency, maximum observed | 20.31 ms |
| Valid individual PNG exports | 425 |
| Export wall time | 27.05 s |

Matching requires IoU > 0.90; the benchmark additionally requires every expected region, zero false positives and maximum edge error below 2 PDF points. The server process group was killed after 12 completed pages. On restart, the job was paused at the saved checkpoint, then resumed to completion. Every output file was opened and verified with Pillow. The benchmark measures one document worker; Heron is off and Apple Vision content checks are on. This run overlapped the real-book validation. Geometry metrics include rejected synthetic artwork and do not measure semantic classification accuracy. Memory measurements include server, worker and native-helper processes, not Chrome or the fixture generator, and are sampled rather than an exact instantaneous maximum.

**These measurements do not establish accuracy on the user's book or arbitrary magazines.** The supplied real publication has now been tested separately, as described below. Flattened white-background photographs and semantic distinctions such as photographic book mockups remain difficult; manual review is part of the application workflow.

## Real 174-page photography-book retest

On 25 November 2026, the supplied fashion/posing publication was processed through the actual HTTP import, Balanced extraction, persistence and PNG export paths. Native PDF, OpenCV and local Apple Vision were active; Heron was disabled. The input and all image derivatives remain in ignored local storage, not in this repository.

| Metric | Original Balanced | Fixed Balanced |
| --- | ---: | ---: |
| Pages processed / failed | 174 / 0 | 174 / 0 |
| All candidates | 599 | 488 |
| Automatically accepted | 208 | 194 |
| Needs review | 391 | 190 |
| Rejected candidates | 0 | 104 |
| Valid PNG exports | 599 (all candidates) | 384 (accepted + review) |
| Processing time | 146.67 s | 272.05 s |
| Export time | 122.77 s | 90.57 s |

All 174 pages were visually inspected through contact sheets; all 104 rejected thumbnails were checked. The originally split/trimmed photographs on pages 12, 21, 44, 51, 55, 64, 67 and 134 now each retain one full visible native placement with a face inside it. Book montages/mockups on pages 5, 7, 94 and 172, text/logo candidates, the six illustrations on page 115, and the painting on page 116 are rejected. A partially off-page inline graphic no longer borrows the photograph behind it for classification. Banner icons are not separated into standalone photo candidates.

All 384 exported PNGs passed decoding and metadata-dimension checks; no rejected item was exported. The 195 encoded passthrough outputs also matched the original PDF image payloads by SHA-256. Peak sampled server/worker/helper RSS was 897.5 MB and health API p95 was 7.22 ms. Processing overlapped the synthetic stress run; timings are observations, not hardware-normalized comparisons. The additional content analysis costs processing time.

The browser's **Photographs + review** export option was separately exercised on pages 5-7: seven valid images, both accepted and review statuses, zero rejected graphics. The default gallery excludes rejected candidates; the Rejected filter still exposes them for recovery. No browser console errors were observed.

These counts are application decisions, not a full hand-labelled precision/recall dataset. Uncertain clipped layouts, photographic backgrounds, PDF overlays and duplicated compositions remain for review. A laptop promotional photograph on page 173 remains in review; photos without faces are not rejected solely for lacking a face. Rendered exports can retain text painted over photos; this work does not remove text through inpainting. Semantic results are specific to macOS Apple Vision; portable checks are less capable.

Reproducibility artifacts are local under `data/validation/balanced-fix/`: `final-report.json`, `final-regions.json`, `run_validation.py`, `report.html`, contact sheets and output comparisons. The final saved job is the newest Balanced run with 384 active candidates. No private images are included in the public test suite.

## Browser validation

In Google Chrome on the Mac, exercised:

- Dashboard and native PDF file picker; uploaded the generated 105 MB, 174-page fixture.
- Starting the real extraction job and live page/region counters.
- Page navigation, selecting a flattened-page image, source metadata and confidence labels.
- Crop splitting, persistent update, undo back to the original region count.
- Photograph gallery and review queue navigation during processing.
- Keyboard acceptance (`A`) and corresponding review/accepted count changes.

In the in-app browser against the same production server, additionally exercised:

- Saved-job reopening after server restart.
- Desktop layout at 1440 × 1000, dark and light themes.
- A real crop resize at 125% zoom: output width changed from 640 to 618 pixels; undo restored 640 pixels.
- Export form selection of JPEG, selected-region export, completion status, local folder and ZIP link.
- Settings persistence and explicit disabled/uninstalled AI state.
- Final desktop export footer visibility; settings focus containment, Escape dismissal and focus restoration.
- No browser console errors in the inspected log.
- Balanced follow-up: new face/content settings default on; Apple Vision availability is shown; the default gallery excludes rejected candidates; page 21 displays a complete photograph boundary instead of head/body fragments.

Native Chrome automation was interrupted while opening the export dialog; export/settings verification continued in the in-app browser. No claim is made that every browser interaction was automated in Chrome. Browser QA used actual backend results, not simulated data or fake progress.

## Double-click launcher follow-up

Added `start.bat` and `start.cmd` for Windows, plus `Start PDF Image Extractor.command` for Finder on macOS. The Mac command started the real production server; health and session endpoints returned HTTP 200 and graceful shutdown completed. Windows-specific bootstrap, batch execution and `msvcrt` locking remain unverified on a native Windows host. Portable helper behavior is covered by the three additional backend tests above.

## Unverified optional paths

Real Heron inference, MPS/CUDA runtime behavior, secondary AI engines, real-world photograph precision/recall, Windows startup, unusual damaged colour profiles and all varieties of nonrectangular PDF clipping are not comprehensively validated. The tested core remains operational without optional AI. See the README for fallback and review behavior.
