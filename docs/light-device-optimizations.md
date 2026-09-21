# Light-device optimizations

Goal: run the full no-cache pipeline on a light box (2-4 GB RAM, 2-4
vCPU, CPU-only) without losing final-output resolution (1080x1920 stays)
or quality. Baseline: `docs/benchmark-no-cache-run.md`
(~4.6 GB peak RSS, ~13 min on 8 cores).

## P0 — done, zero quality impact of any kind

| Item | Change | Files |
|---|---|---|
| Free torch after candidates | `del detector` + `free_torch_memory()` (gc + CUDA clear + `malloc_trim`) after `run_candidates` — MEASURED 2026-09-22, INEFFECTIVE: fresh process hits 33 → 590 (YOLO load) → 1520 MB (5 inferences), then `del` + `free_torch_memory()` reclaims only ~20 MB (1520 → 1498 MB, `malloc_trim` returns 1 but the torch heap is not returned in-process). Run peak unchanged; see "Measured correction" below | `features/detector.py` (`free_torch_memory`), `web/stages/candidates.py`, `scripts/run_e2e.py`, `scripts/profile_e2e.py`, `scripts/run_gap_eval_session.py` (released only on the attempt that reaches render, so retries keep a live detector) |
| Skip preview encode | `run_render(..., preview=False)`; `--no-preview` on `run_e2e.py` / `profile_e2e.py`; default `True` (no behavior change; web flow keeps previews — the operator pause needs them) | `render/pipeline.py`, `scripts/run_e2e.py`, `scripts/profile_e2e.py` |
| Thread count | Already parameterized (`run_ingest`, all render fns, `web/jobs.py:THREADS`); use `--threads 2` on 2-vCPU boxes. No code change needed | — |
| Tonemap skip | Already conditional (`session/_common.py`: `""` when no HDR source). No code change needed | — |

Expected combined effect: run peak ~4.6 GB → ~1.5 GB (render
`medium/crf18` at 1080p with no torch resident), ingest unchanged
(~1.3 GB). Validate with `scripts/profile_e2e.py --no-preview`.

## Measured correction (2026-09-22) — the ~1.5 GB claim is withdrawn

Two isolated probes on the 8-core host, reference workload
(`var/sessions/new_videos_01`, 10 segments):

- Render without torch ever loaded: `render_segments` (medium/crf18,
  1080p, `threads=4`) peaks at **~1.4 GB** process-tree RSS
  (python ends at ~140 MB). The render-only component of the claim holds.
- In-process torch free does not: 33 → 590 MB on YOLO load →
  1520 MB after 5 inferences → **1498 MB after `del` +
  `free_torch_memory()`** (~20 MB reclaimed). `malloc_trim` returns 1
  but the torch heap is not returned to the OS.

So the run peak stays **~4.6 GB** (candidates' own ~3.5 GB in-flight
peak remains the floor even with a perfect post-hoc free — freeing
after the fact cannot retroactively lower a peak already recorded).
Sizing consequence: no box under ~5 GB is safe until candidates runs
in a child process that exits (see zero-risk shortlist). The
`docs/benchmark-no-cache-run.md` verdict (Oracle 12 GB as the only
free fit) stands; Hetzner CAX11/CX22-class 4 GB boxes do not fit the
measured peak.

## Zero-risk shortlist (approved: no pixel change, no selection change)

Everything in P1 changes *which* clips are picked (silent selection
shift, render checks stay green) and everything in P2 changes pixels
or removes features — all excluded here. Approved:

| Item | Why zero-risk | Files |
|---|---|---|
| Candidates in a subprocess that exits | Same model, same frames, same outputs; exit() frees what `malloc_trim` cannot. Turns run peak into max(stage peaks) instead of sum. Engineering risk only | `session/candidates.py`, `web/stages/candidates.py` |
| Decode-side frame skip (same stride value) | `_read_samples` decodes every frame and keeps 1/3; `grab()`-skipping to the same kept frames feeds YOLO bit-identical inputs. Saves cv2 decode CPU only | `features/extract.py:20-34` |
| `OMP_NUM_THREADS` / `TORCH_NUM_THREADS` caps | `--threads` only threads ffmpeg; YOLO (torch intra-op) and x264 filters oversubscribe (candidates ~430-485% mean with `--threads 4`). Env caps change scheduling, not numerics | launch scripts / systemd unit |
| `--no-preview` (CLI batch only) | Skips the duplicate 540p encode; `run_r2=False` covers the missing comparison. Web flow keeps previews (operator pause needs them) | `render/pipeline.py`, `scripts/run_e2e.py` |

## P1 — backlog, degrades selection (which clips, not pixels)

Needs per-item approval + before/after gate (exercise ground truth in
`tools/eval_exercises.py`, `var/exercise_ground_truth.json`).

| Item | Knob | Files |
|---|---|---|
| YOLO `imgsz` 640 → 416/320, `conf=0.5` | `model.predict(frame_bgr, verbose=False)` takes no sizing args today | `features/detector.py:33` |
| Frame stride 3 → 6 + decode-side skip | `_read_samples` decodes every frame, keeps 1/3; speed math already stride-normalized | `features/_common.py:11`, `features/extract.py:20-34,125,129` |
| Proxy 720p → 540p for features | Shared with peak-frame extraction + verify — can't shrink blindly | `ingest/proxy.py:15,47-55` |
| ONNX/OpenVINO export (x86, ~3x) / NCNN (ARM) | `YOLO(...).export(format=...)`, load in `detector.py`; INT8 via NNCF as follow-up | `features/detector.py` |
| Model swap (`yolo11n-pose`, box-only) | Spec allows `n` or superior (`04-features.md:37`) | `features/detector.py:12`, `web/jobs.py:15` |

## P2 — backlog, degrades pixels or removes features

Needs per-item approval + `run_render_checks` gate. Final resolution is
off the table (1080x1920 stays); these trade sharpness/effects for speed.

| Item | Knob | Files |
|---|---|---|
| Render `preset medium → faster` (same `crf 18`) | ~2x faster, ~10-15% larger file, marginally softer detail | `render/_common.py:30` |
| `crf` 18 → 21 | Direct quality reduction; last resort | `render/_common.py:30` |
| `lanczos → bilinear`, Ken Burns 3x → 2x prescale, `blur_radius` 20 → 12 | Sub-pixel sharpness/smoothing changes | `render/segments.py:118,177`, `planner/_common.py:37-38` |
| Cheaper verify (`FRAME_OFFSETS`, instant count) | Lowers proxy-mismatch catch rate, not output quality | `verify.py:19,52-60` |
| Cheaper checks (R2 `run_r2=False`, 1 frame) | Same category as verify | `render/checks.py:89,316` |
| Disable effects (flash/punch-in/text/logo/color match) | Removes creative features — biggest perceptual change | `render/_common.py`, planner config |

## P3 — structural, if P0-P2 still doesn't fit

Split the pipeline: ingest+candidates as an async batch job on a big
slow box (fits Oracle ARM free: 12 GB RAM, 2 vCPU), web UI serving only
selection/preview/render. Stages already communicate via JSON files
(manifest/candidates/selection/edl), matching the §2 layering.
