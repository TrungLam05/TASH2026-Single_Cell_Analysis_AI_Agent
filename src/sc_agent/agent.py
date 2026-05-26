"""Builds the Deep Agent. `agent` is the entrypoint referenced by langgraph.json."""

from __future__ import annotations

import os

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from dotenv import load_dotenv

from sc_agent.prompts import SYSTEM_PROMPT
from sc_agent.session import reports_dir
from sc_agent.tools import TOOLS

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "openai:gpt-5.2")

# Back the agent's filesystem tools (write_file/read_file/ls/edit_file) with real disk, anchored
# to ./reports, so the technical reports it writes persist as files the researcher can open.
# virtual_mode=True confines the agent to root_dir and blocks path traversal.
agent = create_deep_agent(
    model=MODEL,
    tools=TOOLS,
    system_prompt=SYSTEM_PROMPT,
    backend=FilesystemBackend(root_dir=str(reports_dir()), virtual_mode=True),
)
