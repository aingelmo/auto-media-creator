# edl-agent web UI

React + TypeScript SPA for `edl-agent`'s local web UI (session upload, run
progress, hook/music pickers, debug views). Talks to the FastAPI JSON API in
`src/edl_agent/web/app.py`; see `AGENTS.md` at the repo root for the full
dev workflow.

```
npm install
npm run dev      # Vite dev server with HMR, proxies /api and /sessions to :8000
npm run build    # writes to ../src/edl_agent/web/static/ (committed to git)
npm run lint     # oxlint
```

Run the Python server (`uv run scripts/run_web.py`) alongside `npm run dev`
so the proxied API calls have somewhere to go.
