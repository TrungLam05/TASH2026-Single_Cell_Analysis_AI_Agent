"""Offline smoke test: exercise the curated scanpy tools directly (no LLM / API key).

Runs the full standard pipeline on the built-in pbmc3k dataset and prints each tool's
summary. Verifies that the tools and disk-backed session state work end-to-end.

Since this bypasses the LangGraph runtime, ``current_thread_id()`` returns ``"default"``
and output lands under ``work/default/`` (adata + figures).

    python scripts/smoke_test.py
"""

from __future__ import annotations

from sc_agent import tools


def main() -> None:
    steps = [
        ("load_data", lambda: tools.load_data("pbmc3k")),
        ("run_qc", lambda: tools.run_qc()),
        ("normalize_log", lambda: tools.normalize_log()),
        ("select_hvg", lambda: tools.select_hvg()),
        ("scale_pca", lambda: tools.scale_pca()),
        ("cluster", lambda: tools.cluster()),
        ("find_markers", lambda: tools.find_markers()),
        ("plot_umap", lambda: tools.plot_umap("leiden")),
        ("get_status", lambda: tools.get_status()),
    ]
    for name, fn in steps:
        print(f"\n=== {name} ===")
        print(fn())
    print("\nSmoke test complete.")


if __name__ == "__main__":
    main()
