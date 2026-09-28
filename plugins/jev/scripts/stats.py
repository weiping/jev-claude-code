#!/usr/bin/env python3
"""Summarize .claude/jev/logs/decisions.jsonl for /jev-stats.

Meta-workspace support: besides the session's own project root, this also looks one level
down for sibling directories that carry their own `.claude/jev/` (see `jevlib.jev_projects()`
— hooks resolve to a sibling's own logs when a command or dispatch runs with `cwd` inside it,
so a single session-root summary would silently miss all of that activity). A workspace with
no such siblings prints exactly what it always did, with no extra header.
"""
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jevlib  # noqa: E402


def summarize(root: Path) -> bool:
    """Print one project's summary. Returns False (and prints nothing) if it has no log yet."""
    path = root / ".claude" / "jev" / "logs" / "decisions.jsonl"
    if not path.exists():
        return False
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    calls = [r for r in rows if "latency_ms" in r]
    by_hook = defaultdict(list)
    for r in calls:
        by_hook[r["hook"]].append(r)
    tokens = sum(r.get("input_tokens") or 0 for r in calls)
    print(f"Jev calls: {len(calls)}   input tokens: {tokens}   est. cost: ${tokens * 0.042 / 1e6:.4f}")
    print(f"models: {dict(Counter(r['model'] for r in calls))}")
    for hook, rs in sorted(by_hook.items()):
        lat = [r["latency_ms"] for r in rs]
        print(f"- {hook}: {len(rs)} calls, median {statistics.median(lat):.0f} ms, p90 {sorted(lat)[int(len(lat) * 0.9) - 1 if len(lat) > 1 else 0]} ms")
    acts = Counter((r["hook"], r.get("action")) for r in rows if r.get("action"))
    for (hook, act), n in sorted(acts.items()):
        print(f"  {hook} -> {act}: {n}")
    lad = [r for r in rows if r.get("hook") == "output_ladder" and "chars_before" in r]
    if lad:
        b, a = sum(r["chars_before"] for r in lad), sum(r["chars_after"] for r in lad)
        print(f"output_ladder: {b} -> {a} chars ({(1 - a / b) * 100:.0f}% hidden, recoverable)")
    errors = [r for r in rows if "error" in r]
    print(f"errors: {len(errors)}  mode now: {rows[-1].get('mode')}")
    return True


projects = jevlib.jev_projects()
if len(projects) == 1:
    # No siblings: identical output to before this feature existed.
    if not summarize(projects[0]):
        print("No Jev decisions logged yet.")
else:
    for i, root in enumerate(projects):
        if i:
            print()
        print(f"== {root} ({'session root' if i == 0 else 'sibling'}) ==")
        if not summarize(root):
            print("No Jev decisions logged yet.")
