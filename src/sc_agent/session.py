"""Disk-backed session state.

Each curated tool runs as a separate call on the LangGraph server, so the working
``AnnData`` cannot live in process memory reliably. Instead it is persisted to a single
``adata.h5ad`` under the working directory; every tool loads it, mutates it, and saves it
back. Plots are written alongside it.

State is scoped per chat thread: ``work/<thread_id>/`` and ``reports/<thread_id>/`` are
isolated from other threads, so two concurrent chats analysing the same dataset do not
collide. When no LangGraph runtime is present (CLI before the first invoke, smoke test)
the thread id falls back to ``"default"``.

The LangGraph server runs tool calls concurrently (``asyncio.gather``, each sync tool on its
own thread), so all access to the single h5ad file is serialized with a process-wide lock and
writes are atomic (temp file + ``os.replace``). Without this, two overlapping tool calls hit
HDF5's "unable to truncate a file which is already open" error.
"""

from __future__ import annotations

import os
import re
import threading
import uuid
from pathlib import Path

import anndata as ad

# Serializes access to the working dataset within this process. It is reentrant so a tool can
# hold it across its whole load->compute->save while load_adata/save_adata reacquire it. Tools
# should hold this for their entire operation so no tool ever reads half-updated state.
STATE_LOCK = threading.RLock()

# Project root = two levels up from this file (src/sc_agent/session.py -> project root).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

_THREAD_ID_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize_thread_id(raw: str) -> str:
    """Make a thread id safe to use as a directory name.

    Thread ids reaching us are typically uuid hex (already safe), but external clients can
    set any string. Strip path separators and other shell-hostile characters, cap length.
    """
    cleaned = _THREAD_ID_SAFE.sub("_", raw).strip("._") or "default"
    return cleaned[:64]


def current_thread_id() -> str:
    """Return the current chat thread's id, or ``"default"`` outside a LangGraph run.

    The thread id is read from ``langgraph.config.get_config()["configurable"]["thread_id"]``.
    Falls back to ``"default"`` when:
      * not running inside a LangGraph invocation (e.g. ``scripts/smoke_test.py`` calls tools
        directly), or
      * the runtime config doesn't carry a thread id.
    """
    try:
        from langgraph.config import get_config
    except ImportError:
        return "default"
    try:
        cfg = get_config()
    except RuntimeError:
        return "default"
    tid = (cfg or {}).get("configurable", {}).get("thread_id")
    if not tid:
        return "default"
    return _sanitize_thread_id(str(tid))


def work_base_dir() -> Path:
    """Return (and create) the *base* directory that holds all per-thread work dirs."""
    configured = os.getenv("SC_AGENT_WORK_DIR", "work")
    path = Path(configured)
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def reports_base_dir() -> Path:
    """Return (and create) the *base* directory that holds all per-thread reports dirs.

    Used as ``root_dir`` for the agent's :class:`FilesystemBackend`; the per-call ``cwd`` is
    one level deeper (the current thread's subdir).
    """
    path = _PROJECT_ROOT / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def work_dir() -> Path:
    """Return (and create) the per-thread working directory for adata + plots."""
    path = work_base_dir() / current_thread_id()
    path.mkdir(parents=True, exist_ok=True)
    return path


def reports_dir() -> Path:
    """Return (and create) the per-thread directory the agent writes its reports into."""
    path = reports_base_dir() / current_thread_id()
    path.mkdir(parents=True, exist_ok=True)
    return path


def adata_path() -> Path:
    """Path to the persisted AnnData file for the current thread."""
    return work_dir() / "adata.h5ad"


def adata_exists() -> bool:
    return adata_path().exists()


def load_adata() -> ad.AnnData:
    """Load the working AnnData (fully into memory), or raise if nothing is loaded yet."""
    with STATE_LOCK:
        if not adata_exists():
            raise FileNotFoundError(
                "No dataset is loaded yet. Call load_data(...) first "
                "(e.g. source='pbmc3k')."
            )
        return ad.read_h5ad(adata_path())


def save_adata(adata: ad.AnnData) -> None:
    """Persist the working AnnData atomically (write temp file, then replace).

    Writing to a fresh temp file and ``os.replace``-ing it avoids truncating a file that may
    still be open by a concurrent reader, and the replace is atomic on Windows and POSIX.
    """
    with STATE_LOCK:
        target = adata_path()
        tmp = target.parent / f"adata.{uuid.uuid4().hex}.tmp.h5ad"
        try:
            adata.write_h5ad(tmp)
            os.replace(tmp, target)
        finally:
            if tmp.exists():
                tmp.unlink()


def plot_path(name: str) -> Path:
    """Resolve a path for a generated plot inside the current thread's working directory."""
    return work_dir() / name
