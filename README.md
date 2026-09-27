# jev-claude-code

A Claude Code plugin that puts [TypeSafe Jev](https://docs.typesafe.ai) in the agent loop to make
Claude Code faster and cheaper. Jev answers typed questions (choice / score / yes-no) with
probabilities; the plugin keeps every threshold and branch in code.

| Hook / component | What it does |
| --- | --- |
| `PreToolUse(Bash)` permission gate | Hard rules in code, fuzzy judgment from Jev: allow / ask / deny, reads scripts before running them |
| `PostToolUse(Bash)` output ladder | Long output is shown in full, excerpted, or hidden per the current request; originals are always recoverable |
| `UserPromptSubmit` / `SessionStart(compact)` | Loads project guidance only when relevant, suggests project tools, re-injects after compaction |
| `PreToolUse(Agent)` router | Downgrades mechanical subagent work to haiku, keeps sensitive work off cheap models, blocks duplicate subgoals |
| `/jev:init` `/jev:stats` `/jev:snapshot` | Project setup, decision statistics, shared retrieval for parallel read-only reviewers |

Everything runs in **shadow mode** by default: Jev is called and every decision is logged, but
Claude Code's behavior does not change until you switch to enforce mode.

## Install

Requirements: Claude Code 2.1.196 or later (tested on 2.1.281), Python 3.10+, git, and a TypeSafe
API key with access to `jev-1.13.0`.

```text
/plugin marketplace add weiping/jev-claude-code
/plugin install jev@jev-engineering
```

or from a shell: `claude plugin marketplace add weiping/jev-claude-code && claude plugin install jev@jev-engineering`.

Set the key before starting Claude Code (hooks inherit its environment):

```bash
export TYPESAFE_API_KEY=ts_...
claude
```

The first session installs `typesafe-sdk` into the plugin's data directory
(`~/.claude/plugins/data/jev-jev-engineering/`). Until that finishes, every hook stays silent.

## Set up a project

Run `/jev:init` inside the project. It scans the repository and writes `.claude/jev/rules.json`,
`tools.json` and `config.json`. Runtime state and logs go to `.claude/jev/state/` and
`.claude/jev/logs/`, each with its own `.gitignore`.

After about a week in shadow mode, run `/jev:stats`, tune thresholds in `.claude/jev/config.json`,
then turn it on:

```json
{ "mode": "enforce" }
```

or for a single session: `JEV_MODE=enforce claude`.

## Configuration

Defaults live in `plugins/jev/config/default.json`; `.claude/jev/config.json` in a project is
deep-merged on top (lists are replaced, so add project deny rules under
`permission.extra_deny_patterns`).

## Develop and test

See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow and
[plugins/jev/GOTCHAS.md](plugins/jev/GOTCHAS.md) for behavior that is easy to get wrong.

```bash
python3 -m venv /tmp/jev-venv && /tmp/jev-venv/bin/pip install -r plugins/jev/requirements.txt
/tmp/jev-venv/bin/python tests/test_hooks.py   # offline unit tests, mocked Jev
bash tests/e2e.sh                              # real Claude Code + scripted fake model API
claude plugin validate .
```

Neither test needs an Anthropic or TypeSafe key. `e2e.sh` installs the plugin from this repo
into an isolated `CLAUDE_CONFIG_DIR`.

## Data and privacy

The permission gate sends commands and script contents, the output ladder sends command output,
and the router sends subagent task descriptions to TypeSafe. Keep sensitive paths in
`deny_patterns` so they are blocked before any Jev call.

## License

MIT
