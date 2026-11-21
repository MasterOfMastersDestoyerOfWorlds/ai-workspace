# Ring fit: approaches that have failed

The approaches tried for fitting rings and bisectors into a surface's grooves, and why each one
failed. LLM sessions keep proposing the same few ideas under new names. Before proposing an
approach, find it here under any of its names. If it is here, say which entry it is and what is
new about it, or don't propose it.

Sources:
- the craw-106 conversation of 2026-11-12/13 (ring anchor fit);
- the craw-112 conversation of 2026-11-14/15 (RegionClusterFit);
- the craw-112-fable conversation of 2026-11-15 to 20 (air flow, F16 to F19);
- `ring_fit_energy_plan.md`;
- tickets CRAW-106, CRAW-107 and CRAW-112.

Test counts refer to the suite of that time: the 11 to 15 `ring_fit_*` fixtures in craw-106, the
18-case `RingFitBench` in craw-112, and the 19-case bench in craw-112-fable. From 2026-11-20 a
count written "10 / 9" is by the drawn anchors, then over the whole ring (see "Bench defects").
Earlier counts are by anchors only and overstate.

## What the user requires

Every failure below breaks at least one of these. They are the user's words, condensed.

1. **Global.** A ring must reach a groove from anywhere, including flat surface. For example, a
   ring in the middle of a smooth cylinder with a groove at each cap must end in one of them. Most
   of a real mesh is flat.
2. **No tuned constants.** No weights, thresholds or softness to tune. "Tuning is not an option."
3. **No groove objects.** The surface enters only through a field, and the answer comes from one
   global solve of the energy, not from bookkeeping about which groove is whose.
4. **The artist's intent.** Rings are usually drawn close to their grooves and only need nudging
   in.
5. **Partial rings.** A correct ring is often part over a groove and part over flat surface.
6. **Branching grooves.** Rivers, veins and trees, with no closed loops, must work.
7. **One ring per groove.** With one groove and two rings, one ring takes it and the other stands
   opposite (fixture `one_groove_two_rings`). With grooves at 0° and 60° and rings at 30° and
   200°, there is one ring in each groove (`two_grooves_one_ring_nearest_both`).
8. **Bisectors.** Bisectors move into their grooves too, their ends sliding along the rings they
   end on.
9. **Trenches.** A slanted ring with trenches joining its two grooves turns so it steps through
   the trenches (`slanted_ring_trenches`).
10. **Fixtures first.** Solve the simple fixtures before the crawfish scans.

## Common failure cases

The user's three are the first three. Each entry below lists the cases it falls into.

- **C1. Constants covering a gap in understanding.** A weight, threshold, softness or reach is
  tuned until the fixtures pass, standing in for a part of the problem that was never worked out.
  Entries: F1, F2, F3, F4, F5, F7, F9, F11 (a bound acting as a hidden weight), F12, F13.
- **C2. A ring tied to a particular groove or piece of geometry.** A ring is assigned, matched,
  tethered or given ownership of a groove, a loop or a vertex set, instead of the arrangement
  following from one energy over the surface. Entries: F1, F2, F3, F4, F5, F6, F7, F8, F12.
- **C3. Separate state per ring or region.** A field, assignment or centroid kept for each ring
  or region, plus rules for how those states interact. Entries: F1, F3, F4, F5, F7, F8, F9, F11,
  F12, F13.
- **C4. An energy with no slope away from the grooves.** Away from a groove the energy is flat,
  so a ring on flat surface feels no pull, against the "global" requirement. Entries: F2, F6,
  F11.
- **C5. A stepper that cannot reach the nearby fit.** The energy is right near the drawn ring,
  but the moves cannot get there. Examples: rings that only translate (F10), anchors that stop two
  or three cross-sections short (F7), a bisector that stalls 18° out (F12).
- **C6. A ratio that forgets amounts.** Each side of a ring is judged by a fraction of its own
  total, such as how much of its air a groove keeps back, and the two fractions are compared.
  They share no scale, so a side with a trickle that nothing blocks beats a side with 25 times
  the air that loses a quarter of it. The user: "that could be arbitrary". Entries: F17, and
  F18 in its fraction-first form.
- **C7. A crease that only slows.** Whatever makes a crease costly without stopping anything
  leaves the ring to settle where it would with no crease at all. Entries: F9, F18.

C1 also covers F16, F17 and F19: the 0.5 crease strength that decides what is a wall, and the
scale a crease value is divided by.

Starting from the drawn position is not a failure case. The drawn rings carry the artist's or
agent's semantic intent, and the fit improves them. That leaves an open question about the two
fixtures that ask a ring to travel far past a nearer arrangement: the far ring in the 0°/60° case
and the trench case. They may conflict with that intent.

A simpler test for the same question, proposed by the user on 2026-11-15 and not built yet: one
ring already lies in its groove. A second ring is slanted toward its own groove and lies partly in
the first ring's groove. The second ring should move toward its own groove.

## The user's picture: balloons in a bouncy castle

This is the user's intuition for the fit, in the user's words as far as possible. It is not an
approach that has been tried, and nothing above has captured it.

- **A bouncy castle.** Each region is a balloon in a bouncy castle. Each balloon pushes on the
  rings, which are the sewn seams of the castle, until they are taut.
- **A balloon in a glass tube.** The glass tube is the mesh, with a balloon inside. Think about
  how the balloon fills the inside of the glass. The balloon has a hard time getting across the
  tight spaces of the glass, which are the grooves of the mesh, and an easy time where the glass
  keeps a constant width.
- **Soft robots.** Videos of soft robots online use the same principle: inflated chambers pressing
  against each other and against their walls.

**Refined by the user (2026-11-15):** volume is probably the wrong way to talk about it. Each
region's piece of the surface is such a balloon, and a balloon can only spread out in 2D, within
the surface. The tube-narrowing reading below only makes sense on simple meshes.

Under that refinement, as the assistant reads it:

- **Pressure is area.** A region's membrane pushes on its seams while it is crowded. On flat
  surface a seam moves away from the crowded region toward the roomier one, so the pull is global
  and comes from the arrangement, not from any groove.
- **A groove is a barrier, not an attractor.** A membrane spreads easily over smooth surface and
  with difficulty across a crease. A seam pushed across the surface stops where the membrane
  behind it cannot easily follow, which is a groove.
- **Taut seams.** Tension in the seam straightens it between the places where it is held.
- **What is still missing.** A law for how hard a crease is to spread across, one that is not a
  picked crossing weight. F9's crossing-weighted face distances were that idea with a constant.

**What makes a groove hard to cross (the user, 2026-11-15):** "if we have the groove bottoms, a
balloon would pop if it crossed one." A groove bottom is a wall, not a cost: no region may spread
across one. It is a hard rule, so there is no weight to pick. As the assistant reads it:

- **How seams move.** The competition between the regions (e-means) pushes the seams.
- **Where they stop.** A seam pushed onto a groove bottom stops there, because going on would
  mean the region behind it crossing the bottom. That works from either side.
- **Open: an empty groove.** If a groove lies inside a region with no ring near it, does it pop
  that region? If the wall only stops regions from growing across it, a groove inside a region
  as drawn is allowed.
- **Open: what brings a seam to the bottom.** If the pressures already balance before a seam
  reaches a groove, the wall never comes into play.
- **Open: which groove bottoms.** It needs the groove bottoms themselves, and finding them is
  where F5 and F7 met thresholds and pock marks.

**Pock marks without a threshold (open, 2026-11-15).** In the fixtures it is clear where the
groove bottoms are. On the crawfish scans, every earlier attempt needed a strength threshold to
keep pock marks out. Ideas so far:

- **The user's: walls matched to the rings.** Treat the groove maxima as continuous walls, and
  take roughly as many as there are rings. The count would come from the drawing rather than
  being picked, but it is still a selection rule. Rings and walls do not pair one to one
  (partial rings, empty grooves, bisectors, trees). A ranking by depth or persistence would put a
  deep pit above a shallow groove.
- **The assistant's: a wall stops only what cannot go round it.** Every valley maximum is a wall,
  with no depth cut-off. A region may never step across a wall edge, but it may spread round one.
  - A pit is a point, so a seam that meets it flows round it.
  - A groove that closes a loop cannot be gone round, so it stops a seam completely.
  - A groove that ends holds only the stretch of seam lying along it, and the seam bends round
    its ends. That is the partly-in-a-groove ring.

  Risks: how far a seam goes round a long, open groove depends on the regions' push against the
  seam's tautness, which may bring back a ratio between the two (C1). F11 failed because grooves
  can be walked round, though there it was a distance and here it is a rule about moves.
- **A fixture first.** A grooved torus pitted with pock marks of several depths and widths,
  including some deeper than the groove. It is a unit test, so whatever rule is chosen can be
  judged on it before the crawfish.
- **The fixture exists (2026-11-20):** `one_groove_pock_marks`, the one-groove torus with eight
  pits, six of them pressed deeper than the groove, four between the ring and the groove and
  one beside the groove. It is the bench's 20th case. Measured on it, with F19's crease values:
  - The groove reads 1.00 and all 40 of its centre-line vertices are walls. The pits read 0.28
    to 0.76: the groove is narrow and sharp, the pits are wide, so pressing a pit deeper does not
    make it read higher.
  - Four of the eight pits still get walls (13 vertices at 0.5 or more, 37 after closing). Three
    of the other four read 0.47 to 0.49, just under the threshold.
  - F16 and F17 fail it: the ring reaches the groove except for a stretch hooked on the wall of
    the pit beside the groove, 18° off. With every centre-line vertex a wall the ring does not
    move at all.
  - F18 (graded, amount times fraction) passes it exactly, anchors and whole ring. It is the
    only version that does.
  - Correction, same day: 1.00 is the groove's largest value. Along its centre line it reads
    0.501 to 1.000, mean 0.735. Its wall is whole only because its weakest point clears 0.5 by
    0.001.

**Built and measured (2026-11-15 to 20).** The picture was built as air flow: F16 with walls,
F18 without. These are the assistant's measurements, not the user's words. What they say about
the open questions above:

- **What brings a seam to the bottom.** A wall cuts off the air beyond it, so the side of a seam
  facing a wall has less air pressing on it, and the seam moves that way. On the smooth-rings
  bisector as drawn, 0.0059 arrives from the groove's side against 0.0090 from the other. With
  no wall, nothing brings it (F18).
- **What keeps it there.** Only the rule that a seam lying along a wall does not move. The
  forces on it still point away: on the horn, every point of the ring that is not on a wall is
  pushed out onto the sphere.
- **Pressure is area.** This part works as written, and it is what moves every ring: the smaller
  side pushes harder, so a ring goes where the areas on its two sides balance. On a torus that
  is the inside of the tube. On the horn it is far out on the sphere. Grooves only matter where
  a wall resists that.
- **Which groove bottoms.** Still a threshold (F16), and it is fragile.

**Proposed by the user (2026-11-20), not built into the fit yet:** "could we scale an individual
particle's influence on the ring by its total travel distance? that way air that takes longer
routes around an object is not as impactful?" It answers C7: slowed air would count for less,
and air that never arrives counts for nothing, so a graded crease runs smoothly into a wall.

A rough first measurement, the assistant's. It divides the air arriving at each spot of a ring
by the mean time that air took, which is not yet each particle's own time. Bench test
`theAirReachingEachRingAndHowLongItTookWithCreasesAndWithoutIsWrittenToTmp`, with F19's crease
values:

| Ring as it stands | Air over time, no creases | With graded creases | Ring would move |
|---|---|---|---|
| pock marks as drawn, groove side / far side | 1.49 / 1.51 | 1.24 / 1.33 | toward the groove |
| smooth-rings bisector as drawn, groove side / far side | 7.94 / 7.03 | 0.02 / 0.18 | toward the groove |
| horn as drawn, foot side / tip side | 2.11 / 6.36 | 1.54 / 6.29 | toward the foot |
| horn at the foot (pass 5), sphere side / cone side | 4.00 / 7.37 | 3.44 / 4.52 | off onto the sphere |

- Graded creases change how much air arrives by 0 to 7%, and by 36% where a crease reads one.
  They change how long it takes by 11 to 68% on the pock marks and the horn.
- On the smooth-rings torus the times grow 10 to 300 times over. Not traced. A little very late
  air raises a mean a great deal, so the mean understates what a rule per particle would give.
- With no creases the smaller side already pushes harder (the cone, 7.37 against 4.00), with no
  division by the region's area.
- Open: how fast a particle's influence falls with its distance, and how to get each particle's
  own time rather than a mean.

The first reading, from before the refinement. This part is the assistant's reading, not the
user's, so check it against the picture:

- **Where the seam settles.** Balloons meet where the wall between them is cheapest to hold. On a
  tube, that is where the tube is narrowest, so a seam ends up in a pinch without being assigned
  to it. That avoids C2.
- **Why the other ring stands opposite.** The balloons press on each other until the pressures
  balance. With one groove and two rings, the seam without a pinch is pushed to wherever the two
  balloons it separates balance, which is opposite. This is the region balance that F13 tried to
  add as a second term; here it comes from the same physics.
- **Global, with no flat places.** A balloon pushes everywhere, flat glass included, which is the
  "global" requirement. That avoids C4.
- **Starting from the drawn rings.** Inflation starts from the seams as drawn and keeps their
  order, which is the semantic intent.
- **Open: grooves that are not pinches.** A groove running along a tube, like the bisector
  fixtures' outer groove, does not narrow the tube. It is unclear what holds a seam in it.
- **Open: pressure as per-region state.** Each balloon's pressure or volume would be state per
  region (C3). The question is whether it can follow from one quantity of the whole arrangement
  instead.

## Failed approaches

### F1. Thresholded coverage energy

Also called: "every vertex pays its distance to the nearest ring", k-median coverage, the original
`RingAnchorFit` energy.

- **What:** every vertex pays √(edge-Dijkstra distance to the nearest ring). Groove vertices over
  the crease threshold weigh 1000×. Length costs 100 per mean edge, and is checked only when a
  move is accepted.
- **Where:** craw-105, moved to craw-106 as the baseline. 8 of 11 tests passed.
- **Why it failed:**
  - The threshold makes the energy blocky.
  - Edge distance and the square-root cusp make accepting or rejecting a move depend on the
    tessellation.
  - Its constants depend on mesh density.
  - Length can veto a move but never propose one.
  - The hard nearest-ring choice hides a second empty groove from every other ring (see F8).

### F2. Line integral along the ring

Also called: geodesic active contour, snake, "cost per unit length along the ring", ∫g ds plus a
bend term plus a tether to the drawn position.

- **What:** a ring is cheap where it runs along a groove bottom, plus a bend price, a small
  coverage term and a tether to where it was drawn.
- **Where:** proposed in craw-106 and never built. Its older relative, `RingCurveFit` (rings
  slide sideways into the deepest nearby groove), was archived under CRAW-107.
- **Why it failed:** it pulls only within a groove's own width, so it is not global (requirement
  1). The user ruled it out: "the energy needs to be global".

### F3. Occupied-groove discount

Also called: g_i, "a groove next to another ring counts as smooth", the occupied-groove factor.

- **What:** a groove point's value to ring i is scaled down by its nearness to any other ring.
- **Where:** proposed in craw-106 and superseded by F4 before it was built.
- **Why it failed:** it is groove bookkeeping (requirement 3), it needs a reach R, and it is the
  same idea as F8 and F12.

### F4. Smooth coverage energy

Also called: the soft-minimum energy, "heat distance from the rings", the plan's "planned energy".

- **What:** every point pays φ(heat distance to the nearest ring), using a soft minimum over the
  rings with softness τ and a groove weight continuous in valley curvature. Each ring pays its own
  length and bend, cheaper where it runs in a groove. Anchors could also slide along the ring in a
  refinement step.
- **Where:** built in craw-106. 9 of 11, then 9 of 15 with the new fixtures.
- **Why it failed:**
  - It has five picked numbers: groove weight 1000, power 0.5, length price 0.1, bend price
    1e-4, cost smoothing 0.
  - In the 0°/60° case the far ring never comes round. A soft minimum over one edge is nearly
    hard, and widening it means τ ≈ the ring spacing, a picked number.
  - The slanted ring stays split.
  - The trenches are ignored.
  - A bisector end stays two tube sides off, because the ring it stands on already covers the
    groove there.
  - A crease-mode ring grows a tongue.
- **General lesson** (from the plan): any finite ratio between two aims has a geometry where the
  weaker aim wins, and descent only reaches what is downhill from the drawn position. The user's
  verdict: "these are not useful questions … tuning is not an option".

### F5. Ordered aims with a valley-line graph and matching

Also called: lexicographic aims, "a ring lies along a valley line", groove bottoms by comparison,
"valley-line network", "minimum-cost matching of rings to loops", "nearest free loop".

- **What:** the aims come in strict order:
  1. the share of the ring off valley lines;
  2. the nearest free groove;
  3. the loop that covers most;
  4. even coverage.

  Valley lines are vertices whose valley curvature beats their neighbours'. They form a graph,
  and its loops are matched to the rings.
- **Where:** written into `ring_fit_energy_plan.md` (2026-11-13) and never built. The user says
  valley lines have also failed elsewhere.
- **Why it failed:**
  - Pock marks pass the comparison. Without the strength gate it is the old groove-bottom test
    with its thresholds removed, and with the gate it has a threshold again.
  - Rivers and trees have no loops to match (requirement 6).
  - A partial ring is not a loop (requirement 5).
  - On a plain torus, the valley line along the inside of the tube joins every groove into one
    network.
  - "Leftover rings placed evenly" conflicts with the artist's intent.

### F6. Local nudge uphill in valley curvature

Also called: "slide down the flank", ∂γ/∂t = (∇κ_v·n)n, "a stretch on flat surface stays as
drawn", plus the exception "a ring touching no groove moves whole to the nearest free groove".

- **What:** each ring point slides across the ring toward higher valley curvature. A global
  matching moves only the rings that touch no groove slope.
- **Where:** proposed in craw-106 and never built.
- **Why it failed:** most of a mesh is flat, so most rings would never move (requirement 1). The
  exception patches that and "seems so likely to break". The user: "on any mesh with real
  geometry your scheme would fail".

### F7. Distance-to-groove field with taken grooves

Also called: U(x), "the ring lowers the mean of the distance to the nearest groove", "a taken
groove stops being a heat source", `RingAnchorFit.drawing()`.

- **What:** a heat-method distance from the grooves (full-strength groove bottoms). Each ring
  lowers its mean distance along itself. A groove held by most of a ring's points is dropped from
  the other rings' fields.
- **Where:** built in craw-106, with all five picked numbers removed. 3 of 15 tests passed.
- **Why it failed:**
  - The "taken" rule fires only after a ring has arrived, so two rings pulled at once both reach
    the one groove.
  - The second ring's field is then empty: zero energy, no pull, stacked.
  - Using full strength as the source is a threshold. It hid the bisector fixtures' groove
    entirely.
  - Anchors stopped two or three cross-sections short.
  - The tree's branches did not show as separate wells.

### F8. Nearest-ring assignment of grooves, up front

Also called: "decide which ring gets which groove by nearness first", "each groove vertex goes to
the nearest ring", the hard nearest-ring choice.

- **What:** assign groove points to the nearest ring before descending, then each ring follows
  only its own groove points.
- **Where:** proposed at the end of craw-106, and again in craw-112 on 2026-11-15. It is what F1's
  and F4's nearest-ring distance already does.
- **Why it failed:**
  - It is F7's exclusion decided earlier, at a different unit (vertex rather than groove).
  - A ring nearest two empty grooves takes both, so the far ring gets none and the 0°/60° case
    fails.
  - Fixing that needs a matching with capacity (F5) or a soft minimum with τ (F4).

### F9. Region clustering with weights

Also called: RegionClusterFit, e-means balance plus groove pull, "regions as clusters, rings as
their borders", crossing weight.

- **What:** the rings' regions are e-means clusters. Face distances to region centroids are
  stretched by 1 + crossingWeight × groove strength. A ring moves when the region balance plus
  pullWeight × Σ length × grooveDistance drops. Moves are strips, local runs of vertices, or a
  geodesic Voronoi split of the two regions. Bisectors slide their ends, and rings drag the
  bisector ends that touch them.
- **Where:** craw-112, committed as ace44272. 13 of 18 with crossing weight 1e5, 12 of 18 with
  100.
- **Why it failed:** it has picked numbers (crossingWeight, pullWeight, lengthWeight, batch size,
  alpha0, the still-pass count), which the user rejected as "constants we are tuning". These
  cases fail:
  - one_groove_two_rings;
  - two_grooves_one_ring_nearest_both;
  - slanted_ring_trenches;
  - tree_partly_in_groove;
  - horn_ring_on_horn;
  - one_groove_pock_marks (added 2026-11-15): the ring stops 72° out, in the pit at 72°, which is
    deeper than the groove.
  - sphere_half_meridian_two_rings (added 2026-11-15): after 50 passes both rings are within
    about 5° of the great circle. They cannot merge, because touching another ring is refused,
    so the band never dissolves. There were 2.1 million refusals, all "touches ring_00", and the
    run never reaches its still passes, so the bench times out.

### F10. Whole-strip moves

Also called: "step a face strip at a time".

- **What:** a ring moves by sweeping every face on one side of its loop.
- **Where:** in craw-112, before the local-run moves.
- **Why it failed:** rings keep their drawn shape, because a ring can only translate, so a ring
  partly in a groove cannot bend into it. Replaced by local runs of any length.

### F11. Ordinal clustering

Also called: lexicographic distance, "groove crossing counted before length", `ordinal` mode,
off-groove share.

- **What:** face distances compare groove crossings first and length second, using units of the
  summed dual edge length. Rings minimise the share of their length off the groove, with length
  as the tie-break.
- **Where:** craw-112. 5 of 18.
- **Why it failed:**
  - The off-groove share is flat away from grooves, so there is no pull (requirement 1).
  - On a torus a groove can be walked round, so crossing first tells nothing apart.

### F12. Heat descent with taken-groove exclusion, inside region clustering

Also called: per-ring heat field, "release heat only in grooves no other ring has taken", "a
ring takes a groove when more than half its edges lie in it".

- **What:** F11 with the off-groove share replaced by the line integral of each ring's own heat
  field, Σ length × height, with length as the tie-break. Each ring's field leaves out the grooves
  other rings hold.
- **Where:** craw-112, 2026-11-15, uncommitted. 13 of 18. It passes tree_partly_in_groove and
  horn_ring_on_horn, which F9 fails.
- **Why it failed:**
  - It is F7's ownership again, which the user called "a problem".
  - It fires late, so competing rings still fail.
  - Grooves that cross count as one, so one ring takes the whole network.
  - Bisectors stall 18° from their groove.
  - slanted_ring_trenches still fails.
  - one_groove_pock_marks fails: the ring stops 74° out, by the pits nearest where it was drawn.
  - sphere_half_meridian_two_rings fails as F9 does: the rings press together near the great
    circle (worst 5.9°) and cannot merge.

### F13. Combining a groove field with region balance

Also called: "field plus balance", "the field places grooved rings, the balance places the rest".

- **What:** use F12's shared field for "lie in a groove" and the e-means balance for "the other
  ring stands opposite".
- **Where:** discussed in craw-112 on 2026-11-15 and not built.
- **Why it fails:**
  - A weighted sum has a constant, and the two terms are in different units.
  - Field first leaves the second ring parked against the first.
  - Balance first never enters a groove.
  - This is F4's general lesson again.

### F14. Coincident rings and dying regions

Also called: "let rings merge", "a dead cluster", "revive an empty region", "closing move", "the
shared seam carries both rings".

- **What:** F9 with these changes:
  - Each ring keeps the two regions it was drawn between (`regionsBeside`).
  - A ring may lie on the whole of another ring, so a region may become empty.
  - A closing move empties a region in one step, when the balance says so.
  - An empty region regrows only when one of its rings steps off the ring it lies on. The
    Voronoi split refuses an empty side, because its centroid is stale.
  - When two rings lie on one loop with the empty region between them, a move into either
    ring's far region carries both rings: the shared seam moves.
- **Where:** craw-112, 2026-11-15, uncommitted. Weighted 14 of 20, ordinal 13 of 20. No case
  that passed before fails now.
- **What it fixed:** sphere_half_meridian_two_rings passes when weighted:
  - In pass 1 the band closes and ring_00 lands on ring_01.
  - The shared seam then walks both rings to the great circle, and the hemispheres balance at
    10240 / 10240 faces (worst 2.2°).
  - The run takes 0.7 s (F9 hung on this case).
- **What still fails:**
  - The weighted sphere seam never settles: it jitters one face row on the smooth half for all
    400 passes, from mini-batch noise.
  - The ordinal sphere fit stops 6.8° off.
  - one_groove_two_rings now kills a region. Both rings end on one loop, with regions [12800, 0]:
    after 67 passes when weighted, after 2 when ordinal. The case expects one ring in the groove
    and the other opposite.
  - **Measured cause:** a region's centroid face is the face nearest the R³ mean of its faces.
    For a band or a tube segment that mean is off the surface, so its nearest face can lie in a
    groove (the sphere band's did). From a groove face every face looks far under the stretched
    distance, so emptying the region looks like a gain. Faces are assigned in the surface metric,
    but the centroid is taken in R³: the two metrics disagree (failure case C1).
  - An empty region's centroid face is stale, so a revival is scored against where the region
    used to be.

### F15. Centroids in the surface metric

Also called: geodesic medoid, Fréchet or Karcher mean on the surface, "centroid and assignment
in one metric", k-medoids.

- **What:** F14, but each region's centroid face descends to the face minimising the region's
  area-weighted squared stretched distance, instead of being the face nearest the R³ mean (which
  is used only at the first pass). Each step reads the shortest-path tree already built from the
  centroid:
  - inside a face m's subtree, d(m, f) = d(c, f) − d(c, m) exactly;
  - elsewhere, d(m, f) ≤ d(c, f) + d(c, m);
  - so any face where d_m · (d_m·area + 2·moment − 4·subtree moment) < 0 strictly lowers the
    sum. The step has no constant.

  The mini-batch R³ centroids no longer steer anything after the first pass.
- **Where:** craw-112, 2026-11-15, uncommitted. Weighted 13 of 20, ordinal 13 of 20. The bench
  takes 7 s instead of 30 s, because the fit settles once the batch noise is gone.
- **What it fixed:**
  - one_groove_two_rings, weighted, no longer kills a region. ring_00 lands exactly in the
    groove. ring_01's loop lands opposite, at 176.6° ± 10.2° round the torus, the nearest this
    case has come. It still fails the 9° band.
  - The weighted sphere settles in 48 passes instead of jittering.
- **What still fails:**
  - The weighted sphere now misses by half a degree (4.5° against 3.96°).
  - two_grooves_one_ring_nearest_both, weighted, now kills a region: both rings end on one loop
    at −144°.
  - Ordinal mode still kills a region in both torus cases, and its sphere got worse (21°). Its
    distance counts groove crossings before length, so squaring it lets crossings swamp
    everything: the mean of a lexicographic distance means nothing (failure case C1, and F11).
  - **Measured cause of the remaining deaths:** a region with a groove inside it, rather than at
    its border, sees the faces beyond the groove as a full crossing from its centroid. The
    neighbour reaches them the other way round without crossing, so handing over the whole
    region looks like a gain. The partial hand-over, a Voronoi split, is refused because it
    would move faces beside the other ring. That leaves all or nothing.
- **Bench defect found:** `fitted()` snaps each drawn anchor to the loop vertex nearest it in R³.
  When a ring travels far, its anchors collapse onto a few vertices, the re-trace fails, and the
  ring keeps its drawn spline. The bench then scores it where it was drawn: one_groove_two_rings
  reports ring_01 101.25° off, which is its drawn angle, while its loop is at 176.6°.

### F16. Air flow with groove walls, compared by amounts

Also called: air flow, lifetime fit, random walkers, Poisson lifetime, pressure of a region, the
bouncy castle built, groove walls, closed walls, the hold or pin rule.

- **What:** air rises evenly over the surface and leaves at the rings. A groove's centre line is
  a wall air cannot cross. Each side of a ring pushes with the air arriving there over its
  region's area, so the smaller side pushes harder. A ring moves into the weaker side, one
  stretch a pass. A ring lying along a wall does not move.
- **How a wall is picked:**
  1. a vertex is on a groove's centre line when its valley curvature beats both neighbours
     across the groove, at any strength;
  2. it is a wall when its crease strength is also at least 0.5;
  3. from every wall vertex the wall runs on through neighbouring centre-line vertices of any
     strength.
- **Where:** craw-112-fable, 2026-11-15, uncommitted. 11 to 12 of 18. On the code of 2026-11-20,
  with F19's crease values: 13 / 12.
- **Why it failed:**
  - On 2026-11-15 it failed the far ring of the 0°/60° case, the trenches, the tree, the wide
    horn ring and the bisector whose rings are drawn off their grooves. On 2026-11-20 it fails
    the smooth-rings bisector (54°), the 0°/60° far ring, the trenches, the tree, both horn
    rings and the half-grooves ring.
  - The threshold cannot simply be dropped. With every centre-line vertex a wall, at any
    strength, it scores 1 / 0, and 0 / 0 with F17 on top: the one-groove rings end 72° to 180°
    off. Ripples in the mesh pass the centre-line test, as pock marks do.
  - The 0.5 is a threshold (C1). On the horn one vertex at 0.503 makes a stray wall two edges out
    on the flat sphere, and the closing step adds three more at 0.32 to 0.40. A rounding change
    in master moved that vertex across 0.5 and moved the wide horn result from 0.34 to 0.16. The
    smooth-rings bisector's groove is a wall only because its bottom reads 0.54.
  - The wall has gaps. The horn's foot has 168 mesh points and the wall covers 143. Every point
    in a gap is pushed out, each bulge frees the pinned points beside it, and the ring peels off:
    143 pinned at pass 5, 96 by pass 36.
  - Without the 0.5 (every centre-line vertex a wall) it scored 8 of 18 on 2026-11-15.
  - Air rising at each region's centre instead of evenly scored 8 of 18.

### F17. A side's fraction of its own air decides before its amount

Also called: wall share, starved side, bottleneck, fair shares, direct routes, variant A,
variant B, crowding, delay, throttle, pockets, pooled pocket, lexicographic shares, fraction
first.

- **What:** F16, plus a fraction for each side of a ring: the air that reaches it with the
  walls in place over the air that would reach it with no walls. If the two fractions differ at
  all, the ring moves into the side with the smaller one. Amounts decide only on an exact tie.
- **Where:** craw-112-fable, 2026-11-17 to 20, uncommitted. Nineteen cases, by anchors:

  | How the fraction is worked out | Score |
  |---|---|
  | most air that can reach each free stretch of the ring | 16 |
  | each face's air by its shortest way round the walls | 11 |
  | the same, against the region's average ("A") | 7 |
  | the same, multiplying the amount instead of replacing it ("B") | 14 |
  | how squeezed the air's way is, with walls over without | 7 |
  | how late the air arrives, with walls over without | 8 |
  | arriving air times the squeeze, per vertex | 13 |
  | arriving air times the delay, per vertex | 14 |
  | arriving air pooled over each walled-off area, times the squeeze | 15 / 14 |

- **Why it failed:**
  - The user: "so it is just calculating the difference in the ratio of how much they are
    blocked by grooves? that could be arbitrary..." (C6).
  - On the half-grooves ring, 6627 of the 9397 moves the fraction decided over the run (71%)
    went into the side pressing harder. One point: fraction 0.74 against 1.00, while the air
    arriving is 0.00174 against 0.00007. The ring grows from 40 to 157 points.
  - Any difference decides. On the wide horn 1.000 against 0.993 at every free point sends the
    ring up the cone through the wall's gaps.
  - It still needs F16's walls and their threshold.
  - Its best score flatters it. On the smooth-rings bisector amounts alone already send 37 of 41
    points the right way: the wall does the work. On the horn what it adds is pulling the bulges
    in the wall's gaps back.

### F18. Graded air: a crease slows air instead of stopping it

Also called: gradation, graded walls, openness, permeability, soft walls, the band, sharper
curves, "air has trouble moving through higher crease values".

- **What:** no walls. Every vertex lets by one minus its crease strength of the air. Tried on
  the groove's centre line only and over the whole band, with rings pinned on groove bottoms and
  not, and with one minus the strength squared, to the fourth, eighth and sixteenth power.
- **Where:** craw-112-fable, uncommitted.

  | Rule on top | Score |
  |---|---|
  | amounts alone, 2026-11-15 (18 cases; four variants) | 4 to 9 |
  | fraction first (centre line, band, each pinned and not) | 0 to 2 |
  | amount times fraction, band | 10 / 9 |
  | amount times fraction, centre line | 9 |
  | amounts alone, band | 8 / 7 |
  | amount times fraction, band, powers 2, 4, 8, 16 | 10, 10, 10, 9 |
  | fraction first, band, powers 2, 4, 8, 16 | 1, 0, 0, 0 |

- **Why it failed:**
  - Slowing air removes none of it (C7). On the smooth-rings bisector the side facing the crease
    is the outside of the torus and has 36% more surface. With the crease in the way 31% more air
    still arrives from it. The bisector moves away from the crease one row a pass and stops 180°
    round the tube, where the two sides have equal surface. All three bisector cases do this.
  - Nothing holds a ring. The ring on the horn reaches the foot at pass 5 and leaves: of 138
    points, 126 are pushed out onto the sphere, by amounts alone as much as by any fraction. By
    amounts alone it is still moving at pass 225, 24 edges out on average.
  - The curve makes no difference. What changes the score is the rule on top.
  - Crease values rarely reach one, where graded air would stop. The bisector's groove reads 0.54
    at its bottom. 66 of the 220 points on the horn's foot read one.
  - The nine torus cases that pass each end exactly one mesh row short of the groove, which is
    the tolerance.

### F19. Crease values rescaled so the surface's deepest reads one

Also called: normalising the crease values over the surface, dropping the floor, dropping the
95th percentile.

- **What:** crease strength is the smoothed valley curvature over its largest value on the
  surface. Before, it was divided by the larger of the 95th percentile of that curvature and the
  surface's median curvature of any kind.
- **Where:** craw-112-fable, 2026-11-20, uncommitted, in `SurfaceCreases` itself, so it also
  changes the ring tool's crease mode. Three existing tests fail on it.

  | Fit | Before | After |
  |---|---|---|
  | F17, walls, fraction first | 15 / 14 | 15 / 14 |
  | F18, amount times fraction | 10 / 9 | 9 / 9 |
  | F18, amounts alone | 8 / 7 | 3 / 1 |
  | F18, fraction first | 0 | 2 / 1 |

- **Why it failed:**
  - One point sets the scale for the whole surface (C1). Round the horn's foot one point reads
    one where 66 did, the mean falls from 0.90 to 0.58, and the ring runs off the foot (1.64).
  - It did what it was for on the smooth-rings bisector: the groove's bottom reads one all
    along, and under amounts alone the bisector comes to rest one row from it.
- **Found on the way:** smoothing cuts a sharp groove's bottom to a third (1.53 measured, 0.49
  smoothed). A crease value says how deep a place is against the rest of the mesh. It does not
  say whether the place is the bottom of a groove.

### F20. A crease measured by how far the surface turns across it

Also called: turn across, bend angle, dihedral angle of the groove, total turning, a scale-free
crease measure, "an angle needs no normalising".

- **What:** a measure, not a fit. From a centre-line vertex, walk each way across the valley
  while the surface still bends inward and the smoothed curvature keeps falling. The measure is
  the angle between the surface's normals where the two walks end. It was meant to replace
  crease strength as the thing a wall is decided on.
- **Where:** craw-112-fable, 2026-11-20, a bench test only
  (`theTurnAcrossEachGrooveBesideItsCreaseStrengthIsWrittenToTmp`). No fit was run on it.

  | Place | Crease strength, least / mean / most | Degrees turned, least / mean / most |
  |---|---|---|
  | pock-mark torus, the groove's centre line | 0.50 / 0.74 / 1.00 | 37 / 62 / 91 |
  | its eight pits, the most in each | 0.28 to 0.76 | 32 to 100 |
  | everywhere else on it | 0.00 / 0.01 / 0.24 | 0 / 2 / 40 |
  | horn, centre-line vertices on the foot | 0.43 / 0.59 / 1.00 | 4 / 49 / 63 |
  | horn, the 269 centre-line vertices elsewhere | 0.00 / 0.05 / 0.31 | 0 / 0 / 0 |
  | smooth-rings bisector, the long groove | 1.00 all along | 42 all along |

- **Why it failed:**
  - It spreads along one groove as much as crease strength does, so a cut on it is as fragile.
  - A pit's bottom turns as far as a groove's. No value at a point tells a pit from a groove.
    What differs is how far the line runs.
- **What held up:**
  - It reads alike on different meshes with nothing to divide by (42, 49 and 62 degrees for
    three fixtures' grooves), which crease strength does not (F19).
  - On the horn every centre-line vertex off the foot turns zero: the surface does not bend
    inward on both sides of it. That is a yes or no with no number, and it removes the ripples
    that sank the no-threshold run of F16. Not tried on a scan, where noise changes sign too.
- **Found on the way:** the gaps in F16's wall are not from the 0.5. The closing step adds any
  neighbouring centre-line vertex at any strength, so a foot point still missing after it fails
  the centre-line test itself: its curvature does not beat both neighbours across the groove.

### F21. Graded air weighted by how far each bit travelled

Also called: travel weighting, travel distance, travel time, fading air, aged air, "air that
takes longer routes is not as impactful" (the user's proposal of 2026-11-20).

- **What:** F18's graded air with no walls and no pinning, but each bit of air pushes a ring
  with one over the distance it travelled (the root of its time), particle by particle. One
  over the time itself was not used: it blows up for air that rises beside the ring.
- **Where:** craw-112-fable, 2026-11-20, uncommitted (`travelWeighted`, `travelKeepsPressure`).
  Twenty cases, the pock marks among them:

  | Crease values | Region's area still divides the push | Score |
  |---|---|---|
  | F19's (deepest reads one) | yes | 11 / 11 |
  | F19's | no | 8 / 8 |
  | the old scale | yes | 10 / 9 |
  | the old scale | no | 8 / 7 |

- **What it fixed:** it is the best graded run, against 9 / 9 for F18's amount times fraction
  and 3 / 1 for F18's amounts alone. With F19's values every ring that passes lies exactly in
  its groove, not a row short. All four runs pass the pock marks. The best passes the
  smooth-rings bisector, the slanted ring and both two-ring cases.
- **Why it failed:**
  - Both horn rings fail in every run (0.88 to 1.8 off, against 0.08 allowed). The crease round
    the horn's foot reads 0.43 to 1.00, and slowing the air that much does not outweigh the
    cone's side being the smaller.
  - The ring drawn far from its groove (`one_groove_far`) ends 166° off in every run.
  - The other two bisector cases end 170° to 180° off, and the far ring of the 0°/60° case,
    the trenches, the tree and the half-grooves ring still fail.
  - Without the region's area in the push it loses three cases, so travel does not replace
    that division.
- **Not settled:** the sum over travel uses eight sample rates, from one over the longest
  lifetime to one over the time to cross a mesh edge. Nobody has checked the score against
  more.

### F22. Air rising from the creases only

Also called: crease air, crease source, grooves as sources, the air turned round, "flat
surface gives off nothing", coverage of the grooves by the rings, no balancing.

- **What:** the user asked what would remove the balancing (the division by a region's area
  that pushes the horn ring off its foot). Air rises only from creased vertices, each its
  crease strength's worth, and dies at the rings. A ring moves toward the side more of it
  arrives from. No walls, no pin, no area. Tried from every creased vertex and from valley
  centre lines only, alone and with F21's travel weighting.
- **Where:** craw-112-fable, 2026-11-20, uncommitted (`creaseSource`, `creaseSourceLineOnly`).
  Twenty cases:

  | Air rises from | Travel weighting | F19's crease values | The old scale |
  |---|---|---|---|
  | every creased vertex | no | 6 / 5 | 6 / 5 |
  | valley centre lines | no | 5 / 5 | 4 / 4 |
  | every creased vertex | yes | 8 / 8 | 8 / 7 |
  | valley centre lines | yes | 2 / 2 | 2 / 2 |

- **What it did that nothing before did:**
  - Without travel weighting the ring drawn far from its groove (`one_groove_far`) arrives
    exactly, in all four runs. F18 and F21 leave it 166° off.
  - The ring on the horn sits on the foot over its whole length (0.01 to 0.05 off) with air
    from every creased vertex, with no wall, pin or area rule.
- **Why it failed:**
  - Without travel weighting distance does not count: all of a groove's air arrives however
    far off the groove is, so a ring between two grooves is drawn equally by both. The single
    ring with two grooves ends 13° to 52° off.
  - With travel weighting the nearer groove wins and those cases are exact, but the far ring
    is lost again (171° off).
  - Pits draw the ring as grooves do. The pock marks fail in all eight runs, 18° to 130° off.
    This is the old "ring stops in the pit" of F9 and F12: a crease that attracts cannot tell
    a pit from a groove, where a crease that blocks can, because air goes round a pit.
  - A ring with no groove left gets no air and stays where drawn, so the second ring does not
    stand opposite (about 101° off, its drawn place).
  - The trenches, the tree, the half-grooves ring, the far ring of the 0°/60° case and the
    bisectors still fail.
- **What it shows:** the two families fail on opposite cases. Creases that block air (F16 to
  F21) pass the pock marks and need the area rule, which fails the horn. Creases that give off
  air need no area rule and hold the horn, and fail the pock marks.

### F23. The rings give off the air and the creases swallow it

Also called: ring air, ring source, creases as sinks, swallowing creases, absorbing creases,
"a pit swallows only what passes over it", curvature squared as a swallowing rate.

- **What:** every ring vertex gives off air, its length of ring's worth. The air spreads and
  creased vertices swallow it. A ring moves toward the side more of its air leaves by. No
  walls, no pin, no area. It was meant to keep F22's freedom from the area rule and get back
  the difference between a pit and a groove.
- **Where:** craw-112-fable, 2026-11-20, uncommitted (`ringSource`, `ringSourceLineOnly`,
  `ringSourceByCurvature`). Twenty cases:

  | What swallows, and how much | F19's crease values | The old scale |
  |---|---|---|
  | every creased vertex, a chance of its crease value each step | 2 / 1 | 1 / 1 |
  | valley centre lines only, the same chance | 2 / 2 | 1 / 1 |
  | every vertex, at the rate of its valley curvature squared | 8 / 7 | (no scale) |

- **Why it failed:**
  - With a chance per step even the plain one-groove ring ends 90° off. Any faint crease
    swallows everything within a few edges, so only the nearest few vertices count, and the
    rule depends on how fine the mesh is.
  - Curvature squared has the right units and needs no crease scale. It passes the far ring
    and the ring on the horn (0.02 off over its length). It fails the pock marks (90° to 110°
    off), one of the single-ring two-groove cases (56°), and both cases where two rings
    compete for one groove.
  - The pit and groove difference did not come back. The pock marks fail in all five runs.
- **With F22, what it shows:** three kinds of crease that draw a ring (giving off air, giving
  it off with travel weighting, swallowing it) all end with the ring in the pits and pulled
  out of shape. Only a crease that blocks has passed the pock marks.

### F24. The bouncy castle with air lost at the creases

Also called: keep-back, air scaled by crease value, creases that swallow even air, lossy
creases, "did we try bouncy castle with air scaled by crease value?" (the user, 2026-11-20).

- **What:** F16's air (rising evenly, dying at the rings, a region's area dividing its push)
  with no walls and no pin. A crease swallows air crossing it, so less arrives. The same three
  swallowing rules as F23.
- **Where:** craw-112-fable, 2026-11-20, uncommitted (`creasesSwallow`). Twenty cases:

  | What swallows, and how much | F19's crease values | The old scale |
  |---|---|---|
  | every creased vertex, a chance of its crease value each step | 10 / 10 | 7 / 10 |
  | valley centre lines only, the same chance | 10 / 9 | 9 / 9 |
  | every vertex, at the rate of its valley curvature squared | 0 / 0 | (no scale) |

- **What it fixed:** the ring on the horn holds (0.00 to 0.04 off) in four of the five runs,
  with the area rule still in place. Lost air makes a crease of a half nearly a wall.
- **Why it failed:**
  - The pock marks fail in all five runs, 54° to 70° off: the ring stops at the pits. Air
    swallowed by a pit is gone, where air slowed or blocked by a pit goes round it.
  - The wide horn ring, the ring drawn far from its groove (166° off), two of the three
    bisectors, the far ring of the 0°/60° case, the trenches, the tree, the half-grooves ring
    and the slanted ring fail.
  - By curvature squared every ring stops three rows short of its groove.
- **With F21, what it shows:** the horn's foot reads 0.43 to 1.00 and the pits read 0.28 to
  0.76. The two ranges overlap, so no rule on the crease value can make the foot's 0.47 strong
  and a pit's 0.76 weak. F21 treats both as weak and loses the horn. This treats both as
  strong and loses the pock marks.

### F25. Crease measured by the largest sphere that rests on the surface

Also called: resting sphere, inscribed sphere, rolling ball, the balloon that fits, local
feature size, medial axis radius, "the sphere that fits on this face without intersecting
another face" (the user's proposal of 2026-11-20).

- **What:** at each vertex, the largest sphere that rests on the outside of the surface there
  and holds no other vertex. No limit means flat or bulging; a small sphere means a crease.
  For a fit it was turned into a crease strength of one minus the radius over the model's own
  half-size, so a sphere as big as the model reads as flat. That divisor is the assistant's
  choice; the user gave only the two ends.
- **Where:** craw-112-fable, 2026-11-20, bench tests only
  (`theLargestSphereThatRestsOnEachVertexIsWrittenToTmp`, and three benches).

  | Place | Radius in mean edges, least / middle / most |
  |---|---|
  | horn, the 220 vertices on the foot | 0.02 / 0.49 / 1.34 |
  | horn, within three edges of the foot | 1.02 / 4.20 / 7.14 |
  | horn, everywhere else | 7.18 at least; no limit at 7981 of 10196 |
  | pock-mark torus, the groove's bottom row | 1.20 / 1.84 / 2.77 |
  | its eight pits, the least in each | 0.45 to 0.95, and 4.69 in the shallow one |

  | Fit, with crease strengths from the sphere | Score |
  |---|---|
  | F21, graded air with travel weighting and the area rule | 10 / 10 |
  | F18, graded air by amounts alone | 9 / 9 |
  | F24, air lost at the creases | 6 / 9 |

- **What held up:**
  - It finds the horn's foot with nothing else near it: every foot vertex under 1.4, nothing
    off the foot under 7. Where the mesh is crowded the sphere only gets smaller, so no stretch
    of the foot reads as open.
  - Plain graded air with it passes the far ring (`one_groove_far`) and two bisector cases
    (`bisector_grooved_rings`, `bisector_rings_off_grooves`) that no graded run had passed.
- **Why it failed:**
  - Seven of the eight pits hold a vertex tighter than anywhere on the groove, so the pock
    marks fail in all three runs (70° to 90° off). A pit pressed deeper than the groove is
    tighter than the groove.
  - The horn still fails under F21 (1.16 and 1.22 off) with the foot read as nearly shut all
    round. So the assistant's claim that the horn failed because its foot leaked was wrong, or
    at least not enough: slowed air all arrives, the area rule makes the cone's side push
    about fifteen times as hard, and counting late air for less does not make up for that.
    Only a crease that takes air away (a wall, F16, or lost air, F24) has held that ring.

### F26. Walls with the pin removed, and walls found by the resting sphere

Also called: unpinned walls, no hold rule, sphere walls, walls by the largest sphere, thin
wall at the sphere's smallest, running the wall on along a fold.

- **What:** F16 (walls air cannot cross, the area rule, amounts alone) with two changes, tried
  apart and together. A ring lying along a wall is no longer held there. A wall is found by
  F25's sphere: a vertex where the sphere is no bigger than half the model (a picked number,
  for a first answer) and is at its smallest across the valley.
- **Where:** craw-112-fable, 2026-11-20, uncommitted (`wallsUnpinned`; the sphere walls are in
  the bench test only). Twenty cases:

  | Walls found by | Ring held on a wall | Score | Pock marks | Ring on the horn |
  |---|---|---|---|---|
  | crease strength | yes (F16) | 13 / 12 | fails, hooked on a pit | fails |
  | crease strength | no | 12 / 12 | exact | fails, 0.93 off |
  | the sphere | no | 12 / 12 | exact | fails, 1.22 off |
  | the sphere | yes | 13 / 13 | exact | anchors exact, whole ring 0.16 off (0.08 allowed) |

- **What it fixed:**
  - Removing the pin passes the pock marks exactly. The pin was what hooked the ring on a pit.
  - All three new runs pass the ring drawn far from its groove and the two bisector cases with
    grooves at their rings. No graded run but F25's had passed those.
  - The sphere finds the groove's whole bottom row on the pock-mark torus (40 of 40, none on
    its flanks) and no wall off the horn's foot.
- **Why it failed:**
  - The sphere's wall has gaps too. On the horn it holds 119 of the foot's 220 vertices and
    does not part the cone from the sphere: without its walls the surface is still one piece.
    Without the pin the ring leaves through the gaps. With it the ring bulges through them.
  - Running the wall on from where it is found (taking in each neighbour whose sphere is
    stopped by one of its own neighbours) did not close it: 162 of 220, still one piece. On the
    pock-mark torus it spread from 120 stray wall vertices to 857. No bench was run on it.
  - Every run fails the smooth-rings bisector, the far ring of the 0°/60° case, the trenches,
    the tree, the wide horn ring and the half-grooves ring. Without the pin the slanted ring
    fails too.
- **What it shows:** the pin exists only to cover gaps in the wall, and it is what breaks the
  pock marks. A wall with no gaps would need no pin. Neither the centre-line test on curvature
  nor the one on the sphere gives a wall with no gaps on an uneven mesh.

### F27. A wall shrunk from the whole tight band, so it has no gaps

Also called: closed wall, shrunk wall, thinned band, skeleton of the tight band, a wall that
is a loop by construction, "a wall is a band that runs round something".

- **What:** F26's unpinned walls, found a new way. Every vertex where F25's sphere is small
  enough starts as wall. Vertices are then taken away, widest sphere first, as long as taking
  one does not tear or pierce the wall. A band that runs right round something is left as one
  unbroken loop where the sphere is smallest. A patch that runs round nothing, such as a pit,
  shrinks away. No strength test tells a pit from a groove; whether the band runs round
  something does.
- **Where:** craw-112-fable, 2026-11-20. Twenty cases, walls air cannot cross, the area rule,
  amounts alone, no pin:

  | "Small enough" means | A wall's loose ends | Score |
  |---|---|---|
  | no bigger than the model's thinnest half-width | shrink away | 14 / 14 |
  | the same | kept | 14 / 14 |
  | no bigger than a quarter of the model's size | shrink away | 8 / 12 |

- **What it fixed:**
  - On the horn the wall is 140 vertices, all on the foot, and parts the surface in two (449
    vertices of cone, 10044 of sphere). On the pock-mark torus it is the groove's 40 bottom
    vertices and nothing else: all eight pits shrink away.
  - The ring on the horn (0.00 by anchors, 0.04 over the whole ring) and the pock marks
    (exact) pass in the same run, for the first time.
  - All three bisector cases pass, for the first time, the smooth-rings one exactly.
  - The far-drawn ring, the single-ring two-groove cases and all three two-ring cases pass.
- **Why it failed (what is left):**
  - The far ring of the 0°/60° case (133° off), the trenches, the tree, the half-grooves ring,
    the slanted ring (15° off over its length) and the wide horn ring (1.8 off).
  - A groove that stops runs round nothing, so its wall shrinks away. Keeping loose ends keeps
    it, and leaves 32 stray wall vertices on the horn up to 11 edges off the foot; the score
    and the failing cases are the same either way.
  - The limit is a picked number (C1). With the larger one the torus's own hole counts as a
    crease and gets a wall round its inside, and the score falls to 8 / 12.
  - The sphere is found by comparing every vertex with every other, which will not do for a
    scan.

## Why the horn's foot reads unevenly (measured 2026-11-20)

The foot is the same all the way round: the cone meets the sphere at 55.7°, by their shapes.
Its crease strength reads 0.43 to 1.00. Bench test
`theCreaseValuesRoundTheHornFootBesideItsMeshAreWrittenToTmp`:

- **The mesh is uneven there.** The horn is a cone joined to a sphere by `mesh_boolean`, which
  cuts the sphere's triangles along the foot. There are 220 vertices on the foot, 2 to 9 in
  each 10° of it, and the edges across the foot run from 0.5 to 1.2 mean edges.
- **Curvature at a vertex is a change of normal over an edge's length**
  (`PrincipalDirectionField`). At a sharp fold the change is fixed and the length is the
  mesh's, so the number measures the mesh. The largest raw curvature in each 10° runs from 5.4
  to 42.4, eight times over. Over the foot's vertices it goes with the length of the edges
  across the foot (r = -0.51) and with the edge count (r = -0.45).
- **Smoothing narrows that to twice over** (3.6 to 7.7), and then F19's rule divides by the
  largest. Two spots, at 100° and 250° round the axis, read 7.7 and 6.9. Everything else reads
  3.6 to 5.6, which is why most of the foot reads about a half.
- **The curvature does not add up to the fold.** Summed across the foot by area, the raw
  curvature gives about 21° of the 55.7°.
- **The fold read off the triangles is no better.** The widest angle between the triangles
  meeting at a foot vertex runs from 2.5° to 89.1°, mean 44.9°.

## Bench defects found

- **Only the drawn anchors are measured (found 2026-11-20).** The bench moves each drawn anchor
  to the nearest point of the fitted ring and measures those points, six on the horn. A ring
  that bulges between them passes. The ring on the horn under F18 reads 0.003 by its anchors
  while its worst point is 0.238 off, against 0.08 allowed. Under amounts alone the anchors pass
  with the ring 1.8 away.
  - The bench output now gives both counts. A pass is still counted by anchors.
  - Under F17 the tree case is the one that fails over the whole ring (37°). That may be the
    measure's fault: the tree's places were written for its anchors. Not checked.
- **A ring that travels far keeps its drawn spline** (F15, 2026-11-15).
- **The bench measures the state the fit stops in**, and a fit stops when its seams repeat an
  earlier arrangement, so a ring going round a cycle is scored wherever the cycle was caught.

## Archived without a verdict

Archived under CRAW-107. These were superseded by the anchor fit and never compared on the
fixtures:

- **Settle** (`RingSettle`): a random-walker solve that reassigns the faces beside ring walls to
  regions.
- **Curve fit** (`RingCurveFit`): an active contour; see F2.
- **Ring patch network** (`RingPatchNetwork`, `GridWallPull`): cuts the regions into four-sided
  patches and relaxes the grid map with a pull toward grooves.

## Names that keep coming back

When a proposal leans on one of these, it is almost certainly one of the entries above:

| Phrase | Entries |
|---|---|
| taken, claimed, owned, occupied or free groove | F3, F7, F8, F12 |
| nearest ring; nearest free groove | F1, F4, F7, F8 |
| soft minimum; τ about the ring spacing | F4 |
| matching or assignment of rings to grooves | F5, F6, F8 |
| valley lines; groove bottoms; "a comparison, not a threshold" | F5, F7 |
| tether to the drawn position | F2 |
| a ring with no groove stays as drawn, or spreads evenly | F5, F6 |
| weight λ between two aims; lexicographic order of aims | F4, F5, F11, F13 |
| merge rings; dead, empty or revived cluster; closing a region | F14 |
| geodesic centroid, medoid, Fréchet or Karcher mean; one metric for both steps | F15 |
| air flow, lifetime, walkers; pressure of a region; walls a region cannot cross; pinned seam | F16 |
| crease strength of at least a half; "strong" groove vertices; closing a wall's gaps | F16 |
| share, fraction, starved, bottleneck, throttle, crowding, pocket; "how much is blocked" | F17 |
| graded, gradation, openness, permeability, soft wall; slow the air instead of stopping it | F18 |
| a sharper curve, a power or a sigmoid on the crease value | F18 |
| normalise the crease values; the deepest reads one; another percentile or floor | F19 |
| turn across the groove; bend angle; a better number to decide a wall on | F20 |
| weight air by travel distance or time; fading, aged or late air counts for less | F21 |
| air from the creases; grooves as sources or attractors; no balancing, no area | F22 |
| rings give off the air; creases swallow, absorb or act as sinks; curvature squared | F23 |
| keep-back; air lost at a crease; air scaled by crease value in the bouncy castle | F24 |
| largest sphere that fits; rolling ball; feature size; medial axis as the crease value | F25 |
| drop the pin or hold rule; walls from the sphere; close the wall's gaps by running it on | F26 |
| shrink or thin the tight band to a closed wall; skeleton; a wall is a band round something | F27 |

## Logging a new attempt

Add an entry with:
- the next F number;
- every name the approach has gone by;
- what it does in one or two lines;
- where it was tried (worktree, commit or uncommitted) and its test count;
- why it failed, measured or in the user's words.

Before writing a new entry, check whether the attempt is an existing entry under a new name. If
it is, add the name to that entry's "Also called" line and add the run's result under it.
