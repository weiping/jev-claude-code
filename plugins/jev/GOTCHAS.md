# Gotchas

Things that behave differently from what you would guess. Read this before changing a hook,
the config, or the install flow.

## Install and loading

- **Hooks are silent until the venv exists.** `run-hook.sh` exits 0 with no output unless both
  `$CLAUDE_PLUGIN_DATA/venv/bin/python` and the copied `requirements.txt` exist. The first
  session after install only runs `setup.sh`; decisions start in the next one.
- **The copied `requirements.txt` is the "install finished" marker.** `setup.sh` deletes it
  before installing and copies it back only after `pip install` succeeds. Changing
  `requirements.txt` therefore triggers a reinstall on the next session start, and hooks stay
  silent until it finishes.
- **A stale `.installing` lock blocks installs forever.** `setup.sh` uses
  `$CLAUDE_PLUGIN_DATA/.installing` as a lock so parallel sessions install once. A normal exit
  removes it; a killed process does not. If hooks never wake up, check for this directory and
  read `setup.log`.
- **Python 3.10+ is checked at install time only.** Without it, `setup.sh` writes one line to
  `setup.log` and exits 0; nothing tells the user. Set `JEV_PYTHON` to pick an interpreter.
- **Plugins load at session start.** Installing, updating or enabling the plugin does nothing to
  sessions that are already running.
- **A lost `enabledPlugins` entry disables the plugin with no trace.** A batch plugin change
  can leave `jev@jev-engineering` missing from `enabledPlugins` in `~/.claude/settings.json`;
  sessions then start fine but no hook runs and nothing is written to `decisions.jsonl`.
  If the log goes silent across sessions, check that entry and
  `claude plugin enable jev@jev-engineering`.
- **The installed plugin is a cached copy.** Claude Code runs it from
  `~/.claude/plugins/cache/jev-engineering/jev/<version>/`, not from this repository. Editing
  files here changes nothing until you push and update (see `CONTRIBUTING.md`).

## Hook contract

- **Every hook must exit 0.** `jevlib.guard` turns any exception into a logged
  `{"hook": ..., "error": ...}` row and no decision. A broken hook looks exactly like
  "Jev had no opinion"; the only trace is in `.claude/jev/logs/decisions.jsonl` and the
  `errors:` line of `/jev:stats`.
- **Printing nothing means "no decision".** Claude Code then runs its own permission flow.
  Never print debug output to stdout; it is parsed as hook JSON.
- **Jev being down is not an error for the user.** Timeouts and API failures are logged and the
  hook emits nothing. Keep `timeout_s` in `config/default.json` (8s, split into two attempts)
  well below the hook timeouts in `hooks/hooks.json` (15s and 20s), or Claude Code kills the
  hook first and nothing is logged.
- **`output_ladder` must return the whole `tool_response`.** It spreads the original response
  and replaces only `stdout`; returning a partial object makes Claude Code ignore it.

## Shadow mode

- **Shadow mode still calls Jev.** Every hook sends its data to TypeSafe and pays for the call;
  only the final `emit` is suppressed. The privacy note in the README applies in both modes.
- **Rule denies are logged but not enforced in shadow mode**, including `deny_patterns`.
- **`JEV_MODE` in the environment wins over `"mode"` in any config file.**

## Enforce mode

- **The egress branch denies before Jev's own decision is used.** When `egress >
  egress_threshold` and `network_requested < 0.5`, the command is denied for "network access"
  even if Jev's `decision` was `allow` with high confidence. `network_requested` is judged from
  the raw text in `last_prompt.txt`, not from the conversation: a terse imperative ("推送",
  "ship it") routinely scores just under 0.5, so `git push` gets denied on a prompt that
  clearly asked for a push. Retrying the identical command re-sends the same prompt and denies
  again. Put routine network commands in the project's `extra_allow_patterns`
  (e.g. `"^git push\\b"`) — allow rules run before the egress branch and cost no Jev call.

## Configuration

- **Dicts merge, lists replace.** The project `.claude/jev/config.json` is deep-merged over
  `config/default.json`, but a list replaces the default list entirely. Setting
  `permission.deny_patterns` in a project drops the built-in `.ssh`, `.env`, `curl | sh` and
  `rm -rf /` rules. Add project rules to `permission.extra_deny_patterns` instead. The same
  applies to `permission.allow_patterns` (default: `git add`/`git commit`) — extend it with
  `permission.extra_allow_patterns`. Deny patterns always win over allow patterns.
- **Deny patterns match the command string only.** They are `re.search`ed against the raw
  Bash command. `cat .env` is blocked; `python3 load.py` that reads `.env` inside the script is
  not (the gate does send the script text to Jev, which may still deny it).
- **Any shell metacharacter disables the readonly shortcut.** A command containing
  `; & | < > \` $ ( )` is never "simple readonly", so `ls | head` costs a Jev call while `ls`
  does not. The metacharacter check is a raw string scan — quoting does not help, so
  `gh run view 1 --jq '.jobs[] | …'` loses the shortcut to the `|` inside the quotes. Worse in
  enforce mode: the compound then reaches Jev and a network-flavored readonly command
  (`gh run watch 1 >/dev/null; gh run view 1`) is denied by the egress branch. Run
  `gh run view`/`list`/`watch` bare, one command per call.
- **The project root comes from `CLAUDE_PROJECT_DIR`, then `git rev-parse --show-toplevel`.**
  Running a script by hand from a nested repository picks the nested repo's `.claude/jev/`.
  Set `CLAUDE_PROJECT_DIR` when you run `stats.py` or `snapshot.py` manually.
- **`CLAUDE_PROJECT_DIR` is fixed for the whole session — `jevlib.resolve(hint)` is how
  per-invocation hooks stop being stuck with it.** `permission_gate`, `agent_router`,
  `agent_done` and `output_ladder` all call `jevlib.resolve(data.get("cwd"))` first thing and
  use the returned `Resolved.cfg`/`.state`/`.logs`/`.project` instead of the module-level
  `jevlib.CFG`/`STATE`/`LOGS`/`PROJECT` — it walks up from `cwd` looking for the nearest
  `.claude/jev/`, falling back to the session root when none is found. This matters in a
  meta-workspace whose sibling repos are their own independent git checkouts (not part of the
  meta-repo's own git tree, typically `.gitignore`d out of it): a Bash command or a dispatched
  Agent that runs with `cwd` inside such a sibling picks up *that sibling's own*
  `config.json`/state/logs, even though `CLAUDE_PROJECT_DIR` never changes. `agent_router` and
  `agent_done` must resolve from the *same* hint or the dedupe registry silently splits across
  two `subgoals.json` files and never finds the entry the other one wrote.
- **`prompt_context` cannot use `jevlib.resolve()` — it has no single-file hint at
  `UserPromptSubmit` time — so it does its own multi-root pass instead.** `jev_projects()`
  looks one level below the session root for direct child directories that carry their own
  `.claude/jev/`, and `main()` runs `touched_files()` once per project, matching each
  project's own `rules.json`/`tools.json` against its own change list. This is why a sibling's
  `git diff`-scoped `.claude/jev/` config only matters if the sibling sits one level directly
  under the session root — it is not a recursive search. The session root is always project
  index 0 and keeps its rule/tool ids unprefixed; a sibling at index `i` gets its `when_jev`
  rule ids prefixed `rule_s{i}_` and its tool keys prefixed `s{i}:` in the combined Jev
  request, so ids never collide across projects and a workspace with no siblings behaves
  exactly as before.

## Conditional context

- **No `rules.json` and no `tools.json` means no Jev call at all.** `prompt_context` only
  records the prompt until `/jev:init` has run.
- **`when_files` looks at changed files, not at the prompt.** It matches `git diff --name-only
  HEAD` plus untracked files. At the start of a task, before anything is modified, a
  `when_files` rule does not fire. In a repository with no commits, only untracked files count.
- **Globs use `fnmatch`, where `*` also matches `/`.** `src/*.tsx` matches
  `src/a/b/c.tsx`.
- **Injected context is cut at `context.max_chars` (9000).** Guidance files are concatenated
  first and the tool list last, so a large guidance file can push the tool suggestions out.
- **Rule ids become Jev question ids.** A `when_jev` rule is asked as `rule_<id>`, and tool ids
  become the criteria of one choice question, so ids must be unique within their file.
  `"none"` is reserved in `tools.json` for "no tool" and is never suggested.

## State shared between sessions

- **State is per project, not per session.** `last_prompt.txt`, `pinned_context.md` and
  `subgoals.json` live in `.claude/jev/state/`. Two sessions in the same project overwrite each
  other's "current request", and the subagent dedupe sees both sessions' subgoals.
- **Other hooks read the request from `last_prompt.txt`.** If it does not exist yet, they send
  `(unknown)` and Jev judges the command without a request.
- **Saved outputs are never cleaned up.** `output_ladder` writes every long output to
  `state/outputs/`. The directory is git-ignored but grows without bound.
- **Subagent dedupe only compares the last 50 subgoals.** A Jev choice question accepts at most
  255 options, and the registry is trimmed to keep requests small.
