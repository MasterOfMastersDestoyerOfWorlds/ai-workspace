# ai-workspace

This repo is the hub for Claude settings across all of the user's projects. Sessions start here
and reach other repos (Ixdar, ixdar-tickets, autofix, obsidian) as additional directories.

## Repo layout

Every repo lives directly under `$REPO_HOME`, the parent directory of this checkout unless the
`REPO_HOME` environment variable says otherwise (`~/Code` on the user's machines; `ixd/paths.py`
resolves it, `README.md` explains it, `ixd setup` configures a new machine). Reach the repos by
absolute path, never by moving the session. Never write a machine-specific path into a tracked
file.

- `$REPO_HOME/ai-workspace` — this repo. `.claude/settings.json` (permissions, the deny list),
  `.claude/skills/`, `hooks/`, `ixd/` (the CLI: every command is a decorated function at
  `ixd/commands/<command>/<subcommand>.py`, and `README.md` plus `HELP.md` are generated from those
  docstrings by `ixd docs`; the shared engines are `worktree.py`, `machine.py`, `transcripts.py`
  and `paths.py`), `repos.json` and `reports/`. `ixd` is the only executable: `ixd wt`, `ixd land`,
  `ixd setup`, `ixd stats`, `ixd docs`. The bare `wt`, `land` and `setup` names are gone. Run
  `ixd docs` after changing a docstring and `uv run black ixd hooks` after changing any Python here.
- `$REPO_HOME/Ixdar` — the Java/Maven application (`annotations`, `ixdar-app`) plus the
  `ixdar_automation_cli` Python CLI (`uv run ixdar-cli`). Agent worktrees live at
  `Ixdar/.claude/worktrees/<ticket>`; `Ixdar/CLAUDE.md` carries the code conventions.
- `$REPO_HOME/ixdar-tickets` — the live ticket store, branch `main` (see below).
- `$REPO_HOME/autofix` — the checkstyle configuration and the custom checks, built as the
  `autofix-tool` artifact that Ixdar's `maven-checkstyle-plugin` resolves from `~/.m2`. **There is
  no `checkstyle.xml` inside Ixdar** — do not search the filesystem for one. The rules are
  `autofix/src/main/resources/checkstyle.xml`, the custom modules
  (`JavadocDescriptionLengthCheck`, `MeaningfulDuplicateStringLiteralsCheck`,
  `SingleCallerHelperCheck`, `UnnecessaryFullyQualifiedNameCheck`) are under
  `src/main/java/ixdar/autofix/checkstyle/`, and the OpenRewrite recipes that fix violations
  automatically are next to them in `recipes/`. Changing a rule means editing autofix and
  reinstalling that artifact, not editing anything in Ixdar.
- `$REPO_HOME/obsidian` — the user's notes vault.

## Working directory

Never move the session's working directory out of this checkout of ai-workspace. Use absolute
paths into the other repos. If a project needs a repo-local feature (worktrees, project settings),
add or allow it in this repo's `.claude/settings.json` rather than relocating the session.

## No tests in this repo

**Scope: the files of this repo only.** This rule says nothing about Ixdar, ixdar-tickets or
autofix. An agent working on a ticket in any of those repos writes the tests that repo's own
CLAUDE.md and the ticket ask for, and must ignore this section entirely.

Nothing under `hooks/` or `ixd/` carries a test suite: no `test_*.py`, no pytest dependency, no
test runner in `pyproject.toml`. Verify a change here by running the tool or the hook and showing
its output.

## Commits

Never add `Co-Authored-By`, "Generated with", or any other attribution trailer to commit
messages, PR descriptions, or commit commands given to the user. Plain message only.

## Subagents

Spawn Agent-tool subagents with `model: "opus"`. Parallel Fable subagents hit the Fable session
rate limit and were killed mid-work. When relaunching an interrupted agent, tell it to inspect
`git status` and `git diff` in its worktree first and continue from the partial state.

For Ixdar tickets, agents work in `$REPO_HOME/Ixdar/.claude/worktrees/<ticket>` on a branch
of the same name and add a `.vscode/launch.json` entry plus screenshots under `tmp/` so the user
can verify with F5. Git inside a worktree goes through `ixd wt` (the bare `wt` is an alias;
installed from this repo's pyproject with `uv tool install --editable .`); it takes a worktree
path or a bare name such as `craw-27`, refuses the main checkout and the main branch, and
`git add`, `git commit`, `git merge` stay denied. The model:
the worktree's uncommitted diff is the proposed change, sitting directly on top of master so
`git diff` shows exactly what would land. The lifecycle is `wt new <ticket>` (create the worktree
and branch, seed its environment, print the brief an agent needs), `wt status <ticket>` (branch,
distance from master, changed files, and the last note of the agent that worked there — this is
what a relaunch reads instead of a hand-written brief), `wt sync <ticket>` (rebase that diff onto
the current master and leave it uncommitted again), `wt launch add <ticket> --scene <id>` (write
the launch.json entry as JSONC, comments intact) and `wt done <ticket>` (sync, build, run the
entry, check `tmp/` holds a screenshot, mark the ticket REVIEW, refusing with a reason on any
failed step); `commit -m` makes one squashed commit on top of master (only after a sync). Agents
leave their work uncommitted; they run `sync` when they need newer master. The
user alone merges to master, with `ixd land <name>` (sync, strip launch.json entries, squash-commit
with the ticket title as message, fast-forward master, remove the worktree and branch, mark the
ticket DONE). `land` is on the deny list in every spelling; never run it or suggest a way around it. Those launch entries are verification aids the user strips
before merging. Do not create `VERIFICATION.md` files; put verification results in the agent's
final report and on the ticket.

The `wt` docs an agent sees live in `Ixdar/CLAUDE.md` ("Worktrees and git"), which is the file a
ticket agent actually reads; keep the two in step when a verb changes.

## Ixdar tickets

The live ticket store is `$REPO_HOME/ixdar-tickets` (standalone clone, branch `main`). The
nested `Ixdar/ixdar-tickets` submodule is dead; do not use it.

- Mutate tickets only through `uv run python generate_board.py create|update|mark`, never by
  hand-editing JSON. If the CLI lacks an option, extend the script first.
- `create` and `update` support `--blocked-by` / `--blocks` (reciprocal), `--unknown`,
  `--related-file`, repeatable `--subsystem`, and `--add-changes`.
- Check the VIEW, PATCH, MESH and VOYAGE epics for overlap before creating mesh or viewer tickets.
- States: TODO, IN_PROGRESS, REVIEW, DONE, PINNED. When an agent's work is verified and waiting
  for the user to `land` it, mark the ticket REVIEW (`mark review ID`); DONE only after it is on
  master and every definition-of-done item holds.

## Hooks

`hooks/` holds three plain-python Claude Code hooks, wired through the `hooks` key of
`.claude/settings.json`. `checkstyle_edit.py` runs after Edit and
Write: when the edited file is a `.java` file under an Ixdar checkout or worktree it audits that
one file with the configuration the build uses (`checkstyle.xml` off the autofix-tool artifact,
classpath cached in `~/.cache/ai-workspace-hooks/`) and returns the violations in about a second,
so JavadocDescriptionLength no longer costs a module compile. `shell_edit_guard.py` runs before
Bash and refuses `sed -i`, `awk -i inplace`, `perl -pi`, python heredocs and `python -c` that
write files, and `cat`, `tee` or a redirection onto a tracked source path, pointing at Edit and
Write instead; it also refuses `cat` of four or more repository files, pointing at Read. Shell
writes under a `tmp/`, `target/` or scratchpad path stay allowed. `sleep_poll_guard.py` also runs
before Bash and refuses until-sleep and while-sleep loops, sleep-then-command chains and reads of
the harness task-output directory, pointing at the Monitor tool and `run_in_background`. These
hooks override the harness auto-mode instruction to prefer Bash for file edits: they are the
enforcement, and prompt-level bans were not.

## Third-party code

When porting an algorithm, cite the source repository URL and its license in a comment at the
port site. Only permissive licenses (MIT, BSD, Apache) are acceptable: the code must stay
commercialisable. GPL and AGPL code is banned, including reading it for reference. No vendored
reference directories.
