# Frictions found segmenting IMG_4113 (CRAW-105 worktree)

Status: FIXED (in this worktree, uncommitted), OPEN (not fixed, why).

## Fixed

1. FIXED, seen working. `ixdar-cli drag` reply said nothing about what the tool did, so every
   drawn line needed a second `tools` call. The reply now carries the tool row and error, as a
   click's does (`InjectDrag`).
2. FIXED, seen working. `drag` could only draw a straight line. `--via "x,y;x,y"` passes the
   drag through points on the way (`InjectDrag`).
3. FIXED, seen working. The toolbar was drawn into every `multiview` cell
   (`MultiviewScreenshot`).
4. FIXED, seen working. A drawn line's closure came home beside the line instead of round the
   back whenever the line lay in a deep groove (the telson groove: the "ring" was a 0.003-wide
   sliver, and it had been saved like that). Two changes: the closure's first search may never
   point back along its arrow (`HeadedCreasePath.neverBack`), and it keeps off the vertices
   within 8% of the line's span of the line, clear of its two ends
   (`AuthoredSplineRing.drawnBesideVertexId`, stamped closed in `CreaseRingLoop.lay`). The saved
   ring re-evaluated to a full ring round the tail with no edit.
5. FIXED for new files, not run. A first ring chained on `creases.geometry` made the writer add
   a second `surface_metric`/`surface_creases` pair (`RingDslWriter.wireRingInputs`).
   IMG_4113.dsl still carries its `surface_2`/`creases_2`: the writer does not rewrite them.
6. FIXED, seen working. The save replaced the `.dsl` with mode 600; it now keeps the file's
   mode (`RingDslWriter.writeAtomically`).

16. FIXED, seen working. Drawing mode forced the strokes look. It now opens in the strokes look
    by picking it, so M and `shading curvature` change it while drawing; leaving drawing puts
    the earlier look back only if the strokes look is still the one picked (`StrokeRingTool`).
29. FIXED, seen working. A click left a hover preview ring in the next screenshot. `hover-clear`
    now also moves the cursor off the window, so the preview goes; the user's hover is unchanged
    (`HoverClear`). Run `hover-clear` before a screenshot.
36. NEW, seen working. A drawn line can be a cut between two walls: C in drawing mode switches
    lines between rings and cuts. Each end snaps to the nearest ring or bisector within 120 px;
    with no wall in reach the line is drafted as a ring and the row says why
    (`StrokeRingTool.cuts`, `BisectorTool.draftAlong`).
37. NEW, seen working on a cut across one tail band (answers 25 and 35 in part). L in the
    connection tool takes a ring that separates nothing, puts the picks either side of its
    middle edge with every ring a wall, and shows the way round it (red) plus the neck that
    closes it (green, Enter cuts there). Where the way round has no closed neck (a band cut
    once) Enter drafts a cut across the path instead (38). L again takes the next such ring.
38. NEW, seen working: it split all three tail segments into dorsal and underside (12 cuts,
    4 per segment, no new sliver). In the connection tool, Enter on a path with no closed neck
    drafts a straight cut across the path's narrowest strait between two different walls. It
    keeps a strait only if the cut blocks the path (the picks come apart or the way gets
    longer), trying up to 12 straits, narrowest first. Pick the two places again and repeat
    until "not joined" (`ConnectionTool.confirmNeck`, `BisectorTool.draftAcross`).
    What the tail needed it for: each segment's dorsal joined its underside through the hidden
    folds at the four corners of its side lobes, which no camera view shows.
39. NEW. A drawn cut whose two ends are nearest the same wall now takes another wall in reach
    for one end (`BisectorTool.draftAlong`).
40. OPEN. The strait cut misses a strait that lies between two stretches of one wall, and a
    path with no walls near it. On the head (shield top to mouth) the connection tool found a
    closed neck instead: a flat geodesic loop round the face, not a groove. Undone. The head
    still needs its lower front edge drawn, which the folded claws hide.
41. OPEN. Enter in the connection tool leaves the picks cleared after a strait cut, so the two
    places must be clicked again for the next way round.
42. OPEN. A lobe region reaches up into the fold beside it, so a click or line that looks like
    it is on the dorsal lands on the neighbouring lobe; only the regions look shows it.

## Withdrawn

31. The regions and parts looks (`shading regions`, `shading parts`, G) are the coloured
    overview; it is now in the mesh-segment skill.

## Open

7. A line drawn along part of a lobe's base (one side of a loop that is not a girdle) closes as
   a small loop on the drawn side, not round the lobe. Clicked anchors (5 round the base) work.
   Not fixed: the closure has no way to know which side the part is on.
8. A drag that drafts nothing leaves the row unchanged, so the reply shows the previous ring's
   row and looks like a success.
9. Undo restores the sub-tool: undoing after Esc puts the tool back in drawing mode, and the
   next clicks answer "a click draws nothing".
10. Neighbouring regions often get near-identical colours (two blues on the tail, two greens on
    legs and head), so a split cannot be judged from a screenshot; `rg`-style counts were
    needed every time.
11. Region rows in `ui-state` carry no centroid; `creasePoint` was the only position to tell
    regions apart by.
12. `sel 14 20 24` (spaces) answers "not enough args"; it wants commas.
13. `multiview` draws the open terminal into every cell (the toolbar is now hidden, the
    terminal is not).
14. `save-rings` answers "nothing to save" when it has just written 23 part names.
15. `regions.summary` says "parts: none" after `lb` until the next save or reload.
17. `multiview` with no selection frames the model small (a quarter of each cell).
18. `tools` output is 60 KB on this scene; reading one tool's row means filtering it.
19. Ring numbers ("14") and region numbers ("R2") show together and look alike.
20. Legs hidden with Shift+H do not make the carapace edge behind them reachable in a useful
    way: the leg bases stay with the body, so the edge is still covered. What worked instead: a
    bisector from the cervical ring to the tail joint ring with two anchors in the visible gaps
    of the edge groove; the crease path found the stretches behind the legs by itself.
21. A drag that starts off the mesh orbits the camera and the reply says nothing, so every later
    line lands somewhere else. Re-`frame` before each drag.
22. The strokes look shows only a drawn ring's line, not its closure, so a bad closure is
    invisible until the regions are counted.
23. No way to select or delete a ring by name from automation: a click on a non-separating ring
    drafts a new ring instead. Undo back past it is the only way out.
24. An error line stays on screen after later successes (it is in most screenshots here).
25. The connection tool's "neck" is the narrowest cross-section of the path, not the fusion.
    It found the eye stalk hidden under the left eyeball at once (good), but on the head it
    cut an antennule lobe that was not the leak.
26. A model reload puts the ring tool back in geodesic mode.
27. Bisector click order (end, end, then steering anchors) is not in the row or the toolbar.
    Ends can be clicked from two different camera views, which is what made the uropod and
    carapace bisectors possible; nothing says so.
28. The scan fuses joint folds into tunnels, so a crease path dives under the surface (left palm
    joint).
30. `terminal --line` does not open the terminal but GRAVE toggles it, so "close it" opens it.
32. `ui-state` right after `model --path` returns the old regions for a moment.
33. Crease anchors round the eye: the ring dives through the torn socket surface and crosses
    itself with four or more anchors; three anchors worked on the right eye, none did on the
    left (the neck finder did).
34. A bisector whose end meets its wall at a shallow angle leaves slivers of 3 and 9 faces (left
    uropod), and `collapse-slivers` does not take slivers walled by a ring and a bisector.
35. Head shield against the front underside: three bisectors (cervical ring to each antenna base
    ring, and one between the antenna bases) did not separate anything. The front of the head
    has handles (antennule lobes, eye sockets, the spine under the rostrum). Undone.

## Underside pass (leg pipes at the body)

43. WORKED. A leg pipe's base ring: three anchors on the visible arc of the groove where the
    pipe meets the body (middle first, then the two ends), in a close-up (radius 0.06) in the
    curvature look. One anchor alone wanders round the whole body (0.85 long). Anchors placed
    from the wide view land beside the groove; place them from the close-up.
44. NAMES. The four pipe pairs under the body are the claw's base and walking legs 1 to 3, not
    legs 1 to 4. Walking legs 1 and 2 are now cut at the body on both sides.
45. OPEN. Walking leg 3 (the rear, angled pipe) and the claw's base pipe did not separate: the
    base ring closes but the pipe is still joined to the body behind it, where no view reaches.
    The connection tool finds no closed neck there and only one wall is near, so the strait cut
    has nothing to cut between. Needs a ring round the hidden contact.
46. OPEN. A base ring that runs beside an older ring leaves 2-face slivers; `collapse-slivers`
    fixed them here and dropped the old ring (ring_18) where the new ones replaced it.
47. OPEN. Undo is one step per anchor and reopens a draft at each confirm, so undoing a ring
    means counting steps; there is still no "delete this ring".
48. OPEN. The thorax plates are not split yet (thorax underside is still one part).

## Thorax plates pass

49. WORKED. Thorax underside split into five plates: a transverse bisector in each of the two
    front grooves (ends on the leg base rings, three steering anchors in the groove), the
    connection tool's cut-across for the small gaps round the leg rings, then a midline
    bisector. One 9-face sliver was left between a leg ring and a transverse cut.
50. FIXED. The cut-across failed with "ambiguous nearest vertex" where two vertices coincide;
    it now passes vertex ids instead of snapping positions (`BisectorTool.draftAlong`).
51. OPEN. `control --action confirm-neck` can take longer than the CLI waits; the reply is a
    timeout but the scene finishes the cut. Check `ui-state` before the next step.
52. OPEN. The `bisect` control toggles, so firing it twice leaves bisecting and the next
    clicks draft a closed ring. Read `ringTool.subTool` from `ui-state` first.
53. OPEN. `pick` right after a `terminal --line` in the region tool returned the wrong region
    (the head shield got a plate's name and was saved; fixed by re-labelling). Pick in the
    ring tool, then label by region number.
54. OPEN. The rear plate still holds the rear leg pipes and two more transverse grooves.

## Grow tool pass (thorax redone)

55. NEW, seen working. Grow tool (ctrl+U, `grow-tool`): a click floods the flat surface up to
    the rings and the groove bottoms (green patch); `[` / `]` (`grow-less`, `grow-more`) change
    the groove strength it stops at; Enter (`confirm-grow`) makes the outline that is not yet a
    wall into rings and bisectors (`GrowTool`, `GrownPatch`). The thorax underside was redone
    with it: 22 parts (claw base pipes, 5 plate pairs, the inboard pipes of walking legs 1 to
    3) where there were 5 ragged plates. Groove left inside parts: 3.01% to 2.42%.
56. FIXED. A bisector fitted to a long curved outline with 6 anchors cut corners; grown
    outlines take one steering anchor per 16 edges (`BisectorTool.draftAlong` takes the count).
57. FIXED. A strip of groove left between the patch and an older wall became its own region;
    a closed-in pocket that is mostly crease now joins the patch (`GrownPatch.grow`).
58. FOUND. A bisector is deleted by re-opening it (click it) and `delete-bisector-point` until
    the row says the ring is deleted. Answers 23 and 47 for bisectors.
59. OPEN. Midlines of two plate rows and the rear legs against their bases have no groove the
    patch stops at, at any strength; they were cut with a drawn cut and the connection tool.
60. OPEN. A bisector's second end click was refused ("no ring or bisector within 40 px") where
    the wall sits in a fold behind a knob; a drawn cut (120 px reach) took the same ends.
61. OPEN. The groove strength stays where the last part left it, so the next click can run
    over its neighbours; the reply's patch size is the tell.
62. OPEN. Grown cuts left three new slivers (9, 11, 17 faces) where a cut meets a wall at a
    shallow angle, and one 262-face strip by the right leg 2 base; unnamed.
63. OPEN. After `confirm-grow` the surface stays in the dark look until the look is picked
    again.

## Head underside and outer legs pass

64. WORKED. Head underside with the grow tool at groove strength 0.30: the front plate with
    the antennule bases (3 closed rings), then the head shield itself, whose outline against
    the mouth field came out as 6 bisectors. Answers 35 and 40: the head shield is now cut from
    the front underside, the mouthparts and the rostrum. Groove left inside: 2.42% to 1.79%.
65. WORKED in part. The fused outer leg sticks split at their pinches with the grow tool (a
    short closed ring each); one cut separated nothing until `find-leak` + Enter closed it.
66. OPEN. A click ring on a fused stick of two legs lying side by side runs lengthwise (0.23
    long) or rings a nub; undone. Which leg each outer stick belongs to cannot be told from
    the scan, so they are named `walking_legs_*_outer_N`.
67. OPEN. `sel none` prints every part name as an error and the terminal then covers the
    lower third of each screenshot.

## Settle pass (settle_rings node, toggle-settle)

68. DONE. One sparse solve settles every wall: `RingSettle`, the `settle_rings` node and the
    scene's `toggle-settle` (Y). IMG_4113: 96 -> 89 regions, 6 -> 0 slivers, 14 -> 7 unnamed
    regions, every name kept; walls 15.17 -> 14.33 long, mean groove depth on the walls
    0.738 -> 0.861; 2.1 s.
69. OPEN. The settled walls are raw face boundaries: finer teeth than a fitted ring, and where
    two grooves run side by side a wall hops from one to the other.
70. OPEN. The ring scene misreads a file that holds a `settle_rings` statement (91 regions,
    ring_67 and ring_69 separate nothing): the scene adopts the settled marks as the rings.
    The settled walls are not written back into the rings, so a save keeps the drawn ones.
71. OPEN. A wall moved across a label point takes the name with it; the solve pins each label
    point and the faces joining it to its region's middle, which can leave a thread.
72. OPEN. 122 boundary stretches end up under another ring's label so that the walls close:
    ring labels after a settle no longer say which ring a wall came from.
73. DONE. `settle_rings` rebuilt as a compiled node group like `quad_layout`: `ring_membership`
    (assembly, a `DofSystem` on its `dofs` port), the existing `newton_solver` (relax) and
    `settled_ring_marks` (extraction). Same numbers as item 68; stage times on IMG_4113 1.2 s,
    2.2 s and 0.5 s. The group is desktop-only because `newton_solver` is.
74. DONE. `fit_rings`, the curve-fitting version, as a group like `quad_layout`: `ring_curves`
    (assembly: walls cut into curves at the vertices walls share, one offset per curve point
    across its curve, a `DofSystem` whose solve is `NewtonRelaxation`), `newton_solver`,
    `fitted_ring_marks` (extraction). Scene toggle `toggle-fit` (V). IMG_4113: 118 rings as 227
    curves of 11314 points, 2686 moved, 89 iterations, 0.5 s; walls' mean groove depth 0.739 ->
    0.804 (the settle reaches 0.861); all 77 names keep their regions; regions 96 -> 100,
    slivers 6 -> 9, unnamed 14 -> 18.
75. OPEN. The curve fit only finds the groove nearest each point (three quarters of the points
    do not move), its walls are toothy where points round to vertices, and where two rings meet
    it leaves a few regions of 1 to 56 faces. A bisector across the left claw's palm that leaked
    as drawn closes after the fit and splits the palm (13718 faces unnamed).
76. TRIED, KEPT IN. Coarse-to-fine for the curve fit (groove profiles blurred 4, 2, 1 edges,
    then sharp): no change on IMG_4113 (0.804, 2709 points moved against 2686). The curves are
    not stuck short of far grooves; the drawn walls are already within about a third of an edge
    of their nearest groove on average. What limits the fit is the smoothness weight: at 0.1 the
    depth is 0.838 (names kept, slivers 12, walls 16.77 long), at pull 4 and 0.1 it is 0.857
    (three named regions lost, slivers 17, walls 17.33). More motion means toothier walls.
77. TRIED, REMOVED (with the user's yes). Joining every fourth curve point instead of every one
    (straight or along the creases) shortens the walls (14.9 to 15.6) but ten named regions lose
    their names.
78. DONE. `fitted_ring_marks` no longer rounds the fitted curves to mesh edges: `RingNetworkCarve`
    carves them into a working copy of the surface in the quad layout's embedding types
    (`EmbeddedMeshTopology`, `ArcNetwork`: a node where walls meet, an arc per curve, loops cut in
    two), splitting every edge a curve crosses, and the node outputs that copy, its marks and the
    network (`tmesh`). The quad layout's own `SnappingCarve` was not usable: it snaps arcs to
    existing vertices. IMG_4113, 0.4 s, about 10,800 vertices added:
    - default (pull 1, smoothness 1): walls 15.74 long at depth 0.801 (edge-rounded 16.07 at
      0.804, drawn 15.38 at 0.739); regions 96 -> 96, slivers 6 -> 6, every name kept.
    - smoothness 0.1: 16.31 at 0.836; regions 97, slivers 7, every name kept.
    - pull 4, smoothness 0.1: 16.97 at 0.857 (the settle: 0.861); regions 100, slivers 9, every
      name kept (edge-rounded at these weights lost three names and made 17 slivers), but the
      walls zig-zag in wide grooves.
    Pictures: `tmp/craw-105-carve-{close,thorax}-{drawn,default,strong}.png`.
79. OPEN. The carve's straight lines over the surface are plane cuts, which lose their way on
    folded scan surface (17 of 11,314 points at the default, 48 at the strong weights); those
    points are joined along mesh edges instead, as are steps through a face another wall already
    cut (168 and 478). Points that did not move still sit on vertices, so most of a wall still
    runs along mesh edges.
80. OPEN. The ring scene cannot show the carved walls: its V view is still the edge-rounded fit
    on the drawn surface, and opened on a file with a `fit_rings` statement it re-traces the
    drawn rings on the carved copy. The mesh viewer shows the carved marks as lines. Three
    `fit_rings` statements in one file ran the scene out of heap (a mask per ring per stage).
