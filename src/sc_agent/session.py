"""Disk-backed session state.

Each curated tool runs as a separate call on the LangGraph server, so the working
``AnnData`` cannot live in process memory reliably. Instead it is persisted to a single
``adata.h5ad`` under the working directory; every tool loads it, mutates it, and saves it
back. Plots are written alongside it.

The LangGraph server runs tool calls concurrently (``asyncio.gather``, each sync tool on its
own thread), so all access to the single h5ad file is serialized with a process-wide lock and
writes are atomic (temp file + ``os.replace``). Without this, two overlapping tool calls hit
HDF5's "unable to truncate a file which is already open" error.
"""

from __future__ import annotations

import os
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


def work_dir() -> Path:
    """Return (and create) the working directory for adata + plots."""
    configured = os.getenv("SC_AGENT_WORK_DIR", "work")
    path = Path(configured)
    if not path.is_absolute():
        path = _PROJECT_ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def reports_dir() -> Path:
    """Return (and create) the directory the agent writes its reports/notes into.

    This is the real-disk root for the agent's built-in filesystem tools, so the technical
    reports it produces land here as files the researcher can open.
    """
    path = _PROJECT_ROOT / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def adata_path() -> Path:
    """Path to the persisted AnnData file."""
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
    """Resolve a path for a generated plot inside the working directory."""
    return work_dir() / name
