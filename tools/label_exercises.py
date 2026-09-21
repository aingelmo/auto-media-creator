"""Standalone, one-time tool to hand-label the exercise shown in each past
session's video candidates, building ground truth to measure the selector's
exercise-labelling accuracy against (see tools/eval_exercises.py).

Not wired into edl_agent.web on purpose -- this is throwaway, same idiom as
tools/calibrate_prompts.py. Run:

    uv run python tools/label_exercises.py

Reads var/sessions/*/candidates.json, serves a single page showing each
video candidate's contact sheet (peaks/{cand_id}_contact.jpg, already built
by candidates.build.build_video_candidates) next to a dropdown of the
canonical exercise list, writes labels to var/exercise_ground_truth.json.
"""

from __future__ import annotations

import json
import sys
import webbrowser
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = ROOT / "var" / "sessions"
GROUND_TRUTH_PATH = ROOT / "var" / "exercise_ground_truth.json"

sys.path.insert(0, str(ROOT / "src"))
from edl_agent.selector._common import EXERCISES  # noqa: E402


def build_session_summary(session_dir: Path) -> dict | None:
    """Summarize one session's labellable candidates, or None if it has none."""
    candidates_path = session_dir / "candidates.json"
    if not candidates_path.exists():
        return None
    candidates = json.loads(candidates_path.read_text())["candidates"]
    items = [
        {"id": c["id"], "kind": c["kind"]}
        for c in candidates
        if c["kind"] != "image" and (session_dir / "peaks" / f"{c['id']}_contact.jpg").exists()
    ]
    if not items:
        return None
    return {"id": session_dir.name, "candidates": items}


def list_sessions() -> list[dict]:
    summaries = (
        build_session_summary(d) for d in sorted(SESSIONS_DIR.iterdir()) if d.is_dir()
    )
    return [s for s in summaries if s is not None]


def upsert_label(
    ground_truth_path: Path,
    session_id: str,
    candidate_id: str,
    exercise: str,
    note: str = "",
) -> dict:
    """Load, update, and persist the ground-truth file. Returns the full dict.

    `note` is a free-text description of what the movement actually is,
    kept separate from `exercise` (which must stay a canonical `EXERCISES`
    value, or blank, so `eval_exercises.py`'s equality check against the
    selector's output isn't broken by an out-of-taxonomy string) -- useful
    for "other" candidates where none of the enum entries fit.
    """
    ground_truth = {}
    if ground_truth_path.exists():
        ground_truth = json.loads(ground_truth_path.read_text())
    session = ground_truth.setdefault(session_id, {"candidates": {}, "notes": {}})
    session.setdefault("notes", {})
    if exercise:
        session["candidates"][candidate_id] = exercise
    else:
        session["candidates"].pop(candidate_id, None)
    if note:
        session["notes"][candidate_id] = note
    else:
        session["notes"].pop(candidate_id, None)
    session["labeled_at"] = datetime.now(UTC).isoformat()
    ground_truth_path.write_text(json.dumps(ground_truth, indent=2, ensure_ascii=False))
    return ground_truth


PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<title>Exercise labelling</title>
<style>
  body { font: 14px/1.4 system-ui, sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem; }
  .card { border: 1px solid #ccc; border-radius: 8px; padding: 1rem; margin-bottom: 1.5rem; }
  h3 { margin-top: 0; }
  .row { display: flex; align-items: center; gap: .8rem; padding: .4em 0; border-top: 1px solid #eee; }
  .row:first-of-type { border-top: none; }
  img { height: 110px; border-radius: 4px; }
  select { flex: 0 0 auto; }
  input[type=text] { flex: 1 1 auto; min-width: 8em; }
  input[type=text][hidden] { display: none; }
  .status { font-size: 12px; }
  .status.ok { color: #2a8; }
  .status.err { color: #c33; }
</style>
</head>
<body>
<h1>Exercise labelling</h1>
<div id="app">loading...</div>
<script>
const EXERCISES = __EXERCISES__;

async function main() {
  const sessions = await (await fetch('/api/sessions')).json();
  const app = document.getElementById('app');
  app.innerHTML = '';
  for (const s of sessions) app.appendChild(renderCard(s));
}

function renderCard(s) {
  const card = document.createElement('div');
  card.className = 'card';
  card.innerHTML = `<h3>${esc(s.id)}</h3>`;
  for (const c of s.candidates) {
    const row = document.createElement('div');
    row.className = 'row';
    const options = [
        '<option value="">-- sin etiquetar --</option>',
        `<option value="none" ${c.label === 'none' ? 'selected' : ''}>(ninguno -- no es un ejercicio)</option>`,
      ]
      .concat(EXERCISES.map(e => `<option value="${esc(e)}" ${e === c.label ? 'selected' : ''}>${esc(e)}</option>`))
      .join('');
    row.innerHTML = `
      <img src="/media/${s.id}/peaks/${c.id}_contact.jpg">
      <span>${esc(c.id)} (${esc(c.kind)})</span>
      <select>${options}</select>
      <input type="text" placeholder="qué es en realidad..." value="${esc(c.note)}" ${c.label === 'other' ? '' : 'hidden'}>
      <span class="status"></span>
    `;
    const select = row.querySelector('select');
    const note = row.querySelector('input');
    const status = row.querySelector('.status');
    const save = async () => {
      try {
        const res = await fetch('/api/label', {
          method: 'POST',
          body: JSON.stringify({
            session_id: s.id, candidate_id: c.id,
            exercise: select.value, note: note.value,
          }),
        });
        if (!res.ok) throw new Error('status ' + res.status);
        status.textContent = 'saved';
        status.className = 'status ok';
      } catch (e) {
        status.textContent = 'NOT SAVED -- ' + e.message;
        status.className = 'status err';
      }
    };
    select.onchange = () => {
      note.hidden = select.value !== 'other';
      save();
    };
    note.onblur = () => { if (!note.hidden) save(); };
    card.appendChild(row);
  }
  return card;
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

main();
</script>
</body></html>
""".replace("__EXERCISES__", json.dumps(EXERCISES))


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/api/sessions":
            ground_truth = {}
            if GROUND_TRUTH_PATH.exists():
                ground_truth = json.loads(GROUND_TRUTH_PATH.read_text())
            sessions = list_sessions()
            for s in sessions:
                labels = ground_truth.get(s["id"], {}).get("candidates", {})
                notes = ground_truth.get(s["id"], {}).get("notes", {})
                for c in s["candidates"]:
                    c["label"] = labels.get(c["id"], "")
                    c["note"] = notes.get(c["id"], "")
            self._json(sessions)
            return

        if self.path.startswith("/media/"):
            parts = self.path.removeprefix("/media/").split("/")
            if len(parts) == 3 and parts[1] == "peaks":
                session_id, _, filename = parts
                img_path = SESSIONS_DIR / session_id / "peaks" / filename
                if (
                    img_path.exists()
                    and SESSIONS_DIR.resolve() in img_path.resolve().parents
                ):
                    body = img_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
            self.send_error(404)
            return

        self.send_error(404)

    def do_POST(self):
        if self.path == "/api/label":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            ground_truth = upsert_label(
                GROUND_TRUTH_PATH,
                body["session_id"],
                body["candidate_id"],
                body.get("exercise", ""),
                body.get("note", ""),
            )
            self._json(ground_truth[body["session_id"]])
            return
        self.send_error(404)

    def log_message(self, fmt, *args):
        pass  # ponytail: quiet by default, uncomment for debugging

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if not isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            super().handle_error(request, client_address)


def main():
    port = 8766
    server = ThreadingHTTPServer(("localhost", port), Handler)
    url = f"http://localhost:{port}"
    print(f"Serving {url} (Ctrl+C to stop)")
    try:
        webbrowser.open(url)
    except Exception:
        pass  # no browser binary in this environment -- open the URL manually
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
