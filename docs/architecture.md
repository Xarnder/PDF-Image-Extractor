# Architecture and dependency decisions

## Runtime

FastAPI serves both the compiled Svelte 5 app and `/api` from one loopback origin. The application has no cloud connector, telemetry exporter, external font request or remote document service. The launcher passes an already-bound loopback socket to Uvicorn, avoiding a check-then-bind port race. Same-origin checks, Host validation, Fetch Metadata checks, an unpredictable session token on all mutations, frame denial and a restrictive CSP defend the local API from arbitrary websites. There is no cross-origin allowance.

SQLite uses WAL and short transactions. Each completed page commits its regions and checkpoint together. Page state is pending/running/done/failed; job state is ready/queued/running/paused/completed/cancelled. Interrupted running/queued jobs become paused on startup, and in-flight pages become pending. Failed pages are retained and retried explicitly. Manual records are preserved when a page is processed again. Edit history stores reversible region changes, including create/split/merge actions.

The controller uses bounded document worker slots. Each slot owns a reusable spawn-based process and a pipe. Only that process opens and renders its PDFs. A watchdog kills and replaces the worker when the configured timeout/RSS limit is exceeded. A separate serialized process handles on-demand previews, imports and individual image extraction. Exports snapshot region records and run sequentially in an isolated worker behind a bounded queue of 32 waiting exports. No document handle is shared across threads or processes. Heron is loaded once per reusable document worker when enabled.

## Extraction flow

1. **Native placements:** PyMuPDF reports each placement, source XREF, size, mask, and transformation matrix. Placement coordinates are multiplied by the page rotation matrix; the UI and all persisted crops consistently use the displayed page coordinate system in PDF points.
2. **Rendered evidence:** a bounded RGB analysis render provides what the PDF actually displays. Native source transforms are compared with the rendered placement before automatic source-pixel extraction is enabled. Page-sized/composite placements are analysed for internal regions. Original-source mode deliberately bypasses the visible crop, except when the user has edited a crop.
3. **OpenCV:** border-background estimation, adaptive colour tolerance, local texture, connected contours, morphology, projection runs and recursive gutter splitting generate rectangular proposals. Small sparse headings are separated before region size checks. Contour proposals that contain already-separated photographs are not added as combined crops.
4. **Optional Heron:** document picture regions become additional proposals. Maximum mode adds overlapping tiles and a second OpenCV scale. Heron is a layout model, not a semantic photograph classifier.
5. **Fusion/refinement:** matching boxes gain agreement; native photographic boundaries take precedence over an inner foreground silhouette. Adjacent/nested candidates are not blindly averaged or conventionally suppressed. Boundary snapping searches a small neighbourhood for a strong continuous discontinuity. Native boundaries are not trimmed.
6. **Validation:** entropy, quantized colour diversity and edge density provide conservative heuristic classification. Low-detail graphics and page-sized sources remain in review. Confidence values describe detector heuristics, not measured accuracy. Every retained candidate is recoverable.
7. **Export:** orthogonal source pixels are transformed/cropped directly when verified. Complete unchanged images can preserve encoded bytes. Complex composition falls back to MuPDF rendering, constrained by source density and a pixel cap. No enhancement, denoising or generative processing is applied.

Preview/thumbnail writes and output image writes are atomic. Thumbnails are requested lazily. Gallery data is paginated; document pages and compact region metadata are disk-backed. Exact encoded, decoded-pixel and perceptual hashes have separate meanings. Near duplicates never disappear automatically.

## Interfaces and extension points

`extraction/geometry.py` defines the detector protocol and proposal structure. Native extraction, rendering, OpenCV, boundary refinement, fusion, classification, duplicates, Heron, and export are separate modules. API transport, database transactions, process supervision and filesystem exports are independent layers. New detector plugins should return proposals in their input image coordinates and must never mutate photographic content.

The optional Heron adapter follows the model author's [inference example](https://huggingface.co/docling-project/docling-layout-heron). The [Docling model catalog](https://docling-project.github.io/docling/usage/model_catalog/) lists Transformers layout support for CPU, CUDA and MPS; actual compatibility is checked at runtime. Heron weights are Apache-2.0, about 173 MB / 42.9M parameters, with the downloaded revision persisted. The adapter uses RT-DETR-v2 classes from Transformers 4.57.3 and optional Torch 2.9.1. PyPI metadata was checked: those Torch/torchvision releases provide CPython 3.12 macOS ARM64 wheels; Transformers is a pure Python wheel. The optional environment was not installed or hardware-tested here, and is not part of the validated base lock.

The base pins PyMuPDF 1.26.7 to use its established parsing/rendering API without the newer bundled ML/layout dependency stack. Placement handling follows [PyMuPDF's image transformation documentation](https://pymupdf.readthedocs.io/en/latest/app3.html#image-transformation-matrix) and [page API](https://pymupdf.readthedocs.io/en/latest/page.html). Its [multiprocessing guidance](https://pymupdf.readthedocs.io/en/latest/recipes-multiprocessing.html) motivates process isolation. [PyTorch MPS documentation](https://docs.pytorch.org/docs/main/notes/mps.html) describes device support; availability alone is not treated as proof of successful inference.

## Deliberate scope boundaries

Secondary AI engines and semantic classifiers are unavailable rather than represented by mock results. Polygon editing and OCR are absent. Temporary storage is relocated via one environment variable rather than moving active databases from the UI. Individual PDFs can be queued together; each job exports its own selected scope. Settings are immutable snapshots per imported job. Detailed limitations are listed in the README and surfaced through review statuses or explicit error messages where applicable.
