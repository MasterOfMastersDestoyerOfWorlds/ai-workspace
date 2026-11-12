#!/usr/bin/env bash
# Step 0. Snapshot the craw-105 worktree's uncommitted work before anything moves.
# Changes nothing in any worktree. Writes two files next to this script.
set -euo pipefail
WT="${REPO_HOME:-$HOME/Code}/Ixdar/.claude/worktrees"
OUT="$(cd "$(dirname "$0")" && pwd)"

# Every edit to a tracked file, as one patch.
git -C "$WT/craw-105" diff --binary > "$OUT/craw-105-tracked.patch"
# Every new file, as one archive.
git -C "$WT/craw-105" ls-files --others --exclude-standard -z \
  | tar -C "$WT/craw-105" --null -T - -czf "$OUT/craw-105-untracked.tgz"

ls -la "$OUT/craw-105-tracked.patch" "$OUT/craw-105-untracked.tgz"
