# Ring fit energy plan

Notes for the ring anchor fit (`fit_ring_anchors`, the craw-105 worktree of Ixdar).

## The energy looks in the ring scene

The ring scene has two looks over the fit: `BOTTOMS_LOOK` (where the fit takes the groove bottoms
to be) and `PAID_LOOK` (what each vertex pays as the rings stand). Both are registered in
`RingScene.setLooks` as a `SurfaceLook` whose field supplier calls `AnchoredRings.look(...)`.

### Problem: the look goes stale

The paid look is not recomputed

- after each step of the fit, and
- after a ring is moved by hand.

The supplier builds a whole new `AnchoredRings` (and so a new `RingAnchorFit`) from the bundle
each time it is asked, and nothing asks it again when the rings change.

### What is needed: a general look-refresh hook

A look must be able to say "my field depends on this, recompute me when it changes", and whoever
changes the rings must be able to say "the rings changed" without knowing which look is picked.

- The region and part looks already stay current, but by their own route: `RegionLayer` decides
  for itself when to recolour and calls its private `overrideLook`. That is specific to regions.
- Do this once, in `SurfaceLook` / `SurfaceLooks`, so the region looks, the paid look and any later
  field look use the same hook. Do not add a second special case for the paid look.
- Callers that must fire it: a fit step (each kept move in `RingAnchorFit.relax`, through the
  tracer's `settle`), the ring tool moving or adding or removing an anchor, and a model reload.
- The paid look should reuse the fit that is running rather than building a new one per refresh.

### Problem: the paid look is blocky

What the look shows is `log10(1 + weight * (distance / meanEdge)^0.5)`. Two things make it blocky,
and neither is the search for groove bottoms (that only feeds the field term, whose weight is 0):

- `weight` is two-valued: a vertex over the crease threshold weighs 1001 times its area, every
  other vertex 1. The picture is mostly that threshold.
- `distance` is measured along mesh edges by Dijkstra from the ring's path points, so its level
  sets follow the edges, and each vertex belongs wholly to one ring.

Fixing this is a change to the energy, not to the look: see the planned energy below.

## The planned energy

The energy must be global: a groove pulls a ring from any distance (a ring nearly opposite a
groove still reaches it). So the form the code has today is kept, every point of the surface
paying for its distance to the nearest ring and a groove's points paying more, and each
ingredient of it is replaced. A line integral of a groove cost along the ring was considered and
dropped: it only pulls within a groove's own width.

### Equation

$$
E(\Gamma) \;=\; \frac{1}{W}\int_M w(x)\,\varphi\big(d_\Gamma(x)\big)\,dA
\;+\; \sum_i \int_{\gamma_i} g(x)\,\Big[\,\beta + \alpha\,\kappa_g(s)^2\,\Big]\,ds
$$

$$
\sigma(x) \;=\; 1 - e^{-\kappa_v(x)/\kappa_0}
\qquad
w(x) \;=\; 1 + \omega\,\sigma(x)
\qquad
g(x) \;=\; 1 - (1-\varepsilon)\,\sigma(x)
$$

$$
\varphi(d) \;=\; \big(d^2 + \delta^2\big)^{p/2} - \delta^{\,p},\quad 0 < p < 1
\qquad
W = \int_M w\,dA
$$

There are no groove objects anywhere in this. The surface enters only through the one field
$\sigma(x)$, how groove-like each point is, and the fit is one solve over every ring against
that field. "Groove A" and "trench" below are names for parts of a fixture, not things the
energy knows about.

$$
d_\Gamma(x) \;=\; -\tau \,\log \sum_i e^{-d(x,\gamma_i)/\tau}
$$

| Symbol | Meaning |
|---|---|
| $\gamma_i$, $\Gamma$ | one ring or bisector; all of them together |
| $d(x,\gamma_i)$ | geodesic distance from surface point $x$ to ring $i$, by the heat method |
| $d_\Gamma(x)$ | soft minimum of those over the rings: the distance to the nearest ring as $\tau \to 0$ |
| $\kappa_v(x)$ | valley curvature, continuous (no threshold) |
| $\sigma(x)$ | how groove-like a point is: 0 on smooth surface, towards 1 in a deep groove |
| $w(x)$ | what a point's distance counts for: 1 on smooth surface, up to $1+\omega$ in a deep groove |
| $g(x)$ | what a ring pays for its own length and bend at a point: 1 on smooth surface, $\varepsilon$ in a deep groove |
| $\varphi(d)$ | the cost of a distance: quadratic within $\delta$ of a ring, growing as $d^{\,p}$ beyond |
| $\delta$ | smoothing length, about a groove's width |
| $\tau$ | softness of the nearest-ring choice, about the spacing between rings |
| $\kappa_g$, $L_i$ | a ring's bend within the surface; its length |
| $A$ | surface area; every length is divided by $\sqrt{A}$, not the mean edge |
| $\alpha, \beta, \omega, \varepsilon, \kappa_0, p$ | tuning constants; lengths in the ring term are in units of $\sqrt{A}$ |

How it behaves:

- **Global.** Every groove point pulls on the rings from any distance.
- **Nearer groove wins.** $p < 1$ keeps the cost concave far out, so closing the shorter gap
  saves more.
- **No two rings in one groove.** A groove with a ring in it pays nothing, so a second ring
  gains nothing there.
- **No groove, go to the middle.** The smooth surface's weight of 1 does this.
- **A ring pays for being on smooth surface.** Its length and its bends cost $g$: full price on
  smooth surface, almost nothing in a groove. So a ring is straight and short where there is no
  groove, follows a groove's turns freely where there is one, and a stretch that leaves the
  grooves to cross smooth surface is charged for it. These terms are in the energy the solve
  descends, not only in the accept test.
- **Smooth.** $\varphi$ has no cusp at the ring, $w$ has no threshold and the soft minimum has
  no crease, so the look $w\,\varphi(d_\Gamma)$ is smooth.

### How each ingredient differs from today

| Ingredient | Now | Planned |
|---|---|---|
| Groove weight | 1 or 1001, by a threshold on groove strength | $w(x)$, continuous in depth |
| Distance | Dijkstra along edges from the vertex nearest each path point | heat-method geodesic distance, a path point's heat split between its edge's two ends |
| Nearest ring | hard: each vertex belongs to one ring | soft minimum over the rings |
| Cost of a distance | $(d/\bar e)^{0.5}$, infinitely steep at the ring | $\varphi(d)$, the same far out, quadratic within $\delta$ |
| Units | mean edge length | $\sqrt{A}$ |
| Length | 100 per mean edge wherever the ring is, checked only when accepting a move | $\beta\int g\,ds$: cheap in a groove, full price on smooth surface, in the energy the solve descends |
| Bend | none in the energy; a stiffness inside the solve | $\alpha\int g\,\kappa_g^2\,ds$: free in a groove, charged on smooth surface |
| Groove bottoms, field term | computed, weighted 0 | gone |

### Necessary parts

1. **Geodesic distance field, by the heat method** (Crane, Weischedel, Wardetzky 2013,
   "Geodesics in Heat"; implemented from the paper, no third-party code). With $L$ the cotangent
   Laplacian, $M$ the vertex areas and $t = \bar e^{\,2}$ (mean edge length squared):

   $$
   (M + tL)\,u = \delta_{\gamma_i}
   \qquad\quad
   X = -\frac{\nabla u}{|\nabla u|}
   \qquad\quad
   L\,\phi = \nabla\!\cdot X
   $$

   - Heat is released on the ring, its gradient normalised per face, and a Poisson solve
     recovers the distance $\phi$, shifted so it is 0 on the ring.
   - A path point on an edge splits its heat between the edge's two ends by its fraction along
     the edge, so the field varies continuously as a ring moves.
   - Both matrices depend only on the mesh: factor each once per surface (sparse Cholesky,
     `DirectSolver`), then each distance field is two back-substitutions.
   - One field per ring, for the soft minimum; only a ring that moved is solved again.
   - `SurfaceGeodesics` has no distance field today; cotangent weights exist in the cross-field
     code (`NDirectionField`).

2. **Continuous groove weight.** $\kappa_v$ from `SurfaceCreases.valleyCurvature`, with no
   crease threshold. The groove-bottom search (`toBottom`, `bottomward`, `BOTTOM_MARGIN`,
   `ACROSS`) and the field term (`FIELD_WEIGHT`, `FIELD_REACH_EDGES`) are no longer used by the
   energy. Removing them needs a yes from the user.

3. **Ring quantities by arc length.** The bend and length terms are summed over a traced path's
   points with the length each point stands for (`share`); $\kappa_g$ is the turning of the path
   within the surface at each point.

4. **A solve that descends the same energy.** Each point of the surface pulls every ring's
   nearest point toward itself along $\nabla d(x,\gamma_i)$, by $w\,\varphi'(d_\Gamma)$ times
   that ring's share of the soft minimum; the bend and length gradients are added. The heat
   method gives the distance and its direction but not which path point is nearest, so a
   Dijkstra pass stays for that assignment only. Unknowns stay one move across the ring per
   anchor, blended to path points by `RingBlend`.

5. **Units.** Lengths are divided by $\sqrt{A}$, so the constants do not depend on mesh density.

6. **Anchors that can slide along their ring.** Today an anchor moves only across its ring. The
   trench test below needs the place a ring leaves one groove for another to travel along the
   groove, which is along the ring. Either the solve gets a second unknown per anchor (its move
   along the ring), or anchors are respaced along the traced path between rounds.

7. **The look-refresh hook** from the section above, so the look shows the energy per step.

### Still not covered

- The energy is non-convex (one minimum per groove), so the starting position still matters.
- It does not measure region shape and does not forbid two rings crossing.
- A groove that crosses a ring, and that no ring or bisector lies in, still pulls on the ring and
  kinks it at the crossing. The bend and length terms resist; a bisector in the groove ends it.

## Unit tests to add

All are new `ring_fit_*` fixtures on the grooved torus, asserted in `RingAnchorFitTest`. Each
asserts where the anchors stand, never which groove a ring "belongs" to: the energy has no such
notion.

### One ring nearest two empty grooves

- **Fixture:** grooves across the tube at 0° and 60°; one ring at 30°, a second at 200°.
- **Expected:** one ring in each groove.
- **Why it is a test:** with a hard nearest-ring choice the 30° ring is nearest both grooves and
  takes one; the other groove stays nearer that ring (60°) than the second (140°), so the second
  ring never feels it and settles opposite. The soft minimum is what lets the uncovered groove
  pull the second ring. The current code fails this case.

### A slanted ring straddling two grooves

- **Fixture:** two grooves across the tube a short way apart; one ring between them, slanted so
  half its anchors stand close to groove A and the other half close to groove B.
- **Expected: not decided.** The options:
  1. *The whole ring goes into one groove.* Recommended: a ring split across two grooves cuts
     along neither. Assert that every anchor ends in the same groove, whichever it is; a second
     fixture with more anchors near A than B asserts that groove is A.
  2. *The ring stays split*, half in each groove with two crossings between.
- **What the planned energy does:** the coverage term prefers the split. Split, each groove is
  half covered and its uncovered half is no further than the other groove from a ring; whole in
  A, all of B pays that full distance. What opposes the split is the ring term: the two
  crossings run over smooth surface, where length and bend cost full price.
- **Consequence if option 1 is chosen:** this test fixes how large $\beta$ and $\alpha$ must be
  against $\omega$, and the trench test below fixes them from the other side. The two together
  are the check that one setting of the constants gives both results.

### The slanted ring, with two trenches joining the grooves

- **Fixture:** the slanted-ring fixture, plus two short trenches running from groove A to groove
  B at two places round the tube, as deep and as sharply curved as the grooves themselves. The
  ring as drawn crosses from A to B where there is no trench. A and B still run all the way
  round the tube.

  ```
  round the tube
    360° ─┬────────A─────────B────────┬─
          │        ║         ║        │
    270°  │        ╠═════════╣        │   trench 2
          │        ║ ╲       ║        │
    180°  │        ║   ╲     ║        │   the ring crosses A to B here as drawn
          │        ║     ╲   ║        │
     90°  │        ╠═════════╣        │   trench 1
          │        ║         ║        │
      0° ─┴────────A─────────B────────┴─
                   → round the torus
  ```

- **Expected (decided):** the ring turns round the tube until its two crossings lie in the
  trenches: along A for one stretch, across trench 1, along B for the other stretch, back across
  trench 2. Every anchor stands in a groove or a trench. The stretches of A and B the ring does
  not use stay empty.
- **Why the energy gives it:** with the crossings in the trenches the trench points pay nothing,
  and the ring's whole length is in groove, so the crossings and the four corners cost almost
  nothing. Against going whole into A it covers more and pays about the same; against the
  crossings staying on smooth surface it pays far less.
- **What it rules out:** any rule that a ring lies in one groove. Whether a ring splits has to
  come out of the energy.
- **What it needs from the solve:** anchors that slide along their ring (part 6).

## Definition of done

- Every unit test passes: `RingAnchorFitTest` unchanged in what it asserts today, plus the two
  tests above, the other suites in the worktree (`RingCurveFitTest`, `RingNetworkSolveTest`,
  `RingSettleTest`) and the rest of the build's tests.
- The ring scene's energy look shows the planned energy and is smooth: no blocks following the
  crease threshold or the mesh edges. A screenshot under `tmp/` shows it.
- The look updates after each step of the fit and after a ring is moved by hand, through the
  general look-refresh hook, which the region and part looks use too.
