---
name: mesh-segment
description: >
  Segment a scanned mesh into named parts in Ixdar's ring scene (rings, bisectors and part labels,
  usually drawn in crease mode) and judge a finished segmentation. Two roles: the segmenter
  (sonnet, or haiku for a simple mesh), which works one mesh in its own worktree, and the judge
  (opus), a separate adversarial agent that alone decides whether the segmenter has finished.
  Explains every segmentation DSL node, how regions and labels resolve, and the segmenter's
  definition of done. Use when briefing or acting as either role, or when reading or writing
  spline_ring, spline_cut, add_label or ring_regions statements.
---

# Mesh segmentation

Read this whole file before acting, then follow the section for your role.

Keys, control ids, modes and node ports come from the tools, not from here: `ixdar-cli tools`
lists every tool in the scene with its controls, action ids and modes; every `key`, `click` and
`control` reply says what took the input and what it did; `docs/mesh-node-catalog.json` has every
node's ports. The control ids named below were checked against the source when this was written;
if one is gone, trust `tools`. If you need a fact neither gives you, stop and report it as a gap;
do not guess and do not write it into this skill.

## Roles and models

| Role | Model | Sees | Never sees |
|---|---|---|---|
| Orchestrator (the session briefing the others) | the session's own | everything | — |
| Segmenter | `sonnet`; `haiku` only for a mesh with few, obvious parts | its worktree, the reference segmentation, the judge's verdict files | the judge's reasoning beyond its verdict |
| Judge | `opus` | the segmenter's saved DSL, its `tmp/segmenter-report.md`, the reference, the scenes | the segmenter's transcript, reasoning or notes other than the report |

The orchestrator launches each with the Agent tool and passes `model` explicitly on every launch
(`model: "sonnet"` for a segmenter, `model: "opus"` for a judge), never Fable. Never rely on a
default: a subagent launched without `model` inherits the orchestrator's model, which is usually
opus, and six opus segmenters drain the user's limit. It resumes the
same segmenter (SendMessage) with "continue" and the judge's verdict file path after each
`continue`, and a fresh judge each round, so no judge carries the last one's opinion. Only the
judge ends the run; neither the segmenter nor the orchestrator can declare it finished.

## How a segmentation is built

A segmentation is a chain of DSL statements in one `.dsl` file. Each statement takes the one
before it as `geometry=`, so the chain is a single line of nodes:

```
scan     = load_mesh(path="${IXDAR_DATA_ROOT}/<subject>/<scan>.glb")
repaired = repair_mesh(geometry=scan.geometry, ...)
surface  = surface_metric(geometry=repaired.geometry)
creases  = surface_creases(geometry=surface.geometry)
ring_00  = spline_ring(geometry=surface.geometry, metric=surface.metric, creases=creases.creases,
                       points="x,y,z; ...", normal="x,y,z", mode="crease", label="ring_00")
...
ring_54  = spline_cut(geometry=ring_53.geometry, metric=surface.metric, points="...",
                      ends="ring_04; ring_06", label="ring_54")
...
label_telson = add_label(geometry=ring_81.geometry, label="telson", points="x,y,z")
...
```

The ring scene writes everything from `surface_creases` on; the load and repair lines are the
ticket's. Points are surface positions, never vertex or face numbers, so the same file
re-evaluates after a repair setting or a ring changes.

### The nodes the ring scene writes

- **`surface_metric`** measures the surface once for geodesics. Every ring and bisector must take
  its `metric` output from a statement on this very mesh; one without it is refused.
- **`surface_creases`** measures the grooves once: the minimum principal curvature (the curvature
  across a valley), diffused over a few edges and ranked into a valley strength per vertex, and
  each edge's length scaled down where it runs in a groove. Concave grooves are cheap to follow,
  convex ridges are not. Crease mode needs it.
- **`spline_ring`** is a closed ring: a cubic spline through the authored anchors in order. Each
  anchor snaps to its nearest vertex; supporting anchors are fitted between them on every
  evaluation (only the authored ones are stored). One anchor plus `normal` is enough (the ring
  girdles the limb in that plane); three anchors decide a plane themselves. Two modes:
  - `geodesic` (the default): the smooth spline, each span within tolerance of the geodesic to
    the next anchor. Right for a neck with no groove, such as across a smooth limb.
  - `crease`: the spline fitted to the cheapest path over the crease cost that joins the anchors
    once round the part, so it hugs the groove they sit in. Right wherever a joint or seam has a
    groove, which on a scanned creature is nearly everywhere. The ring bends to reach every
    anchor, so **an anchor must sit in the groove's valley, not on the crest beside it**; an
    anchor off the valley makes a kink.

  It emits the ring's edge cycle as edge marks under `label`, its polyline, and the traced spline
  (which `extract_ring_region` cuts along).
- **`spline_cut`** is a bisector: an open spline through at least two anchors whose first and last
  anchor attach to the walls named in `ends` (rings or earlier bisectors; both ends may name the
  same wall). The ends re-attach to their wall's nearest vertex on every evaluation, so editing a
  wall moves the end. It splits every region it crosses. Same `geodesic`/`crease` modes as a
  ring. With `stretch`, it is a stretch of a closed ring between two walls (what sliver collapse
  leaves behind), and its points stay where written. Use bisectors to split a region no closed
  loop can (a carapace into left and right halves, a plate along a seam that ends on two rings).
- **`add_label`** names a part: `label` (a letter, then letters, digits and underscores) and
  `points`, one `x,y,z` inside each region of the part, `;`-separated. The mesh passes through
  unchanged; the labels ride in the `_labels` slot.

### How regions come out

The regions are not stored anywhere; they are recomputed from the walls on every evaluation:
faces flood across every edge no closed ring or bisector marks, and each connected patch is a
region. Each region records its bounding rings and its side of each (distal is a ring's smaller
side). Region numbers are flood order and change whenever a ring changes, so never refer to a part
by region number in anything that outlives the scene.

Problems are reported by ring name: an **open** ring (its trace does not close) walls nothing; an
**empty** ring; **crossing** rings; a **non-separating** ring (it doesn't separate two regions: it needs
more rings to enclose a mesh region, or a neighbouring ring already cut that neck). Two closed rings that run close together pinch thin
**slivers** between them; the scene's `collapse-slivers` control keeps one ring for each run of
slivers and turns the stretches of the other outside the run into bisectors. A sliver is a wall
problem: fix the rings, never name it.

### How labels resolve

A label is its points, not its regions. On every evaluation each point picks its nearest face and
so the region holding that face; the label covers all those regions. That is why a label survives
rings being added, edited or reordered: the point stays put and finds whatever region now holds
it. Consequences:

- A part split across several regions needs one point in each (the scene's `lb` does this: one
  point per selected region). Repeating a label name adds its points to it.
- If a ring change moves a boundary across a label's point, the label moves to the neighbouring
  region. After any ring edit, recheck the names.
- A region no point falls in is unlabelled. When points of two labels fall in one region, the
  label written later in the file silently takes it and the earlier one loses that region, so a
  part can vanish without an error after a ring edit; count every label's regions after each edit.
- A label name may not be a ring label (`ring_NN`).

The ring scene's save writes every label as one block of `add_label` statements at the end of the
file, chained one onto the next, after the last ring.

### The other segmentation nodes

These are not written by the scene; know them to read other DSLs and to propose rings.

- **`loop_through_points`** is the older geodesic loop: points joined by shortest edge walks and
  tightened by FlipOut (`pin` keeps the points). `spline_ring` replaced it for authoring.
- **`ring_regions`** is the region flood above as a node: `labels` picks which edge marks are
  walls, `select` takes `region N` and `point x,y,z` terms, `tag` turns the selection into a vertex
  tag, and its `report` lists every region and every problem ring.
- **`extract_ring_region`** takes selected regions out as their own closed mesh, cutting along the
  ring splines and capping the cut; the region tool's extract does the same.
- **`mark_edges`** writes typed edge marks under a label; rings are boolean edge marks, which is
  why `ring_regions` with empty `labels` takes every ring.

## Rules for both roles

- A scene on a large scan takes several GB. Run at most one scene JVM at a time yourself, only
  while you need it; never run `mvn test` while a scene is up; shut every scene down with
  `ixdar-cli shutdown` (or `--pid`) and confirm it is gone before you hand back. The segmenter and
  the judge take turns: the judge starts its scene only after the segmenter has shut its own down.
- Drive the scene only through `ixdar-cli`: `tools`, `control --action <id>`, `key`, `click`
  (window pixels; `--mods shift` adds to a selection), `hover`, `words`, `ui-state`, `pick`,
  `project`, `frame`, `orbit-get`/`orbit-set`, `screenshot`, `multiview`, `terminal --line`,
  `model --path`. Read state from replies, `tools` and `ui-state` first; screenshots are for
  judging shape, not for reading numbers.
- Rings and bisectors are made only in the scene and written by its save; never write or change a
  `spline_ring`, `spline_cut` or `surface_creases` statement by hand. `add_label` statements may be
  edited directly (renamed, copied, a point moved) as long as the chain stays intact; then reopen
  the file with `model --path <file>` and check every name lands on the region you meant, by area
  and centroid in the ui-state `regions` dataset, not by region number.
- Never drive a scene you did not start, and never touch another agent's worktree.
- On a remote scene host only the build and `src/main/resources` reach the host: a model path
  outside your worktree, or under `tmp/`, fails (silently for `run-scene --property`). Open the
  reference from your own worktree's `dsl/` copy; if master has a newer reference than your
  worktree, run `ixd wt sync <ticket>` first, with no scene of yours up. The two commands spell
  the path differently: `run-scene --property ixdar.model=dsl/crawfish/<file>` (relative to the
  resources directory) but `model --path ixdar-app/src/main/resources/dsl/crawfish/<file>`.
  Check the reference's part names show before relying on it: a segmenter that never opened it
  misses whole kinds of split (thorax plates, tail sides, merus upper/lower).
- A negative CLI value needs the `=` form (`--point=-0.3,0.1,0`, `--elevation=-1.5`); without it
  argparse reads it as a flag and the command fails, so a view you asked for may never change.
- To see grooves, capture with `--shading curvature --headlight` (multiview or screenshot);
  default shading hides shallow valleys. `click`/`hover` take window pixels while `pick`,
  `project` and screenshots take framebuffer pixels; the scale between them is in neither reply,
  so measure it once (project a known point, hover it) before clicking from a screenshot.
- To see what the rings have cut, pick a look: `ixdar-cli shading regions` (the G key) colours
  every region its own colour in every tool, and `ixdar-cli shading parts` colours each region
  by its part name, so two regions of one part match and an unnamed region stands out. In the
  default look the region tool paints every unselected region the same blue, which looks like
  one region. `pick --x --y` on a pixel returns the region number under it, which is how to
  tell two neighbours with similar colours apart without selecting each one.
- A click or hover leaves the ring tool's hover preview at the cursor, drawn like a real ring.
  Run `ixdar-cli hover-clear` before a screenshot you will judge rings from.
- Drawing mode (`draw-stroke-ring`) drafts a ring from a dragged line (`drag --via` for a bent
  one). `toggle-stroke-cut` switches its lines to cuts between two walls: start and end the line
  on or beside a ring or bisector. Drawing opens in the strokes look; `shading curvature` while
  drawing shows the grooves to draw along.
- When a ring is reported as separating nothing, fire `find-leak` in the connection tool: it
  shows the way round that ring (red) and, where one exists, the neck that closes it (green;
  `confirm-neck` cuts there). Fired again it takes the next such ring.
- To split one region in two where the join is hidden (a tail segment's dorsal from its
  underside, joined through the folds beside its side lobes): in the connection tool click a
  place on each half, from two camera views if need be, then fire `confirm-neck`. With no closed
  neck on the path it drafts a straight cut across the path's narrowest strait between two
  walls; `confirm-draft` it in the ring tool, then click the two places again and repeat until
  the reply says `not joined`. Four cuts split each tail segment of IMG_4113. Where it finds a
  closed neck instead (the head), look at the ring before keeping it: it is a geodesic loop,
  not a groove.
- A part bounded by grooves on a flat body (a thorax plate, a leg's base pipe under the body):
  fire `grow-tool`, click the part, and read the reply's patch size (the patch shows green). It
  floods the flat surface from the click and stops at rings and groove bottoms. A patch that
  runs over the neighbours means a groove is too shallow: `grow-less` lowers the groove
  strength it stops at (0.5 to start; IMG_4113's thorax needed 0.5 to 0.1, part by part),
  `grow-more` raises it, and the setting stays for the next click. `confirm-grow` turns the
  outline that is not already a wall into rings (closed stretches) and bisectors (open
  stretches ending on walls), edited afterwards like any other. Delete older cuts across the
  part first (click the cut in the ring tool, then `delete-bisector-point` until it reports
  the ring deleted), or the patch stops at them. Where no groove stops the patch at any
  strength (a midline, a leg against its base), cut with a drawn cut or the connection tool.
- To see every wall settled into its groove at once, fire `toggle-settle` (Y) and read the
  reply: one sparse solve pins each region's middle and each label point, frees the band of
  eight mean edges beside the walls, and gives each free face to a region, grooves insulating.
  Slivers and strips go to their neighbours, walls on smooth surface straighten, and the reply
  gives the walls' length and mean groove depth as drawn and settled. It is a view: the rings
  stay as drawn and `save-rings` writes them, not the settled walls. The same solve is the
  `settle_rings` node (after the last `add_label`), a group built like `quad_layout`:
  `ring_membership` assembles the DOF system, `newton_solver` relaxes it and
  `settled_ring_marks` extracts the marks. It is for files the ring scene does not edit:
  the scene reads such a file's rings wrongly (IMG_4113 came back with 91 regions and two
  rings separating nothing), so never save from the scene a file that holds the statement.
- `toggle-fit` (V) is the gentler view: every wall is cut into curves where walls meet, and each
  curve point slides across its curve (up to eight mean edges, never past a label point or
  nearer another wall) into the nearest groove while the curve stays smooth, by a Newton
  relaxation. Rings keep their labels and the points where walls meet stay put; it moves less
  than the settle and removes no sliver. It wins over Y when both are on and is a view like it:
  the scene rounds the fitted curves to the surface's own edges. The `fit_rings` node
  (`ring_curves`, `newton_solver`, `fitted_ring_marks`) instead carves the curves into a refined
  copy of the surface as an arc network (a vertex wherever a wall crosses an edge) and outputs
  that copy with the marks and labels; its `report` names any ring that stopped walling and any
  part name left without a region. See the carved walls in the mesh viewer, not the ring scene,
  which re-traces the drawn rings on the copy; the same warning about saving applies.

## Segmenter

You own one mesh's DSL in the worktree your ticket names. Save only that file; nothing else under
`dsl/` changes.

1. **Study the reference.** Open the reference segmentation your ticket names in the ring scene
   (`ixdar-cli run-scene --scene ring-tool --property ixdar.model=<reference DSL> --keep-alive`).
   In the region tool (`control --action region-tool`), read the named regions (`tools`, ui-state
   `regions`), turn on region numbers and part names through the controls `tools` lists, and look
   at each part with `terminal --line "sel <part>"`, `frame`, `multiview` and `screenshot`: where
   each boundary sits and which groove it follows. Note in `tmp/parts.md` what you need beyond the
   names. Shut the scene down. With no reference, write the part list you intend in `tmp/parts.md`
   from the subject's anatomy before drawing.
2. **Start in crease mode.** Open your DSL in the ring scene. The ring tool (`control --action
   ring-tool`) opens in geodesic mode; fire `switch-mode` before your first click so every draft
   is a crease ring, and check the reply says crease. Switch a single draft back to geodesic only
   where the boundary crosses smooth surface with no groove to follow, and say so in your report.
3. **Ring the parts.** Hover to preview the ring girdling the limb under the cursor, click to draft
   it, drag and add anchors, then `confirm-draft`. Put every crease anchor in the valley. **Cut every
   limb from the body where it joins the body**, not partway along it; where a limb lies folded
   against the body, its boundary follows the groove along the limb's edge on the body, around its
   base, so the body keeps no limb surface. **Cut the limbs before the body's own rings** (the
   cervical groove, the carapace edge): a body ring drawn first runs across the folded limbs, and
   then the limb rings cross it. Never drop a limb ring to keep a body ring; reroute the body ring.
   A limb base ring needs several anchors (six to ten round a claw or leg base) added in loop
   order: a crease ring from one anchor and a normal wanders into the nearest strong groove, and
   anchors out of order are refused as crossing themselves. A new anchor joins the span nearest
   it, so draft coarse to fine: three anchors spread round the base first, then the midpoint of
   each gap, then the midpoints of those, so every anchor lands on the arc it splits. Anchors are needed only on surface a
   camera can see: the crease path between two anchors finds a hidden groove (under an overhang)
   by itself. An overhang's silhouette is not a groove (pick reads crease 0 on both sides): a
   folded claw's merus overhangs freely, while its base lies on the body with a valley at its foot
   that shows only from an oblique view (front-below), not from straight below. Check crease
   strength with `pick` before trusting an outline. Where a ring draft keeps refusing anchors,
   the bisector sub-tool takes anchors in click order: a midline bisector plus one bisector per
   limb along its foot valley, out and back, can wall a base the ring tool cannot. Use bisectors (the
   ring tool's bisector sub-tool, listed in `tools`) for splits no closed ring can make. A
   bisector may cross other walls and splits every region it crosses, so one long bisector can
   split a whole run of tail bands into dorsal and side at once, as the reference's own long tail
   bisectors do; drawing one per band from lobe wall to lobe wall makes slivers. A bisector may
   end on an earlier bisector, which is how a leak between two seam cuts is closed. Its end
   attaches to the nearest wall, so put the end anchor on the wall you mean, away from corners
   where another wall is closer. After each
   confirm, read the reply and ui-state `regions` (rings that don't separate two regions are
   listed there as `regions.notSeparating`, not in `tools`; the `[regions]` log line names them
   too): no open, crossing, empty or non-separating ring, and
   no new slivers. Prefer moving the ring into the right groove: `collapse-slivers` drops one of
   the two rings along the run, which can delete a boundary a part needs (a tail band's
   underside), so check every part still has all its walls after it. It acts only on slivers under
   100 faces; treat any larger region that reads near 100% crease as a sliver too. Fire `save-rings` from the ring tool:
   fired while the connection tool is active it does not say whether it saved.
   **Fused scans.** A scan often fuses parts that touch (a leg tip on a claw, swimmerets on the
   tail, antennae on the legs), which gives the surface handles: a ring around such a part then
   doesn't separate two regions because the surface leaks round through the fusion. Cut each fusion first with a
   small ring around the contact (the connection tool's `confirm-neck`, listed in `tools`, finds
   the neck), list those rings in your report, and only then ring the part. A fusion ring and the
   part's base ring each separate nothing alone and free the part together: draw both in the same
   session, then confirm that the part separated before you save. Never delete a fusion ring
   because it doesn't separate two regions on its own.
   **Closed parts.** A claw whose movable finger lies closed against the fixed one still gets
   `fingers` split from `palm`: one ring round both fingers where the palm ends.
   **Scan orientation.** Scans are not posed like the reference: before naming any side, find
   which way is dorsal and which is the head in this scan, and write it in your report.
4. **Name every part.** In the region tool, select a part's regions (`terminal --line "sel <region
   numbers>"`, or `click --mods shift` to add one), then `terminal --line "lb <name>"`. Names are
   lowercase words joined by `_`, with sides as `left`/`right` and repeated parts numbered from
   the body outwards, in the reference's word order (the crawfish reference has
   `walking_leg_right_2_segment_1`, `claw_left_palm`, `tail_segment_4_side_right`). Number legs
   front to back by where each attaches on the body, after they are cut at their bases; never
   guess a number from a loose segment. `lb`
   replaces any name the selected regions had. Every region that is a real part gets a name.
5. **Check flatness.** Each row of the ui-state `regions` dataset (`regions.rows`; the region
   items in `tools` do not carry them) has `creaseShare` (area share in
   crease faces), `interiorCreaseShare` (crease area far from the region's rings: a joint no ring
   splits), `peakCurvature`, `peakOverSaturation`, `creasePoint` (the most curved face of the
   largest interior crease patch, else of the crease near the rings) and `creaseInterior` (whether
   that point is far from the rings). A part should be flat inside with its creases on its rings.
   `creaseInterior` true with a high `interiorCreaseShare` usually means an unsplit joint at
   `creasePoint`: ring it, or explain why it is not a joint. Regions bounded by many rings (a body)
   can hide a joint under a low share, so look at them. Slivers read near 100%; fix them as walls.
6. **Save and verify.** Fire `save-rings`, then `model --path <your DSL>` and confirm every ring,
   bisector and name came back and no ring problem is reported.
7. **Hand to the judge.** Write `tmp/segmenter-report.md` (see below), shut your scene down and
   hand back. The verdict comes back as `tmp/judge-<round>.md`. On `continue`, fix every line it
   lists (or answer a line you disagree with in the next report, with why), then hand back again.
   Stop at the round limit in your ticket and report what is still open.

### Definition of done

You are done only when the judge's latest verdict says `finished`, and every item below holds.
Check each before every hand-off and tick it in your report; a hand-off with an unticked item
must say why.

- [ ] The DSL was written by the scene's `save-rings`, holds no hand-written ring or bisector, and
      reopens with `model --path` with no evaluation error and no open, empty, crossing or
      non-separating ring reported.
- [ ] Only your mesh's DSL changed under `dsl/` (`ixd wt status <ticket>` shows the changed
      files).
- [ ] Every region carries exactly one part name; no region is unlabelled, claimed by two labels,
      or a sliver.
- [ ] Every part is the regions of one real part: none split without reason, none merged with a
      neighbour. Each part the reference has and this mesh shows is present; each one it does not
      show is listed in the report with why.
- [ ] Every name follows the naming pattern, with sides and segment numbers checked against the
      mesh and named the way the reference names them.
- [ ] Every limb is cut from the body at its base; no body region holds limb surface.
- [ ] Boundaries sit in the grooves where the surface has one: every ring is in crease mode unless
      the report names it as geodesic with why, and no crease anchor sits on a crest or a flat.
- [ ] No region has `creaseInterior` true with a high `interiorCreaseShare` that the report does
      not explain.
- [ ] For an Ixdar ticket: a launch entry (`ixd wt launch-add <ticket> --scene ring-tool
      --property ixdar.model=<your DSL>`) opens your DSL, `tmp/` holds a whole-body screenshot with part names shown and one per part group,
      and `ixd wt done <ticket>` passes once the judge says `finished`.
- [ ] Your scene is shut down and no JVM of yours is left running.
- [ ] `tmp/segmenter-report.md` holds: the part list (name, region count, area share), the parts
      not found and why, geodesic rings with why, anything you are unsure of, answers to judge
      lines you did not act on, this checklist ticked, and the commands you used.

## Judge

You decide whether the segmenter has finished. Be adversarial: your job is to find what is wrong,
not to approve. Read only the saved DSL, `tmp/segmenter-report.md`, the reference and the scenes.
Start your scene only after the segmenter has shut its own down.

1. **Learn the reference first**, the way the segmenter's step 1 does, before you open the
   candidate, so the candidate does not set your expectations.
2. **Walls.** Open the candidate DSL in the ring scene. Confirm the file holds no hand-written ring
   (every ring and bisector has the scene's form), no ring problem is reported, and no slivers.
   For crease rings, flag authored anchors off the groove (on a crest or a flat) with where they
   are, and every geodesic ring the report does not justify.
3. **Parts.** For each part the mesh shows: is there a region set named by the pattern, is it one
   part (not split, not merged), and does its boundary sit where the reference puts the equivalent
   one? List missing, extra, merged, split and misnamed parts, check each side and segment number
   against the mesh, and test the reasons the report gives for parts it says the mesh lacks. Check
   every limb is cut at its base and no body region holds limb surface.
4. **Blind A/B.** For a sample of parts and whole-body views, capture the candidate and the
   reference from matching camera poses (`orbit-get`/`orbit-set`, `frame`, `multiview`,
   `screenshot`) with ring numbers and part names hidden. Write down a random order before you
   look, pick which of each pair is the hand-segmented reference, record the picks, then reveal. A
   view you cannot tell apart passes; for one you picked easily, say what gave it away. Skip this
   step when there is no reference.
5. **Flatness.** Read every row of the ui-state `regions` dataset. Flag `creaseInterior` true with a high
   `interiorCreaseShare` (compared with the same part in the reference), with its `creasePoint`.
6. **Definition of done.** Go through the segmenter's checklist yourself; a tick you cannot
   confirm is a problem line.
7. **Verdict.** Write `tmp/judge-<round>.md` in the segmenter's worktree: `finished` or
   `continue` on the first line, then each problem as one actionable line (part, what is wrong,
   where as a surface point and part name, what to do), the A/B picks and result, and the flatness
   flags. `finished` only when no problem line is left. Shut your scene down and answer the
   orchestrator with the verdict and the file path.
