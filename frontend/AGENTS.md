# AGENTS.md (frontend)

React/TS SPA for `edl-agent`'s web UI. Builds into
`../src/edl_agent/web/static/` (gitignored build output, so the Python
server needs no node toolchain at runtime). See the root `AGENTS.md` for
overall project context.

## Setup / commands

- `npm install`
- `npm run dev` — Vite dev server with HMR; proxies `/api` and
  `/sessions/*/files` to `:8000`, so run `uv run scripts/run_web.py`
  alongside it.
- `npm run build` — writes to `../src/edl_agent/web/static/`. Run it to
  verify a UI change compiles — that output is what the Python server
  serves, but it is gitignored, so only `frontend/src/` is committed.
- Checks (all must pass): `npx oxlint`, `npx oxfmt --check src`,
  `npx tsc -b --noEmit`, `npm run build`.

If your shell rewrites `npm run lint`/`npm run format` via an `rtk` hook,
it assumes ESLint/Prettier and breaks on this project's oxlint/oxfmt setup
— run `npx oxlint` / `npx oxfmt --check src` directly instead.

## Conventions

- Pages live under `src/pages/`, shared components under `src/components/`.
- Talk to the backend through the `/api/*` JSON endpoints and the
  `/sessions/{name}/...` file/reel routes — both are stable HTTP contracts
  documented in the Python route modules (`src/edl_agent/web/routes/`), not
  implementation details that move with backend refactors.
