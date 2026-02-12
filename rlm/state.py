"""Session persistence across Bash invocations.

Stores session state in /tmp/rlm-sessions/{session_id}/ so that
each Bash invocation (a new process) can pick up where the last left off.
"""

import json
import os
import textwrap
import time
import uuid
from pathlib import Path

SESSIONS_DIR = "/tmp/rlm-sessions"


def init_session(query: str, target_path: str) -> dict:
    """Create a new RLM session.

    Returns dict with session_id and session_dir.
    """
    session_id = uuid.uuid4().hex[:12]
    session_dir = os.path.join(SESSIONS_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)

    state = {
        "session_id": session_id,
        "query": query,
        "target_path": str(Path(target_path).resolve()),
        "created_at": time.time(),
        "iterations": [],
        "results": {},
        "status": "active",
        "final_answer": None,
    }

    _save_state(session_dir, state)

    return {
        "session_id": session_id,
        "session_dir": session_dir,
    }


def get_state(session_id: str) -> dict:
    """Load session state."""
    session_dir = os.path.join(SESSIONS_DIR, session_id)
    return _load_state(session_dir)


def update_iteration(
    session_id: str, iteration: int, action: str, summary: str
) -> dict:
    """Record an iteration in the session log."""
    session_dir = os.path.join(SESSIONS_DIR, session_id)
    state = _load_state(session_dir)

    if isinstance(state.get("error"), str):
        return state

    state["iterations"].append({
        "iteration": iteration,
        "action": action,
        "summary": summary,
        "timestamp": time.time(),
    })

    _save_state(session_dir, state)
    return state


def add_result(session_id: str, key: str, value: str) -> dict:
    """Store a subagent finding or intermediate result."""
    session_dir = os.path.join(SESSIONS_DIR, session_id)
    state = _load_state(session_dir)

    if isinstance(state.get("error"), str):
        return state

    state["results"][key] = {
        "value": value,
        "added_at": time.time(),
    }

    _save_state(session_dir, state)
    return {"status": "ok", "key": key}


def get_results(session_id: str) -> dict:
    """Retrieve all accumulated results."""
    session_dir = os.path.join(SESSIONS_DIR, session_id)
    state = _load_state(session_dir)

    if isinstance(state.get("error"), str):
        return state

    return state.get("results", {})


def set_final(session_id: str, answer: str) -> dict:
    """Mark session as complete with final answer."""
    session_dir = os.path.join(SESSIONS_DIR, session_id)
    state = _load_state(session_dir)

    if isinstance(state.get("error"), str):
        return state

    state["status"] = "complete"
    state["final_answer"] = answer
    state["completed_at"] = time.time()

    _save_state(session_dir, state)
    return {"status": "complete", "session_id": session_id}


def format_results_summary(session_id: str, max_chars: int = 3000) -> str:
    """Produce a bounded summary of all session results."""
    session_dir = os.path.join(SESSIONS_DIR, session_id)
    state = _load_state(session_dir)

    if isinstance(state.get("error"), str):
        return f"Error: {state['error']}"

    lines = []
    lines.append(f"Session: {session_id}")
    lines.append(f"Query: {state['query']}")
    lines.append(f"Target: {state['target_path']}")
    lines.append(f"Status: {state['status']}")
    lines.append(f"Iterations: {len(state['iterations'])}")
    lines.append("")

    # Iteration log
    if state["iterations"]:
        lines.append("Iteration Log:")
        for it in state["iterations"]:
            lines.append(f"  [{it['iteration']}] {it['action']}: {it['summary'][:100]}")
        lines.append("")

    # Results
    results = state.get("results", {})
    if results:
        lines.append(f"Results ({len(results)} entries):")
        for key, entry in results.items():
            val_preview = entry["value"][:200]
            if len(entry["value"]) > 200:
                val_preview += "..."
            lines.append(f"  {key}:")
            lines.append(textwrap.indent(val_preview, "    "))
            lines.append("")

            # Check budget
            current = "\n".join(lines)
            if len(current) > max_chars - 200:
                remaining = len(results) - list(results.keys()).index(key) - 1
                if remaining > 0:
                    lines.append(f"  ... and {remaining} more results")
                break

    # Final answer
    if state.get("final_answer"):
        lines.append("Final Answer:")
        lines.append(textwrap.indent(state["final_answer"][:500], "  "))

    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[:max_chars - 50] + "\n... [truncated to fit output limit]"
    return result


def format_status(session_id: str) -> str:
    """Format a concise status display for the session."""
    state = get_state(session_id)

    if isinstance(state.get("error"), str):
        return f"Error: {state['error']}"

    lines = [
        f"Session: {session_id}",
        f"Query: {state['query']}",
        f"Target: {state['target_path']}",
        f"Status: {state['status']}",
        f"Iterations: {len(state['iterations'])}",
        f"Results: {len(state.get('results', {}))} entries",
    ]

    if state["iterations"]:
        last = state["iterations"][-1]
        lines.append(f"Last action: [{last['iteration']}] {last['action']}")

    return "\n".join(lines)


# --- Internal helpers ---

def _save_state(session_dir: str, state: dict):
    """Save state to disk."""
    state_path = os.path.join(session_dir, "state.json")
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def _load_state(session_dir: str) -> dict:
    """Load state from disk."""
    state_path = os.path.join(session_dir, "state.json")
    if not os.path.isfile(state_path):
        return {"error": f"Session not found: {session_dir}"}
    try:
        with open(state_path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {"error": f"Failed to load state: {e}"}
