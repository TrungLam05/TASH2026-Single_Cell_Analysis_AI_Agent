"""Curated scanpy tools.

Each function is a single, validated step of the standard scRNA-seq pipeline. The LLM agent
chooses *which* step to run and with *what* parameters; it never writes scanpy code itself.
Every tool operates on the disk-backed working AnnData (see :mod:`sc_agent.session`) and
returns a concise text summary so the agent's context stays small.

These tools share one mutable on-disk dataset, so they must run sequentially and in a valid
order. The LangGraph server may execute tool calls concurrently, so each tool:
  * holds STATE_LOCK across its whole load->compute->save (never reads half-updated state), and
  * validates its prerequisites and returns a friendly error string (rather than raising, which
    the default error handler would turn into a crashed run) if called out of order.
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # headless backend (no GUI in the server/CLI)

import numpy as np
import scanpy as sc
import scipy.sparse as sp

from sc_agent.session import (
    STATE_LOCK,
    adata_exists,
    adata_path,
    load_adata,
    plot_path,
    save_adata,
)

sc.settings.verbosity = 1

_NOT_LOADED = "No dataset is loaded. Run load_data(...) first (e.g. source='pbmc3k')."


def load_data(source: str = "pbmc3k") -> str:
    """Load a single-cell dataset into the working session.

    Args:
        source: One of:
            - "pbmc3k": scanpy's built-in 3k PBMC dataset (downloads on first use).
            - a path to a 10x Genomics matrix directory (contains matrix.mtx etc.).
            - a path to an .h5ad file.

    Returns a summary of the loaded matrix (cells x genes). This resets the session.
    """
    with STATE_LOCK:
        src = source.strip()
        if src.lower() == "pbmc3k":
            adata = sc.datasets.pbmc3k()
        elif src.lower().endswith(".h5ad"):
            adata = sc.read_h5ad(src)
        else:
            adata = sc.read_10x_mtx(src, var_names="gene_symbols", cache=True)

        adata.var_names_make_unique()
        save_adata(adata)
        return (
            f"Loaded '{source}': {adata.n_obs} cells x {adata.n_vars} genes. "
            f"Working file: {adata_path()}"
        )


def run_qc(min_genes: int = 200, min_cells: int = 3, max_pct_mt: float = 5.0) -> str:
    """Compute QC metrics and filter low-quality cells and genes.

    Flags mitochondrial genes (names starting with 'MT-'/'mt-'), then removes cells with
    fewer than `min_genes` detected genes, genes seen in fewer than `min_cells` cells, and
    cells whose mitochondrial fraction exceeds `max_pct_mt` percent. Run on raw counts,
    before normalize_log.

    Returns before/after cell and gene counts.
    """
    with STATE_LOCK:
        if not adata_exists():
            return _NOT_LOADED
        adata = load_adata()
        if "log1p" in adata.uns:
            return (
                "Data is already normalized; QC filtering expects raw counts. Re-load the "
                "dataset with load_data if you need to redo QC."
            )
        n0, g0 = adata.n_obs, adata.n_vars

        adata.var["mt"] = adata.var_names.str.upper().str.startswith("MT-")
        sc.pp.calculate_qc_metrics(
            adata, qc_vars=["mt"], percent_top=None, log1p=False, inplace=True
        )
        sc.pp.filter_cells(adata, min_genes=min_genes)
        sc.pp.filter_genes(adata, min_cells=min_cells)
        adata = adata[adata.obs["pct_counts_mt"] < max_pct_mt].copy()

        save_adata(adata)
        return (
            f"QC done. Cells: {n0} -> {adata.n_obs}, genes: {g0} -> {adata.n_vars} "
            f"(min_genes={min_genes}, min_cells={min_cells}, max_pct_mt={max_pct_mt})."
        )


def normalize_log(target_sum: float = 1e4) -> str:
    """Normalize counts per cell to `target_sum` and apply log1p transform.

    Run on raw counts (after run_qc). Stores the normalized log values in `adata.raw` for
    later reference (e.g. plotting gene expression after HVG subsetting).
    """
    with STATE_LOCK:
        if not adata_exists():
            return _NOT_LOADED
        adata = load_adata()
        if "log1p" in adata.uns:
            return "Data is already normalized and log-transformed; skipping to avoid double transform."
        sc.pp.normalize_total(adata, target_sum=target_sum)
        sc.pp.log1p(adata)
        adata.raw = adata
        save_adata(adata)
        return f"Normalized to {target_sum:g} counts/cell and log1p-transformed. Saved raw snapshot."


def select_hvg(n_top_genes: int = 2000) -> str:
    """Identify highly variable genes (HVGs) and subset to them.

    Run after normalize_log. Returns the number of HVGs kept. The full gene set remains
    accessible via `adata.raw`.
    """
    with STATE_LOCK:
        if not adata_exists():
            return _NOT_LOADED
        adata = load_adata()
        if "log1p" not in adata.uns:
            return "Data is not normalized yet. Run normalize_log before select_hvg."
        x = adata.X.data if sp.issparse(adata.X) else adata.X
        if not np.all(np.isfinite(x)):
            return (
                "Data contains non-finite values; cannot select HVGs. Reload the dataset and "
                "run run_qc then normalize_log on raw counts before select_hvg."
            )

        sc.pp.highly_variable_genes(adata, n_top_genes=n_top_genes, flavor="seurat")
        n_hvg = int(adata.var["highly_variable"].sum())
        adata = adata[:, adata.var["highly_variable"]].copy()
        save_adata(adata)
        return f"Selected {n_hvg} highly variable genes (target n_top_genes={n_top_genes})."


def scale_pca(n_comps: int = 50, max_value: float = 10.0) -> str:
    """Scale each gene to unit variance (clipped at `max_value`) and run PCA.

    Run after normalize_log (typically after select_hvg). Returns the total variance
    explained by the components.
    """
    with STATE_LOCK:
        if not adata_exists():
            return _NOT_LOADED
        adata = load_adata()
        if "log1p" not in adata.uns:
            return "Data is not normalized yet. Run normalize_log (and usually select_hvg) before scale_pca."
        n_comps = min(n_comps, adata.n_vars - 1, adata.n_obs - 1)
        sc.pp.scale(adata, max_value=max_value)
        sc.tl.pca(adata, n_comps=n_comps)
        var_ratio = float(adata.uns["pca"]["variance_ratio"].sum())
        save_adata(adata)
        return (
            f"Scaled (max_value={max_value}) and computed {n_comps} PCs "
            f"explaining {var_ratio:.1%} of variance."
        )


def cluster(resolution: float = 1.0, n_neighbors: int = 15) -> str:
    """Build the neighbor graph, compute UMAP, and cluster cells with Leiden.

    Run after scale_pca. Higher `resolution` yields more clusters. Returns the number of
    clusters found and per-cluster cell counts.
    """
    with STATE_LOCK:
        if not adata_exists():
            return _NOT_LOADED
        adata = load_adata()
        if "X_pca" not in adata.obsm:
            return "No PCA found. Run scale_pca before cluster."
        sc.pp.neighbors(adata, n_neighbors=n_neighbors)
        sc.tl.umap(adata)
        sc.tl.leiden(
            adata, resolution=resolution, flavor="igraph", n_iterations=2, directed=False
        )

        counts = adata.obs["leiden"].value_counts().sort_index()
        breakdown = ", ".join(f"{c}:{n}" for c, n in counts.items())
        save_adata(adata)
        return (
            f"Clustered into {counts.size} Leiden clusters (resolution={resolution}). "
            f"Cells per cluster -> {breakdown}."
        )


def find_markers(method: str = "wilcoxon", n_genes: int = 10) -> str:
    """Rank marker genes for each Leiden cluster.

    Run after cluster. `method` is one of 'wilcoxon', 't-test', or 'logreg'. Returns the
    top `n_genes` marker genes per cluster.
    """
    with STATE_LOCK:
        if not adata_exists():
            return _NOT_LOADED
        adata = load_adata()
        if "leiden" not in adata.obs:
            return "No clusters found. Run cluster before find_markers."

        sc.tl.rank_genes_groups(adata, groupby="leiden", method=method)
        save_adata(adata)

        names = adata.uns["rank_genes_groups"]["names"]
        lines = [f"Top {n_genes} markers per cluster (method={method}):"]
        for group in names.dtype.names:
            top = [names[group][i] for i in range(min(n_genes, len(names[group])))]
            lines.append(f"  cluster {group}: {', '.join(top)}")
        return "\n".join(lines)


def plot_umap(color: str = "leiden") -> str:
    """Save a UMAP scatter plot colored by `color`.

    `color` can be 'leiden' (clusters) or a gene name. Run after cluster. Returns the path
    to the saved PNG.
    """
    with STATE_LOCK:
        if not adata_exists():
            return _NOT_LOADED
        adata = load_adata()
        if "X_umap" not in adata.obsm:
            return "No UMAP embedding found. Run cluster before plot_umap."

        fig = sc.pl.umap(adata, color=color, show=False, return_fig=True)
        out = plot_path(f"umap_{color}.png")
        fig.savefig(out, dpi=150, bbox_inches="tight")
        return f"Saved UMAP colored by '{color}' to {out}."


def get_status() -> str:
    """Report what has been computed so far, to decide the next step.

    Lists the current matrix shape and which analysis results are present (QC metrics,
    normalization, HVGs, PCA, neighbors, UMAP, clusters, markers).
    """
    with STATE_LOCK:
        if not adata_exists():
            return _NOT_LOADED
        adata = load_adata()
        done = {
            "QC metrics": "pct_counts_mt" in adata.obs,
            "normalized+log1p": "log1p" in adata.uns,
            "HVGs selected": "highly_variable" in adata.var,
            "PCA": "X_pca" in adata.obsm,
            "neighbors": "neighbors" in adata.uns,
            "UMAP": "X_umap" in adata.obsm,
            "clusters (leiden)": "leiden" in adata.obs,
            "markers": "rank_genes_groups" in adata.uns,
        }
        steps = "\n".join(f"  [{'x' if v else ' '}] {k}" for k, v in done.items())
        return f"Current data: {adata.n_obs} cells x {adata.n_vars} genes.\nCompleted steps:\n{steps}"


# Exported in pipeline order for the agent.
TOOLS = [
    load_data,
    run_qc,
    normalize_log,
    select_hvg,
    scale_pca,
    cluster,
    find_markers,
    plot_umap,
    get_status,
]
