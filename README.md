# sc-agent — Single-Cell Analysis AI Agent

An AI **research partner** for single-cell RNA-seq analysis. An OpenAI GPT agent orchestrates
a fixed toolkit of **curated [scanpy](https://scanpy.readthedocs.io) tools** — it decides which
step to run and with what parameters, exercises scientific judgment on QC thresholds and
clustering, interprets marker genes into likely cell types, and produces a written report.
It never writes arbitrary code; only the curated tools touch the data. Built on
[LangChain Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview).

## How it works

- **Agent** (`src/sc_agent/agent.py`) — a Deep Agent created with `create_deep_agent(...)` and
  exposed as the assistant `sc_agent` via `langgraph.json`.
- **Curated scanpy tools** (`src/sc_agent/tools.py`) — one validated function per pipeline step:
  `load_data → run_qc → normalize_log → select_hvg → scale_pca → cluster → find_markers →
  plot_umap`, plus `get_status`. Each holds a state lock across its whole load→compute→save and
  returns a graceful error string if a prerequisite is missing, so out-of-order calls
  self-correct instead of crashing the run.
- **Deep Agents built-ins** — the agent also gets `write_todos` (planning), a filesystem
  (`ls`/`read_file`/`write_file`/`edit_file`/`glob`/`grep`), and `task` (sub-agents) for free.
- **Two storage areas, two purposes:**
  - `work/` — the working dataset (`adata.h5ad`) and generated figures (PNGs). The scanpy
    tools manage this. Disposable; rebuilt every run.
  - `reports/` — backed by a real-disk `FilesystemBackend`, this is where the agent writes its
    Markdown analysis reports (the deliverable you open). `virtual_mode=True` confines the
    agent to this directory.

## Project layout

```
TASH2026/
  src/sc_agent/
    agent.py           # builds the agent (entrypoint for langgraph.json)
    tools.py           # 9 curated scanpy tools (atomic, validated)
    prompts.py         # system prompt: identity, judgment, deliverables
    session.py         # disk-backed AnnData state + STATE_LOCK + reports_dir
  main.py              # CLI REPL for quick local testing
  scripts/smoke_test.py# offline pipeline check (no LLM/API key needed)
  langgraph.json       # exposes the `sc_agent` graph to langgraph dev + the UI
  pyproject.toml       # dependencies (deepagents, scanpy, langgraph-cli, ...)
  .env.example         # OPENAI_API_KEY + OPENAI_MODEL
  work/                # adata.h5ad and figures (gitignored, auto-created)
  reports/             # agent-written reports (gitignored, auto-created)
```

## Setup

Requires Python ≥ 3.11.

```powershell
# 1. Install (uv recommended; pip also works)
uv sync
#   or: python -m venv .venv ; .\.venv\Scripts\Activate.ps1 ; pip install -e .

# 2. Configure credentials
copy .env.example .env       # then edit .env and set OPENAI_API_KEY
```

Set `OPENAI_MODEL` in `.env` to a model you have access to (default `openai:gpt-5.2`).

## Run

### Option A — CLI (quickest)

```powershell
.\.venv\Scripts\python.exe main.py
```

Try:

> Take pbmc3k through to annotated cell types and write me a report.

The agent will plan with todos, run the pipeline (adapting parameters to the data), interpret
the markers into cell types, save figures under `work/`, and **write a full technical report to
`reports/<name>.md`**. Its chat reply is a concise summary that points at the report file.

### Option B — Web UI (deep-agents-ui)

1. Start the backend from this directory:

   ```powershell
   .\.venv\Scripts\langgraph.exe dev
   ```

   Serves at `http://127.0.0.1:2024` (open `/docs` to verify).

2. Clone and run the UI in a separate folder:

   ```powershell
   git clone https://github.com/langchain-ai/deep-agents-ui
   cd deep-agents-ui
   npm install            # or: corepack enable; yarn install   (corepack may need admin)
   npm run dev            # http://localhost:3000
   ```

3. In the UI settings, set:
   - **Deployment URL**: `http://127.0.0.1:2024`
   - **Assistant ID**: `sc_agent`

   Then send the same prompt and watch the tool-call trace + final report.

## Verify (offline)

Run the curated pipeline end-to-end on pbmc3k *without* any LLM or API key — useful after
dependency changes:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_test.py
```

You should see all 9 steps succeed and a `work\umap_leiden.png` appear.

## Roadmap (not in v1)

Sub-agents per analysis phase, Deep Agents skills/SKILL.md, doublet detection, batch
integration, automated cell-type annotation against references, trajectory inference, richer
plotting, and multi-session/thread state.
