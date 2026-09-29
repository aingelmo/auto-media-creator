"""Resumable chunked uploads that fit through a 100 MB-capped proxy.

Cloudflare free/pro caps proxied request bodies at 100 MB total, so the
single-multipart `POST /api/sessions` in `routes/sessions.py` fails with
413 for large sessions before reaching the app (#4.3). This router splits
each file into small `PUT` chunks (frontend uses 2 MB bodies; the
per-request max stays 8 MB):

1. `POST /api/uploads/init` reserves an `upload_id` + staging dir.
2. `PUT /api/uploads/{id}/chunk?index=N&offset=M` appends one chunk.
3. `GET /api/uploads/{id}/status` reports `{received, size}` for resume.
4. `POST /api/uploads/{id}/complete` verifies size/hash and moves the
   file into `SESSIONS_DIR/{session}/{inputs,music,brand}/`.

The frontend (`frontend/src/api.ts:uploadFileChunked`) drives the steps
with 2 MB `Blob.slice` windows, then submits `POST /api/sessions`
with only upload-ids + refs + text fields (tiny body). Abandoned staging
dirs expire after 24h via an mtime sweep on init/complete.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from edl_agent.paths import CACHE_DIR, SESSIONS_DIR
from edl_agent.session._common import IMAGE_EXTS, MUSIC_EXTS, VIDEO_EXTS

router = APIRouter()

CHUNK_SIZE = 8 * 1024 * 1024
MAX_FILE_SIZE = 5 * 1024**3
UPLOAD_TTL_S = 24 * 3600

_KIND_DIRS = {"clip": "inputs", "music": "music", "logo": "brand"}
_KIND_EXTS = {
    "clip": VIDEO_EXTS | IMAGE_EXTS,
    "music": MUSIC_EXTS,
    "logo": IMAGE_EXTS,
}
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class InitRequest(BaseModel):
    """Reservation for one file's chunk stream (see `init_upload`)."""

    session_name: str
    kind: Literal["clip", "music", "logo"]
    filename: str
    size: int
    sha256: str | None = None


def uploads_dir() -> Path:
    """Staging root for in-progress uploads (respects `EDL_AGENT_VAR`).

    Returns:
        `CACHE_DIR/uploads`, created on demand.
    """
    d = CACHE_DIR / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sweep_expired() -> None:
    """Delete staging dirs whose mtime is older than `UPLOAD_TTL_S`.

    Abandoned uploads (browser closed mid-stream) would otherwise pin
    disk forever. Runs best-effort on init/complete; failures are
    ignored so housekeeping never breaks an upload.
    """
    try:
        root = uploads_dir()
    except OSError:
        return
    now = time.time()
    try:
        children = list(root.iterdir())
    except OSError:
        return
    for child in children:
        if not child.is_dir():
            continue
        try:
            if now - child.stat().st_mtime > UPLOAD_TTL_S:
                shutil.rmtree(child, ignore_errors=True)
        except OSError:
            continue


def _check_upload_id(upload_id: str) -> None:
    """Reject path-traversal upload ids before touching the filesystem.

    Args:
        upload_id: Opaque id minted by `init_upload`.

    Raises:
        HTTPException: 404 when the id has unexpected characters.
    """
    if not _ID_RE.fullmatch(upload_id):
        raise HTTPException(status_code=404, detail="no such upload")


def _staging_dir(upload_id: str) -> Path:
    """Staging directory for one upload.

    Args:
        upload_id: Opaque id minted by `init_upload`.

    Returns:
        Path `CACHE_DIR/uploads/{upload_id}` (may not exist yet).

    Raises:
        HTTPException: 404 for malformed ids (see `_check_upload_id`).
    """
    _check_upload_id(upload_id)
    return uploads_dir() / upload_id


def _read_meta(upload_id: str) -> dict:
    """Load and validate the staging `meta.json` for one upload.

    Args:
        upload_id: Opaque id minted by `init_upload`.

    Returns:
        Meta dict with `session_name`, `kind`, `filename`, `size`,
        `sha256` (or `None`), `received`, `completed`, `final_rel`
        (or `None` until `complete_upload` moves the file).

    Raises:
        HTTPException: 404 when the staging dir or meta is missing.
    """
    meta_path = _staging_dir(upload_id) / "meta.json"
    if not meta_path.is_file():
        raise HTTPException(status_code=404, detail="no such upload")
    try:
        return json.loads(meta_path.read_text())
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="no such upload") from None


def _write_meta(upload_id: str, meta: dict) -> None:
    """Persist staging meta atomically (crash-safe resume bitmap).

    Args:
        upload_id: Opaque id minted by `init_upload`.
        meta: JSON-serializable dict (see `_read_meta`).

    Raises:
        HTTPException: 500 when the write fails.
    """
    meta_path = _staging_dir(upload_id) / "meta.json"
    try:
        tmp = meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta))
        tmp.replace(meta_path)
    except OSError as e:
        msg = f"cannot persist upload: {e}"
        raise HTTPException(status_code=500, detail=msg) from e


def _validate_new_upload(body: InitRequest) -> str:
    """Validate init fields and return the sanitized filename.

    Args:
        body: Parsed `InitRequest` JSON body.

    Returns:
        Sanitized base filename safe to join under the session dir.

    Raises:
        HTTPException: 400 on bad session name, filename traversal,
            disallowed extension, out-of-range size, or malformed hash.
    """
    if not _NAME_RE.fullmatch(body.session_name):
        raise HTTPException(status_code=400, detail="bad session_name")
    filename = body.filename
    if (
        not filename
        or "/" in filename
        or "\\" in filename
        or ".." in filename
        or "\x00" in filename
        or Path(filename).name != filename
    ):
        raise HTTPException(status_code=400, detail="bad filename")
    allowed = _KIND_EXTS[body.kind]
    if Path(filename).suffix.lower() not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"{body.kind} must be one of {sorted(allowed)}, "
            f"got {Path(filename).suffix.lower()!r}.",
        )
    if body.size <= 0 or body.size > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="bad size")
    if body.sha256 is not None and not _SHA_RE.fullmatch(body.sha256):
        raise HTTPException(status_code=400, detail="bad sha256")
    return Path(filename).name


def _final_name(kind: str, filename: str) -> str:
    """Destination basename inside the session dir for a kind.

    Args:
        kind: `"clip"`, `"music"`, or `"logo"`.
        filename: Sanitized base filename from `_validate_new_upload`.

    Returns:
        `filename` for clips/music; always `"logo.png"` for logos so
        the render step finds the brand path recorded in `brand.json`
        (same convention as `routes/config.py:save_brand`).
    """
    if kind == "logo":
        return "logo.png"
    return filename


def _unique_dest(dest_dir: Path, name: str) -> Path:
    """Non-colliding destination inside `dest_dir` for repeated uploads.

    Args:
        dest_dir: Already-created session subdirectory.
        name: Desired basename from `_final_name`.

    Returns:
        `dest_dir/name`, or `dest_dir/{stem}_{n}{suffix}` while taken
        (mirrors `routes/sessions.py:_link_ref` dedupe).
    """
    dest = dest_dir / name
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 1
    while dest.exists():
        dest = dest_dir / f"{stem}_{n}{suffix}"
        n += 1
    return dest


@router.post("/api/uploads/init")
def init_upload(body: InitRequest) -> dict:
    """Reserve a staging dir for one file's chunk stream.

    Args:
        body: Dict with `session_name` (new-session charset), `kind`
            (`"clip"` | `"music"` | `"logo"`), `filename` (bare base
            name, no directories), `size` (total bytes, 1..5 GB), and
            optional `sha256` hex digest verified at complete time.

    Returns:
        Dict with `upload_id` (opaque, used in chunk/complete URLs)
        and `chunk_size` (8 MB; every `PUT` body must fit).

    Raises:
        HTTPException: 400 on invalid fields (see
            `_validate_new_upload`).
    """
    _sweep_expired()
    filename = _validate_new_upload(body)
    upload_id = uuid.uuid4().hex
    staged = _staging_dir(upload_id)
    staged.mkdir(parents=True, exist_ok=True)
    _write_meta(
        upload_id,
        {
            "session_name": body.session_name,
            "kind": body.kind,
            "filename": filename,
            "size": body.size,
            "sha256": body.sha256.lower() if body.sha256 else None,
            "received": 0,
            "completed": False,
            "final_rel": None,
        },
    )
    (staged / "data.bin").write_bytes(b"")
    return {"upload_id": upload_id, "chunk_size": CHUNK_SIZE}


@router.put("/api/uploads/{upload_id}/chunk")
async def put_chunk(upload_id: str, request: Request, index: int, offset: int) -> dict:
    """Append one <=8 MB chunk at the current end of the stream.

    Chunks are sequential: `offset` must equal bytes received so far, so
    a retry after a dropped connection resumes exactly where it stopped.
    `index` is an informational sequence number from the client (the
    frontend sends `offset // <its own 2 MB slice size>`) and is only
    range-checked, not tied to the 8 MB server max — sub-max slices
    would otherwise never align to the server grid. Meta is
    rewritten after every append, so resume survives a restart.

    Args:
        upload_id: Opaque id from `init_upload`.
        request: Raw `application/octet-stream` chunk body.
        index: Client chunk sequence number (non-negative).
        offset: Byte offset the chunk starts at (must equal the
            bytes received so far).

    Returns:
        Dict with `upload_id`, `received` (total bytes so far),
        `size` (declared total), and `done` (received == size).

    Raises:
        HTTPException: 404 for unknown ids; 409 when `offset`
            disagrees with the stored progress; 400 for empty or
            over-8 MB bodies; 413 when the chunk would overflow the
            declared size.
    """
    meta = _read_meta(upload_id)
    if meta.get("completed"):
        raise HTTPException(status_code=400, detail="upload already completed")
    if index < 0 or offset < 0:
        raise HTTPException(status_code=409, detail="index/offset mismatch")
    if offset != meta["received"]:
        raise HTTPException(
            status_code=409,
            detail=f"offset mismatch: expected {meta['received']}, got {offset}",
        )
    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="empty chunk")
    if len(body) > CHUNK_SIZE:
        raise HTTPException(status_code=400, detail="chunk too large")
    if meta["received"] + len(body) > meta["size"]:
        raise HTTPException(status_code=413, detail="chunk overflows declared size")
    staged = _staging_dir(upload_id)
    try:
        with (staged / "data.bin").open("ab") as f:
            f.write(body)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"cannot store chunk: {e}") from e
    meta["received"] += len(body)
    _write_meta(upload_id, meta)
    return {
        "upload_id": upload_id,
        "received": meta["received"],
        "size": meta["size"],
        "done": meta["received"] == meta["size"],
    }


@router.get("/api/uploads/{upload_id}/status")
def upload_status(upload_id: str) -> dict:
    """Report resumable-upload progress for retry/resume.

    The frontend calls this after a chunk `PUT` gets a 409
    offset-mismatch (or a network error that may have landed
    server-side) to learn the authoritative `received` byte count
    and continue from there instead of failing or re-sending
    bytes the server already has.

    Args:
        upload_id: Opaque id from `init_upload`.

    Returns:
        Dict with `upload_id`, `received` (bytes stored so far),
        `size` (declared total), `done` (received == size), and
        `completed` (whether `complete_upload` already ran).

    Raises:
        HTTPException: 404 for unknown ids (see `_read_meta`).
    """
    meta = _read_meta(upload_id)
    received = int(meta.get("received", 0))
    size = int(meta.get("size", 0))
    return {
        "upload_id": upload_id,
        "received": received,
        "size": size,
        "done": received == size,
        "completed": bool(meta.get("completed")),
    }


def _move_into_place(meta: dict) -> tuple[Path, str]:
    """Move staged `data.bin` to its session dir, returning path + ref.

    Args:
        meta: Completed-upload meta dict (see `_read_meta`).

    Returns:
        Tuple of the absolute destination path and the `"{session}/{rel}"`
        media ref the frontend stores (same shape as `GET /api/media`).

    Raises:
        HTTPException: 500 when the move fails.
    """
    session_dir = SESSIONS_DIR / meta["session_name"]
    dest_dir = session_dir / _KIND_DIRS[meta["kind"]]
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = _unique_dest(dest_dir, _final_name(meta["kind"], meta["filename"]))
    try:
        shutil.move(str(_staging_dir(meta["_upload_id"]) / "data.bin"), str(dest))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"cannot store file: {e}") from e
    rel = f"{_KIND_DIRS[meta['kind']]}/{dest.name}"
    return dest, f"{meta['session_name']}/{rel}"


@router.post("/api/uploads/{upload_id}/complete")
def complete_upload(upload_id: str) -> dict:
    """Verify size/hash, move the file into the session dir, keep a receipt.

    Args:
        upload_id: Opaque id from `init_upload` after all chunks.

    Returns:
        Dict with `upload_id`, `ref` (`"{session}/{dir}/{file}"`),
        `filename` (final basename), and `size`.

    Raises:
        HTTPException: 404 for unknown ids; 400 when chunks are
            missing or the sha256 mismatches.
    """
    _sweep_expired()
    meta = _read_meta(upload_id)
    if meta.get("completed"):
        return {
            "upload_id": upload_id,
            "ref": f"{meta['session_name']}/{meta['final_rel']}",
            "filename": Path(meta["final_rel"]).name,
            "size": meta["size"],
        }
    staged = _staging_dir(upload_id)
    data = staged / "data.bin"
    try:
        actual = data.stat().st_size if data.is_file() else -1
    except OSError:
        actual = -1
    if actual != meta["size"]:
        raise HTTPException(
            status_code=400,
            detail=f"incomplete upload: received {max(actual, 0)} of {meta['size']}",
        )
    if meta.get("sha256"):
        digest = hashlib.sha256()
        with data.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != meta["sha256"]:
            raise HTTPException(status_code=400, detail="sha256 mismatch")
    meta["_upload_id"] = upload_id
    _dest, ref = _move_into_place(meta)
    rel = ref.partition("/")[2]
    meta["completed"] = True
    meta["final_rel"] = rel
    meta.pop("_upload_id", None)
    _write_meta(upload_id, meta)
    return {
        "upload_id": upload_id,
        "ref": ref,
        "filename": Path(rel).name,
        "size": meta["size"],
    }


def claim_completed_upload(upload_id: str, session_name: str, kind: str) -> Path:
    """Resolve a completed upload into its final session file.

    Used by `POST /api/sessions` (`routes/sessions.py:create_session`)
    to link chunked uploads the same way `_link_ref`/copy handles
    library refs and fresh multipart files.

    Args:
        upload_id: Opaque id from `init_upload` (must be completed).
        session_name: New-session name the upload was reserved for.
        kind: Expected `"clip"`, `"music"`, or `"logo"`.

    Returns:
        Absolute path of the final file under
        `SESSIONS_DIR/{session_name}/{inputs,music,brand}/`.

    Raises:
        HTTPException: 404 for unknown ids or a missing final file;
            400 when the upload targets another session/kind or is
            not completed yet.
    """
    _check_upload_id(upload_id)
    meta = _read_meta(upload_id)
    if meta.get("session_name") != session_name or meta.get("kind") != kind:
        msg = "upload does not match session/kind"
        raise HTTPException(status_code=400, detail=msg)
    if not meta.get("completed"):
        raise HTTPException(status_code=400, detail="upload not completed")
    rel = meta.get("final_rel") or ""
    if not rel or ".." in rel or rel.startswith("/"):
        raise HTTPException(status_code=404, detail="upload file missing")
    final = (SESSIONS_DIR / session_name / rel).resolve()
    root = SESSIONS_DIR.resolve()
    if root not in final.parents or not final.is_file():
        staged = _staging_dir(upload_id) / "data.bin"
        if staged.is_file():
            dest_dir = SESSIONS_DIR / session_name / _KIND_DIRS[kind]
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = _unique_dest(dest_dir, _final_name(kind, meta["filename"]))
            shutil.move(str(staged), str(dest))
            meta["final_rel"] = f"{_KIND_DIRS[kind]}/{dest.name}"
            _write_meta(upload_id, meta)
            return dest.resolve()
        raise HTTPException(status_code=404, detail="upload file missing")
    return final
