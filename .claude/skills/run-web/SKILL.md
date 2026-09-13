---
name: run-web
description: Launch the edl-agent local web UI (FastAPI/uvicorn) for debugging.
---

Start the server in the background, then smoke-test it:

```bash
uv run scripts/run_web.py > /tmp/web_ui.log 2>&1 &
disown
sleep 3
curl -s -o /dev/null -w "GET / -> %{http_code}\n" http://127.0.0.1:8000/
```

- UI: http://127.0.0.1:8000
- Logs: `/tmp/web_ui.log`
- No project skill dependency; runs directly from repo root with `uv`.
