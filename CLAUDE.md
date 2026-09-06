# ai-workspace

This repo is the hub for Claude settings across all of the user's projects. Sessions start here
and reach other repos (Ixdar, ixdar-tickets, autofix, obsidian) as additional directories.

## Working directory

Never move the session's working directory out of `/home/acw/Code/ai-workspace`. Use absolute
paths into the other repos. If a project needs a repo-local feature (worktrees, project settings),
add or allow it in this repo's `.claude/settings.json` rather than relocating the session.

## Commits

Never add `Co-Authored-By`, "Generated with", or any other attribution trailer to commit
messages, PR descriptions, or commit commands given to the user. Plain message only.

## Subagents

Spawn Agent-tool subagents with `model: "opus"`. Parallel Fable subagents hit the Fable session
rate limit and were killed mid-work. When relaunching an interrupted agent, tell it to inspect
`git status` and `git diff` in its worktree first and continue from the partial state.

For Ixdar tickets, agents work in `/home/acw/Code/Ixdar/.claude/worktrees/<ticket>` on a branch
of the same name, never commit, and add a `.vscode/launch.json` entry plus screenshots under
`tmp/` so the user can verify with F5. Those launch entries are verification aids the user strips
before merging. Do not create `VERIFICATION.md` files; put verification results in the agent's
final report and on the ticket.

## Ixdar tickets

The live ticket store is `/home/acw/Code/ixdar-tickets` (standalone clone, branch `main`). The
nested `Ixdar/ixdar-tickets` submodule is dead; do not use it.

- Mutate tickets only through `uv run python generate_board.py create|update|mark`, never by
  hand-editing JSON. If the CLI lacks an option, extend the script first.
- `create` and `update` support `--blocked-by` / `--blocks` (reciprocal), `--unknown`,
  `--related-file`, repeatable `--subsystem`, and `--add-changes`.
- Check the VIEW, PATCH, MESH and VOYAGE epics for overlap before creating mesh or viewer tickets.
