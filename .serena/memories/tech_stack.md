# Tech Stack

- Python >=3.14, managed with `uv` (uv.lock present, `uv_build` backend).
- Package name `edl-agent`, source layout `src/edl_agent/` (see `mem:core` for the
  per-layer package breakdown).
- Key deps: `google-genai` (Gemini selector, default), `ultralytics`/YOLO pose model
  (`models/yolov8n-pose.pt`) + `opencv-python-headless` for video features,
  `librosa` for audio/beat detection, `scenedetect` for scene cuts, `pandas`/`pyarrow`
  for features storage (parquet), `pillow`/`pillow-heif` for image normalization.
- ffmpeg is invoked as an external CLI (subprocess) for proxies, tonemap, segment
  rendering, concat and loudnorm — not a Python binding.
- Dev dep group: `pytest`, `ruff`, `ty`.
- `[tool.ruff]` in pyproject.toml: explicit `select` of rule families (deliberately
  not `ALL`, per ruff's own advice against it), with a documented `ignore` list
  (e.g. S603/S607 for ffmpeg subprocess calls, PLC0415 for intentional lazy imports
  of slow/optional deps, D100/D104/D105/D107 for module/dunder docstrings).
  pydocstyle convention is `google`. Per-file-ignores relax `tests/**`/`scripts/**`.
- `ty` is the type checker (`[tool.ty.environment]`, python-version 3.14); run via
  `uv run ty check`. No mypy.
