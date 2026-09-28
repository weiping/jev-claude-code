#!/usr/bin/env python3
"""PostToolUse(Agent): mark the subgoal done and keep a short excerpt of its result."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jevlib  # noqa: E402


def main() -> None:
    data = jevlib.read_input()
    resp = data.get("tool_response") or {}
    cwd = data.get("cwd", str(jevlib.PROJECT))
    # 必须跟 agent_router.py 用同一个 hint 解析出同一个 state 目录，否则这里找不到
    # 那次派发登记的 subgoal（dedupe 登记表就对不上了）。
    r = jevlib.resolve(cwd)
    registry = jevlib.state_read("subgoals.json", {}, base=r.state)
    key = data.get("tool_use_id")
    if key in registry:
        text = " ".join(b.get("text", "") for b in resp.get("content", []) if isinstance(b, dict))
        registry[key]["status"] = "done" if resp.get("status") == "completed" else "running"
        registry[key]["result"] = text[:600]
        registry[key]["model"] = resp.get("resolvedModel")
        jevlib.state_write("subgoals.json", registry, base=r.state)
    jevlib.emit(None)


if __name__ == "__main__":
    jevlib.guard("agent_done", main)
