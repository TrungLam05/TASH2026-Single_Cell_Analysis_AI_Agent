# sc-agent — Single-Cell Analysis AI Agent

An AI agent that runs the standard single-cell RNA-seq (scRNA-seq) pipeline by orchestrating a
fixed toolkit of **curated [scanpy](https://scanpy.readthedocs.io) tools**. The LLM (OpenAI GPT)
decides *which* step to run and with *what* parameters — it never writes arbitrary code. Built on
[LangChain Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview).

## How it works

- **Agent** (`src/sc_agent/agent.py`) — a Deep Agent created with `create_deep_agent(...)`,
  exposed as the assistant `sc_agent` via `langgraph.json`.
- **Curated tools** (`src/sc_agent/tools.py`) — one validated function per pipeline step:
  `load_data → run_qc → normalize_log → select_hvg → scale_pca → cluster → find_markers →
  plot_umap`, plus `get_status`.
- **State** — the working `AnnData` is persisted to `work/adata.h5ad`; every tool reads it,
  mutates it, and writes it back. Plots are saved as PNGs under `work/`.

## Setup

Requires Python ≥ 3.11.

```bash
# 1. Install (uv recommended; pip also works)
uv sync
#   or:  python -m venv .venv && .venv\Scripts\activate && pip install -e .

# 2. Configure credentials
copy .env.example .env       # then edit .env and set OPENAI_API_KEY
```

Set `OPENAI_MODEL` in `.env` to a model you have access to (default `openai:gpt-4o`).

## Run

### Option A — CLI (quickest smoke test)

```bash
python main.py
```

Then try:

> Load the built-in pbmc3k dataset, run standard QC, normalize, select HVGs, run PCA,
> cluster, and find marker genes, then plot the UMAP.

Expect the agent to call the tools in order; `work/adata.h5ad` is created/updated, a
`work/umap_leiden.png` appears, and a marker-genes table is summarized back.

### Option B — Web UI (deep-agents-ui)

1. Start the backend (LangGraph server) from this directory:

   ```bash
   langgraph dev
   ```

   It serves at `http://127.0.0.1:2024` (open `http://127.0.0.1:2024/docs` to verify).

2. In a separate folder, clone and run the UI:

   ```bash
   git clone https://github.com/langchain-ai/deep-agents-ui
   cd deep-agents-ui
   yarn install
   yarn dev            # http://localhost:3000
   ```

3. In the UI settings, set:
   - **Deployment URL**: `http://127.0.0.1:2024`
   - **Assistant ID**: `sc_agent`

   Then send the same prompt as above and watch the tool-call trace + results.

## Roadmap (not in v1)

Sub-agents per phase, Deep Agents skills, doublet detection, batch integration, cell-type
annotation, trajectory inference, richer plotting, and multi-session state.
