#!/usr/bin/env python3
"""PostToolUse(Bash): query-aware visibility ladder over long command output.

Each chunk of stdout is shown in full, as a short excerpt, or hidden, depending on the
current user request. The full output is saved and can be recalled at any time.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jevlib  # noqa: E402

LADDER = {
    "full": "Directly relevant to `user_request`; the agent needs these exact lines.",
    "short": "Possibly useful; a two-line excerpt is enough.",
    "hide": "Not needed for `user_request`, e.g. progress bars, boilerplate, unrelated files.",
}
UP = {"hide": "short", "short": "full", "full": "full"}


def chunk(lines: list[str], cfg: dict) -> list[tuple[int, list[str]]]:
    size = max(cfg["chunk_lines"], -(-len(lines) // cfg["max_chunks"]))  # 块数不超过上限
    return [(i, lines[i:i + size]) for i in range(0, len(lines), size)]


def main() -> None:
    data = jevlib.read_input()
    resp = data.get("tool_response") or {}
    stdout = resp.get("stdout") or ""
    cwd = data.get("cwd", str(jevlib.PROJECT))
    # 跟同一次 Bash 调用的 permission_gate 用同一个 hint 解析——这样 state 里的
    # last_prompt.txt/outputs/ 落在同一个 `.claude/jev/` 下，recall 也指向那里。
    r = jevlib.resolve(cwd)
    CFG = r.cfg["ladder"]
    lines = stdout.splitlines()
    if len(lines) < CFG["min_lines"] or resp.get("isImage"):
        jevlib.emit(None)

    from typesafe_sdk import Choice, Noul

    chunks = chunk(lines, CFG)
    state = {"user_request": jevlib.state_read("last_prompt.txt", "(unknown)", base=r.state),
             "command": data["tool_input"].get("command", ""),
             "chunks": {f"c{n}": "\n".join(body)[:3000] for n, (_, body) in enumerate(chunks)}}
    questions = {f"c{n}": Choice(
        instructions=f"How much of chunk `c{n}` in `chunks` should the agent see to work on `user_request`?",
        criteria=LADDER) for n in range(len(chunks))}
    questions["has_error"] = Noul(instructions="Any chunk contains an error, failure, or stack trace.")
    try:
        a = jevlib.ask("output_ladder", state, questions, cfg=r.cfg, base=r.logs)
    except Exception as e:
        jevlib.log({"hook": "output_ladder", "error": repr(e)}, base=r.logs, cfg=r.cfg)
        jevlib.emit(None)
    if a["has_error"].noul >= 0.5:  # 有报错时整段原样保留
        jevlib.emit(None)

    key = data.get("tool_use_id", "last").replace("/", "_")
    saved = jevlib.state_write(f"outputs/{key}.txt", stdout, base=r.state)

    parts, hidden = [], []
    for n, (start, body) in enumerate(chunks):
        ans = a[f"c{n}"]
        level = ans.choice if ans.confidence >= CFG["low_confidence"] else UP[ans.choice]
        a_, b_ = start + 1, start + len(body)
        if level == "full":
            parts.append("\n".join(body))
        elif level == "short":
            parts.append(f"[jev] lines {a_}-{b_} excerpt:\n" + "\n".join(body[:2]) + "\n  ...")
        else:
            hidden.append(f"{a_}-{b_}")
    kept = sum(len(p) for p in parts)
    footer = (f"\n[jev] {len(lines)} lines total; hidden ranges: {', '.join(hidden) or 'none'}. "
              f"Full output: {jevlib.PYTHON} {jevlib.PLUGIN_ROOT}/scripts/recall.py {saved} [START END]")
    jevlib.log({"hook": "output_ladder", "lines": len(lines), "chars_before": len(stdout),
                "chars_after": kept, "hidden_ranges": hidden}, base=r.logs, cfg=r.cfg)
    if jevlib.mode(r.cfg) != "enforce":
        jevlib.emit(None)
    jevlib.emit({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        # 以原始结构为底只替换 stdout，其余字段原样保留，避免不符合输出 schema 被忽略
        "updatedToolOutput": {**resp, "stdout": "\n".join(parts) + footer}}})


if __name__ == "__main__":
    jevlib.guard("output_ladder", main)
