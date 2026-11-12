# TOOL-56 test review: merged report

**How this was produced:**
- **Coordinator:** Opus 5.5.
- **Reviewers:** 21 Sonnet batches, each checked for coverage and sent back where it fell short.
- **Criteria:** `.claude/skills/test-review/criteria.md`.
- **Per-test verdicts:** in `tmp/test-review/<batch>.md`. This file gives the totals and everything that needs a decision.
- **Static-check ideas:** in `tmp/test-review-static-checks.md`.

**Baseline** (master, tool-56 worktree, one `mvn test`):
- 820 tests in 188 classes: 64.1 s of test time and 71 s of wall time.
- 28 s of that wall time is compile and test-compile.
- One test fails on master: `PatchColoursTest.scalarShaderHoldsTheRampPalette`. It reads `src/main/resources/glsl/mesh_scalar.fs` by a path relative to the working directory (criterion 14).

## Totals

| Verdict | Unit tests | Their time today | Benchmarks (not run by `mvn test`) |
|---|---|---|---|
| KEEP | 351 | 2.37 s | 0 |
| REWRITE | 364 | 43.27 s | 3 |
| SHRINK | 37 | 11.34 s | 1 |
| MOVE | 4 | 4.44 s | 6 |
| MERGE | 37 | 1.75 s | 5 |
| DELETE | 10 | 0.95 s | 19 |

Two thirds of the REWRITEs come from your DSL rule alone (criterion 9). They check the right
thing, but they build their geometry in Java. Most of them are **one fixture swap per class**,
and many classes share one fixture. Three shared Java builders feed 50+ tests across classes:
`RingRegionsTest.cappedCylinder`, `RingAnchorOrderTest.tube` and `GridMeshNode.triangulated`.
A REWRITE only saves time when its sketch also shrinks the input.

### Projected suite time

These numbers are the reviewers' estimates, not measurements.

| Bucket | Today | After |
|---|---|---|
| SilhouetteHullNodeTest | 29.0 s | about 0.6 s (skull hull moved to `heavy`, the rest at resolution 32) |
| The next 14 slowest classes (table below) | 28.1 s | about 3.5 s |
| Everything else | 7.0 s | about 3.7 s |
| **Total** | **64.1 s** | **about 7 to 8 s** |

**5 s is reachable, but not from these verdicts alone.** Two more things are needed:
- **Class warm-up:** about 188 classes each pay first-method warm-up of 5 to 130 ms. The cure is
  fewer, larger test classes, or one shared JVM-warm fixture.
- **The three remaining heavy fixtures:** the ring scene in RegionControlAutomationTest, the
  Y-shaped extraction in the ring-candidate and ring-deletion tests, and the stroke spheres.
  Each has to land near its estimate.

Maven and JVM overhead of about 7 s stays in the wall time whatever the tests do. Compile time
falls by about 4.3k lines: the deleted and merged benchmarks plus the `ManifoldShell` helper.

### Slowest classes

| Class | Time | Verdicts (time) | What the reviewer proposes |
|---|---|---|---|
| SilhouetteHullNodeTest | 29.05 s | REWRITE 29.0 | **Skull (14.2 s):** 10 pipelines at resolutions up to 96; move it to `heavy`. **Symmetry (8.8 s):** an O(V²) nearest-mirror loop; compare volumes at resolution 32 instead. **Notched hull (4.3 s):** the rasteriser calls `hypot` per pixel per edge. All fixtures become `.svg`/`.dsl` at resolution 32. |
| GoldenFingerprintTest | 4.08 s | REWRITE 4.05 | `fertility_ring_pick` (2.2 s) runs on a 14k-vertex scan. See Goldens below. |
| CreaseRingTest | 2.90 s | SHRINK 2.82 | A 23k-face tube built in Java; use a coarse notched-tube fixture with fewer clicks. |
| TradeGameTest | 2.83 s | MOVE 2.26 | `oneSmallLoopEarnsBronzeAtBest` is a brute-force balance check; move it to `heavy`. |
| SurfaceRidgesTest | 2.72 s | SHRINK 1.79, REWRITE 0.93 | Share one fit; use a coarse ellipsoid. |
| RegionControlAutomationTest | 2.35 s | REWRITE 2.33 | One `ring_scene_cylinder.dsl` fixture; three slow methods also shrink. |
| MeshNodeIndependenceTest | 2.17 s | MOVE 2.17 | A source-scanning lint; it becomes a checkstyle module. |
| StrokeKeyTest + SculptSyncTest | 3.71 s | SHRINK/REWRITE | Rebuild a resolution-48 sphere on every `sync()`; one `stroke_base_sphere.dsl` at resolution 16 to 24, loaded in `@BeforeAll`. |
| RingDeletionTest + RingCandidatesTest | 3.00 s | mixed, 1 DELETE | Extract the Y once per class; `theYRankingIsStableAcrossRuns` (458 ms) is a determinism lock-in and is deleted. |
| ReferenceStrokesTest | 1.53 s | SHRINK | Shared pictures, halved raster, a smaller sphere. |
| StrokeSculptTest | 1.42 s | SHRINK/REWRITE | `sphere()` at resolution 64 becomes `stroke_ball.dsl` at 24 (about 7x fewer faces). |
| BisectorTest | 0.89 s | REWRITE | An 8.3k-face Java tube becomes `bisector_tube.dsl` at about 2k faces. |
| TriangleSoupRingOrderTest | 0.46 s | DELETE | An equivalence lock-in against the algorithm from before CRAW-87. |

## Goldens (section C)

Only `GoldenFingerprintTest` reads the 30 goldens under `test/resources/golden`. Every golden is
a mesh SHA-256 plus counts, recorded from a run (TOOL-28). **None is a hand-checked reference.**
All of them break on any change to vertex order, face order, float bits or tessellation, even
when the geometry is identical. Two have already been re-recorded after correct changes
(CRAW-81, MESH-92).

| Goldens | Recommendation |
|---|---|
| 11 small arc-network fixtures (twin_cell, fan_collapse, loop_collapse, the layouts, …) | **Drop them.** Each fixture already has its own `*FixtureTest` with real assertions. |
| 13 small others (dungeon 2D/3D, quad cylinder, torus ring, the 4 layouts, the quad-layout sphere) | **Replace them with invariants:** Euler characteristic, closedness, quads only, face count after subdivision (4^levels), Poincaré–Hopf for the cross field. The reviewer listed one per file. |
| 12 real-scan goldens (fertility ×2, crawfish ×10) | Already `heavy` apart from fertility. These are the **only** candidates for the "master's golden handed to the agent" endpoint. |

**Recommendation:** don't build the endpoint for the default path. With the first two rows done,
nothing on the default path is bit-exact, so the "not bit identical" trap is gone. Revisit the
endpoint only if the scan goldens turn out to matter when they run in `heavy`.

Other bit-exact tests that work like goldens:
- `CrossFieldAssemblyTest`, against a copy of the old implementation with a tolerance of 0.0.
  The replacement invariant: the matrix is symmetric and the mass diagonal sums to area/2.
- `DijkstraTest` tie order. The replacement invariant: settled distances never decrease.
- The `CrossFieldEquivalenceBenchmark` fingerprint. The replacement invariant: the singularity
  indices sum to 4χ.

## Benchmarks (section D)

34 methods in 24 files, none kept as they are: DELETE 19, MOVE 6, MERGE 5, REWRITE 3, SHRINK 1.
- **Already fixed, nothing asserted:** most of them guard tickets that are DONE or ARCHIVED
  (CRAW-21/22/23/37/44/45/60/63/87, MESH-52/60/92/93/94, VIEW-25). They only print numbers.
- **Still the only guard:** three fixed problems — CRAW-93 cold repair (MESH-67 still open),
  CRAW-92 orientation and the CRAW-1 heap budget. These are MOVEs.
- **Guarding problems that are still open:** CRAW-2 (`SeamlessPipelineBenchmark`,
  `CrawfishQuadLayoutBenchmark`) and PATCH-123/124 (`CrossFieldEquivalenceBenchmark`).
- **Compile cost:** every MOVE should leave the test source root, as a `benchmark` source set or
  module, per TOOL-14.

## DSL gaps (criterion 9)

Each gap is a feature the app can't drive from DSL, so tests reach it from Java instead.
Grouped and deduplicated:

1. **Literal and odd meshes:**
   - a node that makes a mesh from explicit vertices and faces (a single triangle, a hand-placed quad);
   - tetrahedron and octahedron primitives;
   - a Möbius band;
   - non-manifold, mixed triangle/quad, unused-vertex or scrambled-order meshes;
   - an `ArrayMesh` output.
2. **Local edits:**
   - flip the winding of selected faces;
   - move one named vertex (a pleat);
   - a seeded jitter on interior vertices only;
   - rotate or transform a mesh;
   - a Gaussian groove or ridge displacement;
   - a radius profile on a tube;
   - a triangulated cylinder with height rows;
   - an n-gon cap on `quad_cylinder`.
3. **UV authoring:**
   - per-corner UVs and `CornerUvField`/`ChartAtlas`;
   - blank one face's UVs;
   - an unwelded mesh that keeps its corner UVs.
4. **Half-edge and topology operators:**
   - `flipEdge`, `splitFace`, `splitEdge` and `collapseEdge`;
   - `EmbeddedMeshTopology` split and `insertChord`;
   - `deactivateFace`;
   - the incremental edge-table edits.
5. **Arc-network internals:**
   - call `ArcRerouter.tryRoute` directly (five batches hit this);
   - pre-claimed arcs, edges and vertices;
   - a `network_node` at an exact barycentric;
   - `FaceStripPath` passages;
   - an arc `setPath` after creation;
   - a pre-routed folded arc;
   - wrapped patch corners and port tables;
   - expose `PatchRectangleMap`.
6. **Ring tool and scene:**
   - load a DSL surface and its rings into a `RingScene`. This one fix would unlock most of the
     ring-tool tests.
   - Reach these from DSL, where today only the ring tool does: `SliverCollapse`, the incremental
     `RingRegions.update`, `measureJoins`, `snapFraction` and the hover frame.
7. **Pictures:**
   - a primitive picture or mask node (an ellipse, a rectangle);
   - a headless silhouette render;
   - a shaded test picture;
   - an `OutlineOverlap` node.
8. **Analysis nodes:**
   - `ImplicitFit` and `SurfaceRidges`, `StrokeKey`, `SurfaceConnection`, `SurfacePicker` and
     `GirdlingPlane`;
   - `simplify_curve` and curve-from-points;
   - analytic SDF volume primitives;
   - symmetry and fold measures;
   - `ConformingLoopSnap` on a raw path;
   - glTF image and material access.

**Check before writing fixtures.** Several sketches assume node behaviour that no reviewer
checked, because reviewers ran nothing:
- `quad_cylinder cap_rings=0` leaves the ends open;
- `set_position` can rotate a mesh or express a groove;
- `uv_sphere(4,2)` gives the octahedron's vertex order;
- `quad_layout` accepts a `uv_sphere`;
- `RingScene.dslResource` loads a DSL resource.

## Bugs and oddities found on the way

- **PatchColoursTest fails on master:** it uses a path relative to the working directory (see
  Baseline above).
- **`RingCandidatesTest.aPlainTubeProposesNoRing`:** it runs the dumbbell, not the tube.
- **`ConstraintStripTest.aGrazingCrossingStaysOnItsEdge`:** it never calls the code its name
  describes.
- **`ScrollRegionHitTest` and `SnappingLaneOrderTest`:** they copy the production formula or loop
  (criterion 7). `SnappingCarve.splitEdgeIntoLanes` is never actually called.
- **`ZeroArcCollapseSteppingTest`:** it compares `collapse()` with its own stepped loop.
- **Dead or test-only production code (criteria 8 and 15):**
  - `GridMeshNode.triangulated`, `vertexId` and `rowCoordinate`: 0 production callers, 39 test uses;
  - `ZeroArcCollapseOperator.dragArcEndOntoVertex`;
  - `DirectSolver.refactorizeHandle`;
  - `SymmetricDirichletEnergy.projectHessian`;
  - `TJunctionExtension.extensionCount`;
  - `ExtractedPatchGrids.directMatchCount`;
  - `repeatedCornerReleaseCount`;
  - `branchOfRegion`, `tightenedRing` and `CYCLE_VERTEX_DEGREE`;
  - the `ModelCollection` cache accessors.
- **`DriftLocalizeScratchTest`:** it only prints and asserts nothing.

## Decisions for the user

1. **Hand-built internal state.** Three tests need state no DSL can express: the chart walker
   (`ChartWalkerStalledExitTest`), and the carve end-crossing and fold-back tests. Either they keep
   hand-built inputs with a stated exception, or each one becomes a DSL gap to close first.
   They're treated as gaps for now.
2. **Ring anchors computed in Java but written out as DSL** (the sliver-collapse tests). These
   are counted as DSL-sourced and KEEP. If the anchors must be `.dsl` files too, about 9 more
   tests become REWRITE.
3. **The skull hull test at resolution 48:** on the default path (about 1.2 s) or entirely
   `heavy`.
4. **`TradeGameTest.oneSmallLoopEarnsBronzeAtBest`:** move this balance invariant (2.3 s) to
   `heavy`.
5. **The goldens recommendation above:** drop the 11 small arc-network goldens, replace the 13
   other small ones with invariants, and build no endpoint.
6. **Test-only production code:** delete it together with its tests, `GridMeshNode.triangulated`
   included once its 39 callers use `mesh_grid` DSL.
7. **How to split the phase 2 work.** Suggested order, by time saved: SilhouetteHull; goldens;
   the ring-scene fixture (RegionControl, Bisector, and the ring tests); the stroke spheres;
   benchmarks out of the source root; then the criterion-9 fixture swaps, class by class.
