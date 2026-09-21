# No-cache full-run resource profile (2026-09-21)

How much CPU/RAM a whole video generation costs with the cache disabled,
measured to size a cloud deployment. Method, raw data notes, verdict,
and optimization ideas.

## Workload (reference input)

Copied from `var/sessions/new_videos_01/` (inputs + music + brand only,
no outputs) into a fresh session dir, so the run is cold and repeatable:

- 23 inputs, 890 MB on disk: 18 vertical videos + 4 HEIC images
  (1 horizontal clip skipped by ingest) + 1 MP3
- 296 s of source video → 53 candidates → 9 slots → 15 s reel (1080x1920)
- LLM: DeepSeek `deepseek-flash` for selection + hooks (API-bound, so local
  CPU/RAM is pure pipeline: ffmpeg + YOLO + librosa)
- Flags: `--no-cache` equivalent (`cache_root=None`), `--threads 4`,
  `CUDA_VISIBLE_DEVICES=""` (CPU-only: free tiers have no GPU)

## Method

`scripts/profile_e2e.py` mirrors `scripts/run_e2e.py` stage by stage
(ingest → slots → candidates → selection → planner_base → hooks →
planner_final → render_preview → render_segments → concat → checks) and
polls the whole process tree every 0.2 s with `psutil`:

- `total_rss_mb`: sum of RSS over Python + all children (ffmpeg, …)
- `cpu_pct`: sum of per-process CPU, Unix convention (100% = 1 core;
  8-core host → ceiling 800%)
- `sys_cpu_pct`: system-wide cross-check; `top_proc`/`top_rss_mb` show
  which process dominates each sample
- Output: `samples.csv` (full timeseries) + `summary.json` (per-stage
  wall/peak/mean). Both are written even if a stage raises.

Host: 8 vCPU / 11 GiB RAM / RTX 2070 (unused — CPU-only run),
ffmpeg 5.1.9, torch 2.14 CPU, `yolov8n-pose.pt`.

## Results (3 full runs + 1 tiny validation)

| Stage | Wall | Peak RSS | Mean RSS | Peak CPU | Mean CPU |
|---|---|---|---|---|---|
| ingest (proxy x264 720p + verify) | ~530-570 s (70%) | ~1.3 GB | ~1.1 GB | ~730% | ~440% |
| slots (librosa beats) | ~1-2 s | ~0.4 GB | ~0.3 GB | ~340% | ~130% |
| candidates (YOLOv8n-pose CPU) | ~142-165 s (20%) | ~3.5 GB | ~3.0 GB | ~714% | ~430-485% |
| selection (DeepSeek API) | ~9 s | inherits ~3.0 GB¹ | — | idle | ~13% |
| planner / hooks | ~7 s | inherits ~3.1 GB¹ | — | idle | — |
| render_preview (x264 ultrafast 540p) | ~3-4 s | ~3.2-3.6 GB¹ | — | ~200% | — |
| render_segments (x264 medium 1080p) | ~30-38 s | **~4.2-4.6 GB** | ~3.8-4.2 GB | ~750% | ~290-325% |
| concat + checks | ~16 s | ~3.1 GB¹ | — | idle | — |
| **Total** | **~768-779 s (~13 min)** | **~4.6 GB** | — | — | — |

¹ RSS never drops below ~3 GB after `candidates` because the torch process
stays alive holding YOLO weights; those stages add little themselves.

- LLM cost per run: ~$0.011 (selection ~37k in / ~1.5k out tokens,
  hooks ~6-7k in / ~250 out).
- Disk: 890 MB inputs → ~1.0 GB session (74 MB proxies, 17-19 MB
  segments, 18 MB reel).
- Tiny validation (6 clips, 142 MB): ingest 61 s / 1.2 GB / 711%,
  candidates 31 s / 1.9 GB / 714% — scales sub-linearly, sampler sane.

### Measurement pitfalls found (read before re-running)

1. **Fresh `psutil.Process` reads 0.0 CPU.** Polling a newly spawned
   ffmpeg twice in the same tick (prime + read, ~0 wall-time between)
   produced a fake 21711% spike. Fix: prime new PIDs, contribute 0.0,
   read from the next tick (`scripts/profile_e2e.py`).
2. **Same-process double count.** 3 isolated samples showed exactly 2x
   the top process RSS with identical neighbors (±0.2 s) — a
   `children()` race during short-lived ffmpeg spawns. Rule: a 1-sample
   spike at exactly Nx top RSS with unchanged neighbors is an artifact;
   sustained plateaus (render_segments >4 GB for 67 consecutive samples)
   are real. Candidates peak is ~3.5 GB, not 5.9 GB.
3. **Horizontal sources are silently skipped** by ingest — a workload of
   horizontal clips measures 0 sources. Use vertical 9:16 inputs.
4. **Small workloads die in the planner** (`no admissible hook
   candidate`, `not enough develop candidates` with <10 clips) — expected,
   not a profiler bug. The 23-clip workload is the minimum for render data.
5. **`.env` is not auto-loaded**: `DEEPSEEK_API_KEY` must be exported
   (`set -a; source .env`) or selection/hooks fail.

## Cloud verdict (free-tier only, re-validated Sept 2026)

Peak RSS ~4.6 GB and ~13 min wall on 8 cores rule out the strict free
tiers for the full pipeline as-is. The P0 torch-free does not change
this: measured 2026-09-22 it reclaims ~20 MB of ~1.5 GB in-process, so
the 4.6 GB peak stands (see `docs/light-device-optimizations.md`,
"Measured correction"). Size every option below against 4.6 GB.

- **Oracle Always Free A1 (2 OCPU / 12 GB ARM, 200 GB disk): the best
  free option.** The only perpetual free VM fitting the measured peak
  with headroom; disk is plenty (~1 GB/session). Confirmed in Oracle's
  current Always Free docs — but note the June-2026 halving (was
  4 OCPU / 24 GB, cut without notice; enforcement still inconsistent,
  so audit the tenancy and set budget alerts). Ranked risks: (1) no A1
  capacity in-region (known failure mode — have a fallback before
  building ARM-only artifacts); (2) account approval friction;
  (3) ARM build work: weights are arch-independent (non-issue), the
  real work is a custom ffmpeg (stock Oracle Linux builds lack
  libass/zscale for `render/_common.py` hook text and the
  `ingest/proxy.py` tonemap) plus `OMP_NUM_THREADS=2` /
  `TORCH_NUM_THREADS=2` caps (`--threads` does not cap YOLO's torch
  threads — candidates burns ~430-485% mean with `--threads 4`).
  Expect ~30-60 min wall on 2 vCPU, not ~30-40. Run batch over SSH
  (`scripts/run_e2e.py --no-preview`); keep the web UI local.
- **Hugging Face CPU Basic (2 vCPU / 16 GB / 50 GB ephemeral disk,
  sleeps after 48 h idle):** RAM fits and a Docker image carries the
  custom ffmpeg + torch — best free *endpoint* for UI/preview or short
  jobs, not the batch worker. Caveats: disk is ephemeral (persist
  sessions to the Hub), outbound restricted to 80/443/8080 (DeepSeek
  API is 443, fine), 2 vCPU is slow, and current docs say compute
  Spaces require a paid plan — verify before relying on it.
- **GitHub Codespaces (120 core-h/mo = 60 h 2-core / 30 h 4-core /
  15 h 8-core, 15 GB storage):** best free *burst compute*. An 8-core
  machine (~16 GB) matches the profiled host → ~13 min/run → ~60
  reels/month free. Not a server (30-min idle stop, monthly quota).
- **Kaggle (CPU uncapped weekly, 12 h sessions, background commit
  runs) / Colab free (12-13 GB RAM, ≤12 h wall, ~90-min idle kill,
  dynamic quota):** last-resort batch runners. Kaggle CPU is the more
  predictable of the two. Notebook-shaped, ephemeral disk, no serving.
- **Disqualified:** AWS/GCP/Azure free (1 GB micros — ingest alone
  peaks at 1.3 GB), Render free (512 MB, 9x over), Fly.io / Railway
  (no permanent free tier, trial credit only).

Realistic options: batch worker on Oracle via CLI (or Codespaces
quota / Kaggle CPU when Oracle has no capacity), UI local (or an HF
Space as public preview endpoint). Cheapest paid fallback per run:
HF CPU Upgrade 8 vCPU / 32 GB at $0.03/h ≈ ~$0.01/reel.

## Optimization ideas (from the breakdown)

1. **candidates RSS (~3 GB, torch resident):** run YOLO in a subprocess
   that exits afterwards (`spawn` + explicit free) → post-candidates
   baseline drops ~2.5 GB. Biggest single RAM win.
2. **render_segments peak (~4.6 GB):** python holds torch RAM *while*
   ffmpeg encodes at `crf 18 / preset medium`. Combine with (1), or
   render in a fresh process after the LLM stages.
3. **ingest wall (70% of runtime):** proxy preset/crf is the knob;
   `verify_source` re-decodes originals (2nd full decode per clip) —
   consider sampling fewer verification windows.
4. **YOLO on every proxy frame:** frame stride / lower proxy fps for
   feature extraction cuts the 20% candidates slice nearly linearly.
5. **Skip preview render by default** (`render_preview_segments` doubles
   ffmpeg work per session; only needed for operator review).
6. **`--threads` scaling:** mean load is 3-5 cores; on a 2-vCPU box set
   threads=2 and expect ~2x wall time, not failure — CPU degrades
   gracefully, RAM does not.
