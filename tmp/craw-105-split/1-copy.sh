#!/usr/bin/env bash
# Step 1. Copy whole files from craw-105 into the new worktrees.
# Additive: craw-105 is not touched. Every destination is on the same master commit as
# craw-105, so copying a modified file whole is the same as applying its diff.
set -euo pipefail
WT="${REPO_HOME:-$HOME/Code}/Ixdar/.claude/worktrees"
SRC="$WT/craw-105"
J=ixdar-app/src/main/java/ixdar
T=ixdar-app/test/unit/mesh
R=ixdar-app/src/main/resources/dsl/fixtures

copy() { # copy <destination worktree> <file>...
  local dst="$WT/$1"; shift
  for f in "$@"; do install -D -m 644 "$SRC/$f" "$dst/$f"; echo "  $dst/$f"; done
}

echo "craw-106: ring anchor fit"
copy craw-106 \
  $J/geometry/mesh/data/rings/RingAnchorFit.java \
  $J/geometry/mesh/data/rings/AnchoredRings.java \
  $J/geometry/mesh/data/rings/RingBlend.java \
  $J/nodegraph/nodes/selection/FitRingAnchorsNode.java \
  $J/tools/ring/AnchorGrooveFit.java \
  $J/nodegraph/nodes/selection/SplineCutNode.java \
  $T/RingAnchorFitTest.java
for f in "$SRC"/$R/ring_fit_*.dsl; do copy craw-106 "$R/$(basename "$f")"; done

echo "craw-107: settle, curve fit, ring patch network (to archive)"
copy craw-107 \
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
  $J/geometry/mesh/quadlayout/embedding/TJunctionExtension.java \
  $J/geometry/mesh/quadlayout/gridmap/FlattenedFaceUv.java \
  $J/geometry/mesh/quadlayout/gridmap/GridWallPull.java \
  $J/geometry/mesh/quadlayout/gridmap/GlobalGridMap.java \
  $J/geometry/mesh/quadlayout/gridmap/GridMapOptimizer.java \
  $T/RingCurveFitTest.java \
  $T/RingSettleTest.java \
  $T/RingNetworkSolveTest.java

echo "craw-108: grow tool"
copy craw-108 \
  $J/tools/connection/GrowTool.java \
  $J/geometry/mesh/data/rings/GrownPatch.java \
  $J/tools/connection/package-info.java \
  ARCHITECTURE.md

echo "craw-109: connection tool leak finder and cut"
copy craw-109 \
  $J/tools/connection/ConnectionTool.java

echo "ui-21: toolbar"
copy ui-21 \
  $J/scenes/Scene.java \
  $J/scenes/model/ModelScene.java \
  $J/automation/endpoints/ui/MultiviewScreenshot.java
