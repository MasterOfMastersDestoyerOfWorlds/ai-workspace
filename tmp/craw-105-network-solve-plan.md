# Plan: rings → arc network → patches fitted to the crease field → rings

Ticket: ring and bisector segmentation of the crawfish scans (CRAW-105).

Scope, as corrected: only the stage of the quad pipeline where the arc network is turned into
patches and relaxed against an energy (`assembly` + `relax`). No contraction, no quad mesh, no
patch surfaces. The energy is the crease field. The relaxed network is converted back to rings.

## The group

`fit_rings` becomes four stages:

| # | Node | Status | In → out |
|---|---|---|---|
| 1 | `ring_network` | new | rings and bisectors → `ArcNetwork` with four-sided patches, carved into a working copy |
| 2 | `grid_map_assembly` | the layout's node; energy changed | network → patch maps and the DOF system |
| 3 | `newton_solver` | the layout's node, unchanged | DOF system → relaxed |
| 4 | `network_rings` | new | relaxed map → one set of edge marks per ring, labels kept |

## Status and findings (after reading the code and two cylinder tests)

Done, in `RingNetworkSolveTest` (worktree craw-105, uncommitted):

- **Tube test passes.** Three rings on the test cylinder joined by four seams, ten patches,
  through the layout's `GridMapAssembly` and `newton_solver` unchanged, with the surface itself
  as the reference field (`FlattenedFaceUv`): ten patches mapped, none folded, the middle ring's
  four nodes freed, relaxed in 3 iterations.
- **Groove test passes.** With the crease term (`GridWallPull`, hung on `GlobalGridMap.wallPull`
  and added in `GridMapOptimizer.totalEnergy` / `assembleInto`), a groove one row from the middle
  ring: the groove vertices go from 1.0 grid unit off the ring's grid line to 0.30 in 6 Newton
  iterations, no triangle folded. The distortion energy stays in as the barrier.

- **Junction test passes** (option A, the layout's `conform()`). A bisector from the middle ring
  to the top ring, its two ends T-junctions: `NetworkContraction.conform()` runs without the
  contraction rounds and extends them round the cylinder, 10 patches become 16, 10 nodes are
  freed (only the 8 three-corner nodes stay pinned), the groove still pulls the ring's line onto
  it, no triangle folded.
- **`conform()` needs real integer lengths** on the arcs with opposite sides of every patch
  summing equal: it places each extension at the matching offset on the far side and bounds its
  work by the layout's quantized area. On the cylinder they are set by hand (edges counted).
  For real rings stage 1 has to solve for them; the layout's own `IntegerProgram` (equalities
  plus "at least 1" rows) looks reusable. Not yet read in detail.
- **Patch orientation matters**: each arc needs one patch on each flank. A cap walked the wrong
  way still assembled, but split the grid into two components and broke conforming.

What the code requires that the plan below did not know:

1. **Every patch side must be exactly one arc** (`LayoutResolution.requireSingleArcSides`
   throws otherwise). No T-junctions: the rings plus seams must form a conforming layout. A
   bisector ending on a ring is a T-junction and has to be extended across the patch it ends
   against, as the layout's `NetworkContraction.conform()` does (LCK21a §6). This replaces the
   "four corners, other nodes are T-junctions" item of stage 1.
2. **Lengths need no solve.** Assembly sizes the arcs itself, one count per strip of opposite
   sides, from their length in the reference field. The lengths item of stage 1 is gone.
3. **A seam needs a different patch on each side** to be freed, and two patches may not share
   the same set of boundary arcs (`PatchRegions`). So a tube is cut by at least two seams, in
   practice four so that an end cap is a four-sided patch too.
4. **Which nodes move:** only nodes where four patch corners meet. In the test the middle ring's
   four nodes are free; the eight where a cap meets two side patches are three-corner nodes and
   stay pinned (a closed surface must have some). Nodes are added with `critical = false`.
5. **Not yet shown:** that a freed node itself lands in a groove (step 3), and the relaxed walls
   read back as rings (stage 4).

## What I read, and what I did not

Read: `QuadLayoutNode.build`, `GridMapAssemblyNode`, `NewtonSolverNode`, `GridMapAssembly`, the
field docs of `GridMapDofSystem`, the method list of `GridMapOptimizer`,
`ArcNetwork.addNode/addArc/addPatch`, `EmbeddedPatch`, LCBK19 §6.2.

Not read yet: the bodies of `GridMapOptimizer` (1,073 lines), `GridMapDofSystem.build`,
`LayoutPatchMaps`, `LayoutResolution`, `IntegerGridMap`, `PatchRectangleMap`. Step 0 is reading
them; what depends on them is marked **(to confirm)**.

## Stage 1: `ring_network` (rings → patches)

`grid_map_assembly` needs what `layout_embedding` hands it: nodes, arcs with a
`quantizedLength`, and four-sided patches (`ArcNetwork.addPatch(sourcePatchId, sideArcIds,
firstCornerId)`). The carve I have (`RingNetworkCarve`) makes the nodes and arcs. It gains:

1. **Seams, so every region is a disc.** A tube (a leg segment between two rings) gets one seam
   arc from ring to ring; a region with `k` boundary loops gets `k − 1`. A seam is a shortest
   path between the loops, kept off the creases. Seams are marked as seams and never become rings.
2. **Four corners per region.** A tube cut by its seam has them already (ring, seam, ring, seam
   back). A plate takes its four sharpest boundary turns; other nodes on a side are T-junctions.
3. **Lengths.** Each arc's `quantizedLength` from its surface length, with opposite sides of every
   patch equal (LCBK19 Definition 3.1). Without contraction every arc must be at least 1.
   **(to confirm)** how strictly assembly needs integers when no quads are extracted; if it does
   not, real lengths remove this step.
4. **No pre-fit.** Walls start where they were drawn; moving them is the solve's job.

Without the contraction stage, slivers stay as they are drawn (thin patches). They remain the
ring tool's `collapse-slivers` problem, as today.

## Stage 2: assembly with the crease field as the energy

Assembly maps every patch onto its rectangle, frames the patches in one grid, and builds the DOF
system: one slot per free vertex, seams coupled through their transitions, regular nodes freed
through their fan transforms. All reused. What the DOF system relaxes changes:

- **Energy.** A wall is where a patch's chart coordinate takes its boundary value `k`. For every
  vertex `v` in the band of a wall, with crease strength `c(v)` (the `surface_creases` valley
  strength) and area `A(v)`:

  `E = − Σ_v c(v) · A(v) · K((u(v) − k) / σ)`

  `K` a smooth bump of width `σ`. Lowest when the deepest groove vertices lie on the wall. Seam
  arcs get no term.
- **Fold-free.** The layout's distortion energy is also what stops the map folding. With the
  crease field as the only energy, that has to come from somewhere: I would keep the layout's
  fold-free step limit (`maximumStep`) as a constraint, and keep the distortion term only as a
  barrier (weight near zero, no pull of its own) if the step limit alone is not enough.
  **(to confirm)** in step 0 and in the first test.
- **Reference field.** Assembly takes a `UvField` to size the patches and as the triangles'
  reference shape. Rings have no seamless parametrization; a field that flattens each triangle
  as it lies on the surface stands in. **(to confirm)** that nothing in `LayoutPatchMaps` needs
  it to be seamless.

The form of `E` is my proposal; the papers do not give one for this use.

## Stage 3: `newton_solver`

Unchanged.

## Stage 4: `network_rings` (relaxed network → rings)

For every non-seam arc, trace the line where its patch's chart coordinate equals the boundary
value across the working copy (the same face-by-face crossing walk the carve uses, on the map
instead of a plane), carve it in, and mark its edges under the ring's label. Nodes land where the
relaxed map puts them. Output: the surface, each ring's marks, the part labels, and a report (wall
length and groove depth before and after, regions, slivers, rings that stopped walling, part
names left without a region).

**(to decide)** whether "rings" should also mean editable `spline_ring` / `spline_cut`
statements (anchors re-fitted to the relaxed walls, so the ring scene can open and edit the
result), or edge marks are enough.

## Order of work, each verified before the next

0. Read the unread code; settle the **(to confirm)** items; amend this plan.
1. **Tube.** Test cylinder, one ring: seam, two patches, assembly with the crease energy and no
   groove. Pass: the map is valid and the ring comes back where it was.
2. **Groove.** Groove one row from the ring. Pass: the ring lands on it.
3. **Free node.** A ring with a bisector ending on it, the groove offset at the junction. Pass:
   the junction moves into the groove.
4. **Plates and many-holed regions.** Corners and several seams on a small synthetic mesh.
5. **IMG_4113.** Wall depth, regions, slivers and names against the drawn walls, the settle
   (0.861) and the carved curve fit (0.801 to 0.857), with pictures.

## Risks

- **Size.** The layout's optimizer runs on tens of thousands of triangles; IMG_4113 has 964,000.
  The solve may have to be limited to a band around the walls.
- **The body.** One region with a boundary loop per limb needs many seams.
- **Lengths**, if integers turn out to be required.

## The code written so far

Nothing is removed without your yes. Proposal once step 5 passes: keep `RingNetworkCarve` and
`SurfaceChordTrace` (stage 1's carve); `RingCurveFit`, `RingCurvesNode`, `FittedRingMarksNode`,
the V view and `RingCurveFitTest` would go; the settle is unaffected.
