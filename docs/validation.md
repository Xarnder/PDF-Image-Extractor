# Validation report

Validated on 24 November 2026 on this Apple Silicon Mac, using Python 3.12.14. The supplied UI mockup guided the three-panel editor; it was not treated as a real-document detection fixture.

## Automated checks

- **33 backend tests pass.** Native extraction and byte-for-byte JPEG passthrough; original dimensions; flattened three-image layouts; narrow gutters; white photographic backgrounds in native sources; white/dark/coloured paper; mixed headings/photos; conservative decorative-graphic review; full-page and empty pages; page/image rotation; rectangular clipping and crop boxes; soft masks; reused placements; inline images; corrupted/password-protected files; RGB/CMYK/grayscale; exact/perceptual hashes; alpha-aware pixel hashes; crop export; PNG/JPEG validation; metadata preservation/removal; collision prevention; coordinate validation; edit revision conflicts; undo/redo; manual preservation during re-detection; pause/resume; checkpoint recovery; failed-page retry; low disk space; worker timeout/cancellation/recovery; pixel limits; optional model failure and device selection fallback; same-origin/Host/token controls; actual HTTP import/export; Windows helper port fallback, stale-process checks and browser fallback.
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
| Processing wall time, including forced restart | 49.18 s |
| Processing throughput | 3.54 pages/s |
| Peak combined server + worker RSS | 1035.7 MB |
| Local health API latency, 95th percentile | 1.45 ms |
| Local health API latency, maximum observed | 5.30 ms |
| Valid individual PNG exports | 425 |
| Export wall time | 25.45 s |

Matching requires IoU > 0.90; the benchmark additionally requires every expected region, zero false positives and maximum edge error below 2 PDF points. The server process group was killed after 14 completed pages. On restart, the job was paused at the saved checkpoint, then resumed to completion. Every output file was opened and verified with Pillow. The benchmark measures one document worker; optional AI is off. Memory measurements include server and worker processes, not Chrome or the fixture generator, and are sampled rather than an exact instantaneous maximum.

**These measurements do not establish accuracy on the user's book or arbitrary magazines.** The actual 174-page publication was not supplied. Flattened white-background photographs and semantic distinctions such as photographic book mockups remain difficult; manual review is part of the application workflow.

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

Native Chrome automation was interrupted while opening the export dialog; export/settings verification continued in the in-app browser. No claim is made that every browser interaction was automated in Chrome. Browser QA used actual backend results, not simulated data or fake progress.

## Double-click launcher follow-up

Added `start.bat` and `start.cmd` for Windows, plus `Start PDF Image Extractor.command` for Finder on macOS. The Mac command started the real production server; health and session endpoints returned HTTP 200 and graceful shutdown completed. Windows-specific bootstrap, batch execution and `msvcrt` locking remain unverified on a native Windows host. Portable helper behavior is covered by the three additional backend tests above.

## Unverified optional paths

Real Heron inference, MPS/CUDA runtime behavior, secondary AI engines, real-world photograph precision/recall, Windows startup, unusual damaged colour profiles and all varieties of nonrectangular PDF clipping are not comprehensively validated. The tested core remains operational without optional AI. See the README for fallback and review behavior.
