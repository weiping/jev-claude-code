# Contributing

## Layout

| Path | What lives there |
| --- | --- |
| `.claude-plugin/marketplace.json` | Marketplace `jev-engineering`, lists the `jev` plugin |
| `plugins/jev/.claude-plugin/plugin.json` | Plugin manifest, including `version` |
| `plugins/jev/hooks/hooks.json` | Which hook events and tool matchers run which script |
| `plugins/jev/scripts/` | One script per hook, plus `jevlib.py` (config, Jev client, logging, state) |
| `plugins/jev/config/default.json` | Default thresholds and patterns |
| `plugins/jev/skills/` | `/jev:init`, `/jev:stats`, `/jev:snapshot`, `/jev:recall` |
| `plugins/jev/agents/` | `cheap-worker` and `readonly-reviewer` subagents |
| `tests/` | Offline unit tests and the end-to-end test |

Read [`plugins/jev/GOTCHAS.md`](plugins/jev/GOTCHAS.md) before changing a hook or the config.

## Rules for hook code

- Keep every threshold and branch in code or config. Jev answers typed questions; the script
  decides what to do with the answer.
- Wrap `main` in `jevlib.guard`, exit 0, and print nothing unless you return a decision.
- Log every Jev call and every action through `jevlib.ask` and `jevlib.log`. `/jev:stats` and
  the tests read `decisions.jsonl`.
- Respect shadow mode: compute and log the decision, then emit it only when
  `jevlib.mode() == "enforce"`.
- New settings go in `config/default.json` with a safe default. Lists replace on merge, so
  add an `extra_*` list when projects should extend a default list.

## Test

Neither test needs an Anthropic or TypeSafe key.

```bash
# 1. Unit tests: every hook with a mocked Jev transport, in a throwaway git repo.
#    Any Python with typesafe-sdk works; the installed plugin's venv is the quickest.
~/.claude/plugins/data/jev-jev-engineering/venv/bin/python tests/test_hooks.py
# or: python3 -m venv /tmp/jev-venv && /tmp/jev-venv/bin/pip install -r plugins/jev/requirements.txt
#     /tmp/jev-venv/bin/python tests/test_hooks.py

# 2. End to end: installs the plugin from this checkout into an isolated CLAUDE_CONFIG_DIR and
#    drives the real `claude` binary against a scripted fake Messages API.
bash tests/e2e.sh

# 3. Manifests, skills and agents.
claude plugin validate .

# 4. Lint (config in ruff.toml).
ruff check .
```

`e2e.sh` needs `claude` and `python3` on `PATH`, network access for the first
`pip install typesafe-sdk`, and a free port 8765 (`E2E_PORT=9000 bash tests/e2e.sh` to change
it). It prints `e2e ok: ...` on success. The `Terminated: 15` line after it is the cleanup trap
stopping the mock server, not a failure.

When you add a hook behavior, add a case to `tests/test_hooks.py` with canned answers
(`run(hook, payload, answers)`), and extend the assertions in `e2e.sh` if the behavior is
visible to the model.

## Try your change in a real session

The installed plugin is a cached copy, so local edits are not picked up. Either test from an
isolated config the way `e2e.sh` does, or push and update:

```bash
git push
claude plugin marketplace update jev-engineering
claude plugin update jev@jev-engineering
```

Then start a **new** Claude Code session; running sessions keep the old hooks. Bump `version`
in `plugins/jev/.claude-plugin/plugin.json` for any change users should receive, since the
cache is keyed by version.

## Release

1. Bump `version` in `plugins/jev/.claude-plugin/plugin.json`.
2. Run the four checks above.
3. Commit with a conventional message (`feat:`, `fix:`, `docs:`, `chore:` ...).
4. `claude plugin tag .` to create the `jev--v<version>` tag, then push the branch and the tag.
