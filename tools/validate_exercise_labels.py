"""Standalone tool: eyeball the open-vocabulary selector's exercise labels
(no more canonical enum, see prompts.py) with a plain thumbs up/down per
candidate -- a sanity check, not the rigorous ground-truth scoring that
tools/eval_exercises.py does against hand-typed canonical names (which no
longer applies now that `exercise` is free text).

Two steps, same idiom as tools/eval_exercises.py (real select(), scratch
dir, real client):

    uv run python tools/validate_exercise_labels.py --predict [session_id ...]
    uv run python tools/validate_exercise_labels.py           # serve review UI

Predictions are cached to var/exercise_openvocab_predictions.json so the
review server doesn't re-call the LLM; verdicts go to
var/exercise_openvocab_verdicts.json.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = ROOT / "var" / "sessions"
PREDICTIONS_PATH = ROOT / "var" / "exercise_openvocab_predictions.json"
VERDICTS_PATH = ROOT / "var" / "exercise_openvocab_verdicts.json"

sys.path.insert(0, str(ROOT / "src"))
# candidates.json's peak_frames are relative to var/ -- match the app's own
# cwd expectation (see tools/eval_exercises.py, same idiom).
os.chdir(ROOT / "var")

from edl_agent.candidates._common import FPS
from edl_agent.llm import get_client
from edl_agent.selector import select
from edl_agent.web.pipeline import DEFAULT_MODELS

MODEL_TO_PROVIDER = {v: k for k, v in DEFAULT_MODELS.items()}
THEME = "training"


def predict_session(session_id: str) -> dict[str, dict]:
    """Re-run the real selector on one session. Returns `{cand_id: {exercise,
    exercise_confidence}}` for every *selected* candidate (unselected ones
    have nothing to review)."""
    session_dir = SESSIONS_DIR / session_id
    candidates_json = json.loads((session_dir / "candidates.json").read_text())
    slots_json = json.loads((session_dir / "slots.json").read_text())
    duration_s = slots_json["duration_f"] / FPS

    selection_meta_path = session_dir / "selection_meta.json"
    model = DEFAULT_MODELS["gemini"]
    if selection_meta_path.exists():
        model = json.loads(selection_meta_path.read_text()).get("model", model)
    client = get_client(MODEL_TO_PROVIDER.get(model, "gemini"))

    with tempfile.TemporaryDirectory() as scratch:
        selection, _meta = select(
            candidates_json, slots_json, duration_s, client, Path(scratch),
            config={"theme": THEME, "model": model},
        )
    if selection is None:
        return {}
    return {
        e["candidate_id"]: {
            "exercise": e["exercise"],
            "exercise_confidence": e["exercise_confidence"],
        }
        for e in selection["selected"]
    }


def run_predict(session_ids: list[str]) -> None:
    predictions = json.loads(PREDICTIONS_PATH.read_text()) if PREDICTIONS_PATH.exists() else {}
    wanted = session_ids or [d.name for d in sorted(SESSIONS_DIR.iterdir()) if d.is_dir()]
    for session_id in wanted:
        if not (SESSIONS_DIR / session_id / "candidates.json").exists():
            continue
        print(f"predicting {session_id}...")
        predictions[session_id] = predict_session(session_id)
    PREDICTIONS_PATH.write_text(json.dumps(predictions, indent=2, ensure_ascii=False))
    print(f"wrote {PREDICTIONS_PATH}")


def upsert_verdict(session_id: str, candidate_id: str, verdict: str, correction: str = "") -> dict:
    """`correction` is the true exercise name, typed in only when `verdict ==
    "down"` -- what tools/label_exercises.py calls a note, here promoted to a
    real field since it's expected to be filled in every time, not just for
    an "other" catch-all."""
    verdicts = json.loads(VERDICTS_PATH.read_text()) if VERDICTS_PATH.exists() else {}
    session = verdicts.setdefault(session_id, {})
    if verdict:
        session[candidate_id] = {"verdict": verdict, "correction": correction}
    else:
        session.pop(candidate_id, None)
    VERDICTS_PATH.write_text(json.dumps(verdicts, indent=2, ensure_ascii=False))
    return verdicts


PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<title>Exercise label validation</title>
<style>
  body { font: 14px/1.4 system-ui, sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem; }
  .card { border: 1px solid #ccc; border-radius: 8px; padding: 1rem; margin-bottom: 1.5rem; }
  h3 { margin-top: 0; }
  .row { display: flex; align-items: center; gap: .8rem; padding: .4em 0; border-top: 1px solid #eee; }
  .row:first-of-type { border-top: none; }
  img { height: 110px; border-radius: 4px; }
  .label { flex: 1 1 auto; }
  .conf { color: #888; font-size: 12px; }
  button { font-size: 16px; border: 1px solid #ccc; border-radius: 4px; background: #fff; cursor: pointer; padding: .2em .5em; }
  button.active.up { background: #2a8; border-color: #2a8; }
  button.active.down { background: #c33; border-color: #c33; }
  input[type=text] { flex: 1 1 auto; min-width: 8em; }
  input[type=text][hidden] { display: none; }
</style>
</head>
<body>
<h1>Exercise label validation (open vocabulary)</h1>
<div id="app">loading...</div>
<script>
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
    row.innerHTML = `
      <img src="/media/${s.id}/peaks/${c.id}_contact.jpg">
      <span class="label">${esc(c.id)} -- <b>${esc(c.exercise)}</b> <span class="conf">(${esc(c.confidence)})</span></span>
      <button class="up ${c.verdict === 'up' ? 'active' : ''}">👍</button>
      <button class="down ${c.verdict === 'down' ? 'active' : ''}">👎</button>
      <input type="text" placeholder="cuál era en realidad..." value="${esc(c.correction)}" ${c.verdict === 'down' ? '' : 'hidden'}>
    `;
    const up = row.querySelector('.up');
    const down = row.querySelector('.down');
    const correction = row.querySelector('input');
    const save = async (verdict) => {
      await fetch('/api/verdict', {
        method: 'POST',
        body: JSON.stringify({
          session_id: s.id, candidate_id: c.id,
          verdict, correction: verdict === 'down' ? correction.value : '',
        }),
      });
    };
    const vote = (verdict) => {
      const next = (verdict === 'up' ? up : down).classList.contains('active') ? '' : verdict;
      up.classList.toggle('active', next === 'up');
      down.classList.toggle('active', next === 'down');
      correction.hidden = next !== 'down';
      save(next);
    };
    up.onclick = () => vote('up');
    down.onclick = () => vote('down');
    let saveTimer;
    correction.oninput = () => {
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => save('down'), 400);
    };
    correction.onblur = () => { clearTimeout(saveTimer); if (!correction.hidden) save('down'); };
    card.appendChild(row);
  }
  return card;
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML.replace(/"/g, '&quot;');
}

main();
</script>
</body></html>
"""


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
            predictions = json.loads(PREDICTIONS_PATH.read_text()) if PREDICTIONS_PATH.exists() else {}
            verdicts = json.loads(VERDICTS_PATH.read_text()) if VERDICTS_PATH.exists() else {}
            sessions = []
            for session_id, preds in sorted(predictions.items()):
                session_verdicts = verdicts.get(session_id, {})
                candidates = []
                for cand_id, pred in preds.items():
                    contact = SESSIONS_DIR / session_id / "peaks" / f"{cand_id}_contact.jpg"
                    if not contact.exists():
                        continue
                    v = session_verdicts.get(cand_id, {})
                    candidates.append(
                        {
                            "id": cand_id,
                            "exercise": pred["exercise"],
                            "confidence": pred["exercise_confidence"],
                            "verdict": v.get("verdict", ""),
                            "correction": v.get("correction", ""),
                        }
                    )
                if candidates:
                    sessions.append({"id": session_id, "candidates": candidates})
            self._json(sessions)
            return

        if self.path.startswith("/media/"):
            parts = self.path.removeprefix("/media/").split("/")
            if len(parts) == 3 and parts[1] == "peaks":
                session_id, _, filename = parts
                img_path = SESSIONS_DIR / session_id / "peaks" / filename
                if img_path.exists() and SESSIONS_DIR.resolve() in img_path.resolve().parents:
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
        if self.path == "/api/verdict":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            verdicts = upsert_verdict(
                body["session_id"], body["candidate_id"],
                body.get("verdict", ""), body.get("correction", ""),
            )
            self._json(verdicts[body["session_id"]])
            return
        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        pass  # ponytail: quiet by default, uncomment for debugging


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_ids", nargs="*", help="Restrict to these sessions.")
    parser.add_argument("--predict", action="store_true", help="Run the selector and cache predictions, then exit.")
    args = parser.parse_args()

    if args.predict:
        run_predict(args.session_ids)
        return

    port = 8767
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
