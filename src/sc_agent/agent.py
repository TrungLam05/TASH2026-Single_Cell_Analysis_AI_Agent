"""Builds the Deep Agent. `agent` is the entrypoint referenced by langgraph.json."""

from __future__ import annotations

import os
from pathlib import Path

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from dotenv import load_dotenv

from sc_agent.prompts import SYSTEM_PROMPT
from sc_agent.session import current_thread_id, reports_base_dir
from sc_agent.tools import TOOLS


def _patch_deepagents_messages_reducer_for_none_state() -> None:
    """Work around a NoneType crash in `deepagents._messages_reducer` (v0.6.3).

    The vendored reducer calls ``convert_to_messages(state)`` when ``state`` is falsy, which
    crashes with ``TypeError: 'NoneType' object is not iterable`` when ``state is None``
    (hit by the langgraph dev server's ``/threads/.../history`` endpoint during checkpoint
    replay for threads with no messages yet). Coerce ``None`` to ``[]`` before the upstream
    call so the reducer behaves like the empty-list case.

    The reducer is captured by reference in a ``DeltaChannel`` instance inside
    ``deepagents.graph._DeepAgentState.__annotations__["messages"]`` at import time, so
    rebinding the module attribute alone is not enough — we also have to mutate the
    channel instance's ``.reducer`` attribute.
    """
    from typing import get_args, get_type_hints

    from deepagents import _messages_reducer as reducer_mod
    from deepagents import graph as graph_mod
    from langgraph.channels.delta import DeltaChannel

    original = reducer_mod._messages_delta_reducer

    def safe_reducer(state, writes):  # type: ignore[no-untyped-def]
        return original(state if state is not None else [], writes)

    # Rebind the module attribute so any *future* import sees the safe wrapper.
    reducer_mod._messages_delta_reducer = safe_reducer

    # Patch the already-constructed DeltaChannel instance on _DeepAgentState. The
    # ``messages`` annotation is nested (``Required[Annotated[list[...], DeltaChannel(...)]]``
    # plus more Annotated wrappers inside list[...]), so walk the type tree recursively and
    # mutate every DeltaChannel we find.
    def _patch_channels(node: object, seen: set[int]) -> None:
        if id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, DeltaChannel):
            node.reducer = safe_reducer
            return
        for child in get_args(node):
            _patch_channels(child, seen)

    try:
        hints = get_type_hints(graph_mod._DeepAgentState, include_extras=True)
        _patch_channels(hints.get("messages"), set())
    except Exception:  # noqa: BLE001 — patch is best-effort; original error stays better than masking
        pass


_patch_deepagents_messages_reducer_for_none_state()

load_dotenv()

MODEL = os.getenv("OPENAI_MODEL", "openai:gpt-5.2")


class _ThreadScopedFilesystemBackend(FilesystemBackend):
    """A :class:`FilesystemBackend` whose ``cwd`` resolves to the current thread's reports dir.

    ``FilesystemBackend.__init__`` captures ``cwd`` once at construction. We override it as a
    data descriptor (property) so every operation re-resolves to ``<base>/<thread_id>/``,
    making the agent's filesystem tools (write_file/read_file/edit_file/ls/glob/grep) operate
    on a per-chat-thread sandbox even though the backend is constructed once at import.

    ``virtual_mode=True`` keeps path traversal blocked, so the agent cannot escape its own
    thread directory into a sibling's.
    """

    @property
    def cwd(self) -> Path:
        d = self._base_dir / current_thread_id()
        d.mkdir(parents=True, exist_ok=True)
        return d

    @cwd.setter
    def cwd(self, value: Path) -> None:
        # Called once by FilesystemBackend.__init__(root_dir=...). Capture the base; per-call
        # reads of self.cwd resolve to <base>/<thread_id>.
        self._base_dir = Path(value).resolve()
        self._base_dir.mkdir(parents=True, exist_ok=True)


agent = create_deep_agent(
    model=MODEL,
    tools=TOOLS,
    system_prompt=SYSTEM_PROMPT,
    backend=_ThreadScopedFilesystemBackend(
        root_dir=str(reports_base_dir()), virtual_mode=True
    ),
)
