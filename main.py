"""Minimal CLI loop for testing the agent locally (before wiring up deep-agents-ui).

Usage:
    python main.py

Type a request (e.g. "Load pbmc3k and run the standard pipeline"), or 'exit' to quit.

A single ``thread_id`` is minted at startup and reused for every turn in this REPL, so
``work/<thread_id>/`` and ``reports/<thread_id>/`` accumulate the whole session's state.
Run main.py again to start a fresh thread.
"""

from __future__ import annotations

import uuid

from sc_agent.agent import MODEL, agent


def main() -> None:
    thread_id = uuid.uuid4().hex
    config = {"configurable": {"thread_id": thread_id}}
    print(f"Single-cell analysis agent (model: {MODEL}).")
    print(f"thread: {thread_id}  (work/{thread_id}/, reports/{thread_id}/)")
    print("Type 'exit' to quit.\n")
    messages = []
    while True:
        try:
            user = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if user.lower() in {"exit", "quit"}:
            break
        if not user:
            continue

        messages.append({"role": "user", "content": user})
        result = agent.invoke({"messages": messages}, config=config)
        messages = result["messages"]

        reply = messages[-1].content
        if isinstance(reply, list):  # some models return content blocks
            reply = "".join(part.get("text", "") for part in reply if isinstance(part, dict))
        print(f"\nagent> {reply}\n")


if __name__ == "__main__":
    main()
