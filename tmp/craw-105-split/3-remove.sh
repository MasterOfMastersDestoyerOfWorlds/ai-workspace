#!/usr/bin/env bash
# Step 3. Remove from craw-105 the whole files that steps 1 and 2 moved elsewhere.
# DESTRUCTIVE in craw-105: deletes new files and puts modified files back to master.
# Run only after step 0's snapshot exists and the destinations have been checked.
# `git checkout` is denied to Claude, so the user runs this one.
set -euo pipefail
WT="${REPO_HOME:-$HOME/Code}/Ixdar/.claude/worktrees"
SRC="$WT/craw-105"
OUT="$(cd "$(dirname "$0")" && pwd)"
J=ixdar-app/src/main/java/ixdar
T=ixdar-app/test/unit/mesh
R=ixdar-app/src/main/resources/dsl/fixtures

test -s "$OUT/craw-105-tracked.patch" && test -s "$OUT/craw-105-untracked.tgz" \
  || { echo "no snapshot: run 0-backup.sh first"; exit 1; }

# New files that now live in another worktree. Each is checked to exist there first.
gone() { # gone <destination worktree> <file>...
  local dst="$WT/$1"; shift
  for f in "$@"; do
    cmp -s "$SRC/$f" "$dst/$f" || { echo "differs or missing in $dst: $f"; exit 1; }
    rm "$SRC/$f"; echo "  removed $f"
  done
}

gone craw-106 \
  $J/geometry/mesh/data/rings/RingAnchorFit.java \
  $J/geometry/mesh/data/rings/AnchoredRings.java \
  $J/geometry/mesh/data/rings/RingBlend.java \
  $J/nodegraph/nodes/selection/FitRingAnchorsNode.java \
  $J/tools/ring/AnchorGrooveFit.java \
  $T/RingAnchorFitTest.java
for f in "$SRC"/$R/ring_fit_*.dsl; do gone craw-106 "$R/$(basename "$f")"; done

gone craw-107 \
  $J/geometry/mesh/data/rings/RingCurveFit.java \
  $J/geometry/mesh/data/rings/RingSettle.java \
  $J/nodegraph/nodes/selection/FitRingsNode.java \
  $J/nodegraph/nodes/selection/FittedRingMarksNode.java \
  $J/nodegraph/nodes/selection/RingCurvesNode.java \
  $J/nodegraph/nodes/selection/SettleRingsNode.java \
  $J/nodegraph/nodes/selection/SettledRingMarksNode.java \
  $J/nodegraph/nodes/selection/RingMembershipNode.java \
  $J/nodegraph/nodes/selection/RingNetworkNode.java \
  $J/nodegraph/nodes/selection/RingCreaseEnergyNode.java \
  $J/geometry/mesh/quadlayout/embedding/RingPatchNetwork.java \
  $J/geometry/mesh/quadlayout/embedding/RingNetworkCarve.java \
  $J/geometry/mesh/quadlayout/embedding/SurfaceChordTrace.java \
  $J/geometry/mesh/quadlayout/gridmap/FlattenedFaceUv.java \
  $J/geometry/mesh/quadlayout/gridmap/GridWallPull.java \
  $T/RingCurveFitTest.java \
  $T/RingSettleTest.java \
  $T/RingNetworkSolveTest.java

gone craw-108 \
  $J/tools/connection/GrowTool.java \
  $J/geometry/mesh/data/rings/GrownPatch.java

# Modified files whose whole diff moved: back to master in craw-105.
git -C "$SRC" checkout -- \
  $J/nodegraph/nodes/selection/SplineCutNode.java \
  $J/geometry/mesh/quadlayout/embedding/TJunctionExtension.java \
  $J/geometry/mesh/quadlayout/gridmap/GlobalGridMap.java \
  $J/geometry/mesh/quadlayout/gridmap/GridMapOptimizer.java \
  $J/tools/connection/package-info.java \
  ARCHITECTURE.md \
  $J/tools/connection/ConnectionTool.java \
  $J/scenes/Scene.java \
  $J/scenes/model/ModelScene.java \
  $J/automation/endpoints/ui/MultiviewScreenshot.java

git -C "$SRC" status --short | wc -l
