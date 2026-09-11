# Tech Stack

- Python >=3.14, managed with `uv` (uv.lock present, `uv_build` backend).
- Package name `edl-agent`, source layout `src/edl_agent/`.
- Key deps: `google-genai` (Gemini selector, default), `ultralytics`/YOLO pose model
  (`models/yolov8n-pose.pt`) + `opencv-python-headless` for video features,
  `librosa` for audio/beat detection, `scenedetect` for scene cuts, `pandas`/`pyarrow`
  for features storage (parquet), `pillow`/`pillow-heif` for image normalization.
- ffmpeg is invoked as an external CLI (subprocess) for proxies, tonemap, segment
  rendering, concat and loudnorm — not a Python binding.
- Dev dep group: `pytest`. `.ruff_cache/` exists (ruff used) but no `[tool.ruff]`
  config in pyproject.toml — defaults apply.
- No mypy/type-checker config found.
