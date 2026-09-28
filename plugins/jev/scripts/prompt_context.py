#!/usr/bin/env python3
"""UserPromptSubmit: remember the request, load conditional instructions, suggest project tools.

Everything is decided in a single Jev request. The result is injected as additionalContext
and also pinned to state, so session_context.py can re-inject it after a compaction.

Meta-workspace support: besides the session's own project root (`jevlib.PROJECT`, fixed for
the whole session from `CLAUDE_PROJECT_DIR`), this hook also looks one level down for sibling
directories that carry their own `.claude/jev/` — a repo living inside a meta-workspace root
that is not itself part of that root's git tree (e.g. `.gitignore`d out, its own independent
git repository). Each such sibling is treated as its own Jev project: its own `git diff`
scope, its own rules.json/tools.json, `load` paths resolved relative to its own directory.
This is deliberately one level deep only, to stay fast and match the common "meta-repo with
sibling repos" shape; it does not recurse further. The session's own project root is always
project index 0, so a workspace with no such siblings behaves exactly as before (same
question ids, same tool "none" text) — this is what keeps existing tests unchanged.
"""
import fnmatch
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jevlib  # noqa: E402

CFG = jevlib.CFG["context"]


def touched_files(root: Path) -> list[str]:
    cmds = [["git", "diff", "--name-only", "HEAD"], ["git", "ls-files", "--others", "--exclude-standard"]]
    files = []
    for c in cmds:
        r = subprocess.run(c, cwd=root, capture_output=True, text=True)
        files += r.stdout.split()
    return files


def main() -> None:
    data = jevlib.read_input()
    prompt = data.get("prompt", "")
    jevlib.state_write("last_prompt.txt", prompt)  # 其他 hook 用它当"当前查询"

    projects = []  # [(root, rules, tools, touched_files)]
    for root in jevlib.jev_projects():
        pj = root / ".claude" / "jev"
        rules = jevlib.project_file("rules.json", [], project_jev=pj)
        tools = jevlib.project_file("tools.json", {}, project_jev=pj)
        if rules or tools:
            projects.append((root, rules, tools, touched_files(root)))
    if not projects:  # 还没运行 /jev:init，不花一次调用
        jevlib.emit(None)

    from typesafe_sdk import Choice, Noul

    loaded = []          # [(root, rule)] —— when_files 已经匹配上的
    ask_questions = {}
    ask_state = {"user_request": prompt}
    tool_criteria, tool_lookup, none_text = {}, {}, None  # "{i}:{tid}" -> (root, tid, tool)

    for i, (root, rules, tools, files) in enumerate(projects):
        tag = "" if i == 0 else f"s{i}_"  # 会话根不加前缀，跟改动前的问题 id 完全一致
        loaded += [(root, rule) for rule in rules if "when_files" in rule
                   and any(fnmatch.fnmatch(f, g) for f in files for g in rule["when_files"])]
        for rule in rules:
            if "when_jev" in rule:
                ask_questions[f"rule_{tag}{rule['id']}"] = Noul(instructions=rule["when_jev"])
        ask_state[f"changed_files{'' if i == 0 else f'_{i}'}"] = files[:200]
        for tid, tool in tools.items():
            if tid == "none":
                if none_text is None:
                    none_text = tool["what"]
                continue
            key = tid if i == 0 else f"s{i}:{tid}"
            tool_criteria[key] = tool["what"]
            tool_lookup[key] = (root, tid, tool)

    if tool_criteria:
        tool_criteria["none"] = none_text or "None of the project tools is relevant to this request."
        ask_questions["tool"] = Choice(instructions="Which project tool, if any, helps with `user_request`?",
                                       criteria=tool_criteria)

    picked = []
    if ask_questions:
        try:
            a = jevlib.ask("prompt_context", ask_state, ask_questions)
            for i, (root, rules, tools, files) in enumerate(projects):
                tag = "" if i == 0 else f"s{i}_"
                loaded += [(root, rule) for rule in rules if "when_jev" in rule
                           and a[f"rule_{tag}{rule['id']}"].noul >= CFG["rule_threshold"]]
            if "tool" in a:
                probs = a["tool"].probabilities
                picked = [k for k in sorted(probs, key=probs.get, reverse=True)[:CFG["tool_top_k"]]
                         if k in tool_criteria and k != "none" and probs[k] >= CFG["tool_min_prob"]]
        except Exception as e:  # noqa: BLE001
            jevlib.log({"hook": "prompt_context", "error": repr(e)})

    blocks = []
    for root, rule in loaded:
        p = root / rule["load"]
        if p.is_file():
            blocks.append(f"Project guidance from {rule['load']} applies to this request:\n"
                          + p.read_text(encoding="utf-8"))
    if picked:
        lines = [f"- {tid}: {tool['what']} Usage: {tool['how']}"
                for _root, tid, tool in (tool_lookup[k] for k in picked)]
        blocks.append("Project tools relevant to this request (read the help before use):\n" + "\n".join(lines))
    context = "\n\n".join(blocks)[:CFG["max_chars"]]
    jevlib.state_write("pinned_context.md", context)
    jevlib.log({"hook": "prompt_context", "rules": [rule["id"] for _, rule in loaded], "tools": picked,
                "chars": len(context)})
    if not context or jevlib.mode() != "enforce":
        jevlib.emit(None)
    jevlib.emit({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}})


if __name__ == "__main__":
    jevlib.guard("prompt_context", main)
