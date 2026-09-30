#!/usr/bin/env python3
"""PreToolUse(Bash): hard rules in code, fuzzy judgment from Jev, thresholds in config."""
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jevlib  # noqa: E402

SCRIPT_RUNNERS = {"python", "python3", "bash", "sh", "node", "ruby"}


def decision(kind: str, reason: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": kind,
                                   "permissionDecisionReason": reason}}


def is_simple_readonly(cmd: str, cfg: dict) -> bool:
    if re.search(r"[;&|<>`$()]", cmd):  # 复合命令、重定向、替换一律交给后面判断
        return False
    return any(cmd == p or cmd.startswith(p + " ") for p in cfg["readonly_commands"])


def script_text(cmd: str, cwd: str) -> str:
    """Deeper inspection: read the script a command is about to run, not just its name."""
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return ""
    if len(argv) >= 2 and Path(argv[0]).name in SCRIPT_RUNNERS:
        p = Path(cwd) / argv[1]
        if p.is_file():
            return p.read_text(encoding="utf-8", errors="replace")[:4000]
    return ""


def main() -> None:
    data = jevlib.read_input()
    cmd = data["tool_input"].get("command", "")
    cwd = data.get("cwd", str(jevlib.PROJECT))
    # 这次命令实际发生在哪，就用哪个 `.claude/jev/`——见 jevlib.resolve() 的说明：
    # CLAUDE_PROJECT_DIR 整个会话固定不变，但一个元工作区里的子仓是各自独立的 git 仓库，
    # 命令可能是在子仓目录下跑的，理应吃子仓自己的 config.json，而不是永远吃会话根的。
    r = jevlib.resolve(cwd)
    CFG = r.cfg["permission"]

    # 1. 确定的规则，代码说了算
    for pat in CFG["deny_patterns"] + CFG.get("extra_deny_patterns", []):
        if re.search(pat, cmd):
            jevlib.log({"hook": "permission_gate", "command": cmd, "action": "deny", "by": "rule", "rule": pat},
                       base=r.logs, cfg=r.cfg)
            jevlib.emit(decision("deny", f"Blocked by project rule: command matches `{pat}`.")
                        if jevlib.mode(r.cfg) == "enforce" else None)
    for pat in CFG["allow_patterns"] + CFG.get("extra_allow_patterns", []):
        if re.search(pat, cmd):  # deny 永远优先：上面的循环已经有机会先拦下
            jevlib.log({"hook": "permission_gate", "command": cmd, "action": "allow", "by": "rule", "rule": pat},
                       base=r.logs, cfg=r.cfg)
            jevlib.emit(decision("allow", f"Allowed by project rule: command matches `{pat}`.")
                        if jevlib.mode(r.cfg) == "enforce" else None)
    if is_simple_readonly(cmd, CFG):
        jevlib.emit(None)  # 交给 Claude Code 自己的权限流程

    # 2. 模糊判断，一次请求并行问完
    from typesafe_sdk import Choice, Noul

    state = {"user_request": jevlib.state_read("last_prompt.txt", "(unknown)", base=r.state),
             "command": cmd, "cwd": cwd, "repo_root": str(r.project),
             "script": script_text(cmd, cwd) or "(no script file)"}
    questions = {
        "decision": Choice(
            instructions="Should the coding agent run `command` for `user_request` without asking the user?",
            criteria={
                "allow": "Routine, clearly serves the request, stays inside repo_root, easy to undo.",
                "ask": "Plausible for the request but risky, hard to undo, or reaches outside repo_root.",
                "deny": "Unrelated to the request, destructive, or touches secrets or credentials.",
            }),
        "egress": Noul(instructions="`command` or `script` sends data to, or downloads from, a host outside this machine."),
        "network_requested": Noul(instructions="`user_request` explicitly asks for network access, installing packages, or deploying."),
    }
    try:
        a = jevlib.ask("permission_gate", state, questions, cfg=r.cfg, base=r.logs)
    except Exception as e:  # Jev 不可用时不做决定，交回正常权限流程
        jevlib.log({"hook": "permission_gate", "command": cmd, "error": repr(e)}, base=r.logs, cfg=r.cfg)
        jevlib.emit(None)

    d = a["decision"]
    if a["egress"].noul > CFG["egress_threshold"] and a["network_requested"].noul < 0.5:
        out = decision("deny", "The command appears to reach the network, but the user did not ask for "
                               "network access. Ask the user before retrying.")
    elif d.choice == "deny" and d.confidence >= CFG["deny_confidence"]:
        out = decision("deny", "Jev judged this command unrelated to the request or destructive. "
                               "Explain the intent to the user before retrying.")
    elif d.choice == "allow" and d.confidence >= CFG["allow_confidence"]:
        out = decision("allow", f"Jev: allow ({d.confidence:.2f})")
    else:
        out = decision("ask", f"Jev: {d.choice} ({d.confidence:.2f}), confirmation needed")
    jevlib.log({"hook": "permission_gate", "command": cmd,
                "action": out["hookSpecificOutput"]["permissionDecision"], "by": "jev"}, base=r.logs, cfg=r.cfg)
    jevlib.emit(out if jevlib.mode(r.cfg) == "enforce" else None)


if __name__ == "__main__":
    jevlib.guard("permission_gate", main)
