# edl-agent web UI

React + TypeScript SPA for `edl-agent`'s local web UI (session upload, run
progress, hook/music pickers, debug views). Talks to the FastAPI JSON API in
`src/edl_agent/web/app.py`; see `AGENTS.md` at the repo root for the full
dev workflow.

```
npm install
npm run dev      # Vite dev server with HMR, proxies /api and /sessions to :8000
npm run build    # writes to ../src/edl_agent/web/static/ (gitignored)
npm run lint     # oxlint
npm run format   # oxfmt (--check for CI, no rewrite)
```

Run the Python server (`uv run scripts/run_web.py`) alongside `npm run dev`
so the proxied API calls have somewhere to go.

**If your shell has the `rtk` Claude Code hook enabled:** `rtk hook claude`
rewrites `npm run lint` to `rtk lint`, which always assumes ESLint and tries
to parse its output as ESLint JSON. This project uses oxlint, not ESLint, so
that rewrite breaks (`ESLint output (JSON parse failed...)`). Run
`npx oxlint` / `npx oxfmt --check src` directly, or `rtk proxy npm run lint`
to bypass the rewrite.
