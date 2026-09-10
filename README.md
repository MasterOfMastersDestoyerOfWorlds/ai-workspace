# ai-workspace

The hub for Claude Code settings, hooks and worktree tools across the user's repositories.
Sessions start in this checkout and reach the other repositories as sibling directories.

## REPO_HOME

Every tool and hook finds the other repositories through `REPO_HOME`, the directory that holds
them all:

```
$REPO_HOME/
  ai-workspace/    this repo
  Ixdar/           the application
  ixdar-tickets/   the ticket store
  autofix/         checkstyle rules and recipes
  obsidian/        notes
```

Resolution, in `tools/paths.py`:

1. the `REPO_HOME` environment variable, when set;
2. otherwise the parent directory of this checkout.

So a checkout at `~/Code/ai-workspace` needs no configuration as long as its siblings sit next
to it. Set the variable only when the repositories live somewhere else. Claude Code sessions
read it from `.claude/settings.local.json` (untracked; `setup` writes it), terminals from the
shell profile. Nothing in the tracked files may hold a machine-specific path.

## Setup on a new machine

Requires `git`, [`uv`](https://docs.astral.sh/uv/), a JDK and Maven.

```bash
git clone https://github.com/MasterOfMastersDestoyerOfWorlds/ai-workspace.git ~/Code/ai-workspace
cd ~/Code/ai-workspace
uv run setup
```

`setup` clones every entry of `repos.json` into `REPO_HOME`, installs `wt`, `land` and `setup`
on PATH (`uv tool install --editable .`), creates the venv the hooks and tests use, records
`REPO_HOME` in `.claude/settings.local.json` and the shell profile (`setx` on Windows), and
installs the autofix artifact into `~/.m2`. Every step is idempotent. `--dry-run` prints the
plan, `--repo-home DIR` chooses another location, `--no-shell`, `--no-tools` and `--no-maven`
skip steps. Open a new terminal afterwards.

## Contents

- `.claude/settings.json`: permissions (the deny list keeps agents off git history and `land`),
  the hook wiring, and the sibling directories a session may touch.
- `hooks/`: Claude Code hooks. `shell_edit_guard.py` and `sleep_poll_guard.py` run before every
  Bash call; `checkstyle_edit.py` runs after Edit and Write on Java files. Hook commands use
  `${CLAUDE_PROJECT_DIR}`, which Claude Code substitutes on every platform.
- `tools/`: `wt` (`worktree_sync.py`, for agents), `land` (`worktree_land.py`, user only),
  `setup`, `transcript_stats.py`, and `paths.py`.
- `.claude/skills/`: `/ix-tool-review`.
- `reports/`: tool-review reports (untracked).
