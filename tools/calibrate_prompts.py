"""Standalone, one-time tool to review past reels and flag good/bad results
to guide prompt calibration for the selector and hook-copy prompts.

Not wired into edl_agent.web on purpose -- this is throwaway. Run:

    uv run python tools/calibrate_prompts.py

Reads var/sessions/*/hooks.json + reel video, serves a single page to watch
each reel and thumbs-up/down each generated hook line with an explanation,
writes ratings to var/prompt_calibration_ratings.json.
"""

from __future__ import annotations

import json
import webbrowser
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SESSIONS_DIR = ROOT / "var" / "sessions"
RATINGS_PATH = ROOT / "var" / "prompt_calibration_ratings.json"
VIDEO_NAMES = ("reel.prev.mp4", "reel.mp4")


def build_session_summary(session_dir: Path) -> dict | None:
    """Summarize one session for review, or None if it has no reel video."""
    video = next((n for n in VIDEO_NAMES if (session_dir / n).exists()), None)
    if video is None:
        return None

    hook = None
    hooks_path = session_dir / "hooks.json"
    if hooks_path.exists():
        h = json.loads(hooks_path.read_text())
        hook = {
            "line": h.get("hook_line"),
            "alternates": h.get("hooks", []),
            "dropped": h.get("dropped") or [],
        }

    return {
        "id": session_dir.name,
        "video": video,
        "hook": hook,
    }


def list_sessions() -> list[dict]:
    summaries = (
        build_session_summary(d) for d in sorted(SESSIONS_DIR.iterdir()) if d.is_dir()
    )
    return [s for s in summaries if s is not None]


def upsert_rating(ratings_path: Path, session_id: str, hooks: list[dict]) -> dict:
    """Load, update, and persist the ratings file. Returns the full ratings dict.

    `hooks` is a list of per-alternate ratings:
    `[{"angle", "hook_line", "good", "note"}, ...]`, one per hook line the
    reviewer judged (thumbs up/down + why).
    """
    ratings = {}
    if ratings_path.exists():
        ratings = json.loads(ratings_path.read_text())
    ratings[session_id] = {
        "hooks": hooks,
        "rated_at": datetime.now(UTC).isoformat(),
    }
    ratings_path.write_text(json.dumps(ratings, indent=2, ensure_ascii=False))
    return ratings


PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<title>Prompt calibration review</title>
<style>
  body { font: 14px/1.4 system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; }
  .card { border: 1px solid #ccc; border-radius: 8px; padding: 1rem; margin-bottom: 1.5rem; }
  video { width: 260px; flex: 0 0 auto; border-radius: 4px; }
  h3 { margin-top: 0; }
  .dim { color: #777; }
  .dropped { color: #a33; font-size: 12px; }
  .hookrow { border-top: 1px solid #eee; padding: .6em 0; }
  .hookrow:first-of-type { border-top: none; }
  .angle { color: #777; font-size: 12px; margin-right: .4em; }
  .hookrow textarea { width: 100%; height: 2.4em; margin-top: .3em; box-sizing: border-box; }
  button.up, button.down { padding: .2em .7em; margin-right: .5em; cursor: pointer; }
  button.up.active { background: #2a8; color: #fff; }
  button.down.active { background: #c33; color: #fff; }
  .clearfix { display: flex; align-items: flex-start; gap: 1rem; }
  .clearfix .hooks { flex: 1 1 auto; min-width: 0; }
  .status { font-size: 12px; margin-left: .6em; }
  .status.ok { color: #2a8; }
  .status.err { color: #c33; }
</style>
</head>
<body>
<h1>Prompt calibration review</h1>
<div id="app">loading...</div>
<script>
async function main() {
  const sessions = await (await fetch('/api/sessions')).json();
  const app = document.getElementById('app');
  app.innerHTML = '';
  for (const s of sessions) {
    app.appendChild(renderCard(s));
  }
}

function renderCard(s) {
  const card = document.createElement('div');
  card.className = 'card';

  const savedByLine = {};
  if (s.rating && s.rating.hooks) for (const h of s.rating.hooks) savedByLine[h.hook_line] = h;

  const alternates = s.hook ? s.hook.alternates : [];
  const rows = alternates.map((h, i) => {
    const prev = savedByLine[h.hook_line];
    return `
      <div class="hookrow" data-angle="${esc(h.angle)}" data-line="${esc(h.hook_line)}">
        <span class="angle">[${esc(h.angle)}]</span>${esc(h.hook_line)}<br>
        <button class="up" data-good="true">👍</button>
        <button class="down" data-good="false">👎</button>
        <textarea placeholder="why?">${prev ? esc(prev.note) : ''}</textarea>
      </div>`;
  }).join('');
  const dropped = s.hook && s.hook.dropped.length
    ? `<p class="dropped">Dropped: ${s.hook.dropped.map(d => `${esc(d.hook_line)} (${d.why})`).join(', ')}</p>`
    : '';
  const hookBlock = s.hook ? `${rows}${dropped}` : '<p class="dim">no hooks.json</p>';

  card.innerHTML = `
    <div class="clearfix">
      <video controls preload="metadata" src="/media/${s.id}/${s.video}"></video>
      <div class="hooks">
        <h3>${s.id} <span class="status"></span></h3>
        ${hookBlock}
      </div>
    </div>
  `;

  const status = card.querySelector('.status');
  const save = async () => {
    const hooks = [];
    for (const row of card.querySelectorAll('.hookrow')) {
      const good = row._getGood();
      if (good === null) continue; // unrated line, skip
      hooks.push({
        angle: row.dataset.angle,
        hook_line: row.dataset.line,
        good,
        note: row.querySelector('textarea').value,
      });
    }
    try {
      const res = await fetch('/api/rate', {
        method: 'POST',
        body: JSON.stringify({ session_id: s.id, hooks }),
      });
      if (!res.ok) throw new Error('status ' + res.status);
      status.textContent = 'saved';
      status.className = 'status ok';
    } catch (e) {
      status.textContent = 'NOT SAVED — ' + e.message;
      status.className = 'status err';
    }
  };

  for (const row of card.querySelectorAll('.hookrow')) {
    const line = row.dataset.line;
    const prev = savedByLine[line];
    let good = prev ? prev.good : null;
    const upBtn = row.querySelector('.up');
    const downBtn = row.querySelector('.down');
    const sync = () => {
      upBtn.classList.toggle('active', good === true);
      downBtn.classList.toggle('active', good === false);
    };
    sync();
    upBtn.onclick = () => { good = true; sync(); save(); };
    downBtn.onclick = () => { good = false; sync(); save(); };
    row._getGood = () => good;
    row.querySelector('textarea').onblur = () => { if (good !== null) save(); };
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
"""


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_video(self, path: Path):
        # Range support so <video> scrubbing works -- browsers refuse to
        # seek on a 200 response with no Accept-Ranges/206 handling.
        size = path.stat().st_size
        range_header = self.headers.get("Range")
        start, end = 0, size - 1
        status = 200
        if range_header and range_header.startswith("bytes="):
            status = 206
            spec = range_header.removeprefix("bytes=")
            start_s, _, end_s = spec.partition("-")
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else size - 1
            end = min(end, size - 1)

        self.send_response(status)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        try:
            with path.open("rb") as f:
                f.seek(start)
                self.wfile.write(f.read(end - start + 1))
        except (BrokenPipeError, ConnectionResetError):
            pass  # ponytail: browser aborted the fetch (seek/reload), not our bug

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
            ratings = {}
            if RATINGS_PATH.exists():
                ratings = json.loads(RATINGS_PATH.read_text())
            sessions = list_sessions()
            for s in sessions:
                s["rating"] = ratings.get(s["id"])
            self._json(sessions)
            return

        if self.path.startswith("/media/"):
            parts = self.path.removeprefix("/media/").split("/")
            if len(parts) == 2 and parts[1] in VIDEO_NAMES:
                session_id, filename = parts
                video_path = SESSIONS_DIR / session_id / filename
                # path-traversal guard: must resolve inside SESSIONS_DIR
                if (
                    video_path.exists()
                    and SESSIONS_DIR.resolve() in video_path.resolve().parents
                ):
                    self._serve_video(video_path)
                    return
            self.send_error(404)
            return

        self.send_error(404)

    def do_POST(self):
        if self.path == "/api/rate":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            ratings = upsert_rating(RATINGS_PATH, body["session_id"], body.get("hooks", []))
            self._json(ratings[body["session_id"]])
            return
        self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        pass  # ponytail: quiet by default, uncomment for debugging


def main():
    port = 8765
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
