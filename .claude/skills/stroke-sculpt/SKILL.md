---
name: stroke-sculpt
description: >
  Sculpt a mesh toward a subject from reference pictures alone, by drawing weighted SVG strokes on
  Ixdar multiview captures (the stroke_sculpt DSL node), and score the result blind. Three roles:
  the orchestrator, which renders jittered reference pictures from a goal mesh and keeps the goal
  out of sight; the sculptor, which sees only those pictures and the judge's words; and the judge,
  which compares the sculpt with the goal, keeps every score secret and tells the sculptor in words
  which parts need the most work. Use when briefing or acting as any of the three.
---

# Stroke sculpting from references

Read this whole file before acting, then follow the section for your role. The protocol models
real use: a sculptor has reference pictures of a subject, never its mesh, and a critic who has
seen the subject tells it in words what is still wrong, like a teacher at the sculptor's shoulder,
never with a number. The goal mesh exists so the judge can compare and the run can be measured.

Facts about nodes, ports, SVG attributes and CLI flags come from the tools, not from here:
`ixdar-cli --help`, `ixdar-cli <command> --help`, `docs/mesh-node-catalog.json` (the
`stroke_sculpt` entry) and the route list `ixdar-cli` prints. If you need a fact the tools do not
give, stop and report it as a gap; do not guess and do not write it into this skill.

## Roles and what each may see

| Role | Sees | Never sees |
|---|---|---|
| Orchestrator | everything | — |
| Sculptor | `tmp/references/*.png` in its worktree, its own sculpt, the judge's feedback words | the goal mesh, the manifest, any score or number from the judge, the judge's directory |
| Judge | the sculptor's DSL and SVG files (group names and stroke counts, from `stroke-report`), the goal mesh, its own renders of the goal and of each round from the same cameras, its metrics | the reference pictures, the sculptor's notes, report or reasoning |

The judge directory is `~/.cache/ixdar-sculpt-judge/<subject>/`: the goal mesh, its decimated
copy, the reference manifest and the scores. It is never inside a worktree.

## Orchestrator

1. **Keep the goal out of the worktree.** Put the goal mesh (OBJ) in the judge directory. Nothing
   derived from it except the reference pictures may enter the sculptor's worktree.
2. **Render the references** through Ixdar. The script loads the goal in the mesh viewer of an
   Ixdar checkout, in clay shading, and screenshots it from jittered cameras with
   `orbit-set --fov --roll`:

   ```bash
   uv run python "$REPO_HOME/ai-workspace/.claude/skills/stroke-sculpt/render_references.py" \
     --checkout "$REPO_HOME/Ixdar" --goal ~/.cache/ixdar-sculpt-judge/<subject>/<goal>.obj \
     --out <worktree>/tmp/references \
     --manifest ~/.cache/ixdar-sculpt-judge/<subject>/references_manifest.json --seed <N>
   ```

   It writes seven pictures named by their nominal view only (`ref_01_front.png` …
   `ref_07_top.png`). Each has its azimuth and elevation jittered by up to 8°, a roll of up to 3°,
   a field of view from 15° to 55°, the subject filling 55–85% of the frame, and the headlight on
   or off. The exact cameras go to the manifest in the judge directory. Run it with no other scene
   up in that checkout, use a new seed for each run, and look at the pictures before handing them
   over.
3. **Stage 1: build and check the base mesh.** Before any sculptor starts, trace the references
   into one outlines SVG (`ixdar-cli trace-outlines`) and build the base from it with
   `silhouette_hull` (with `symmetry` for a symmetric subject), `volume_to_mesh`,
   `keep_largest_part`, `smooth_mesh` and `quad_layout` (see each node's catalog entry). Save the
   base as a tracked mesh file next to the sculpt (`resources/dsl/<subject>/base.ply`, with the
   outlines SVG and the `base.dsl` that built it), so the sculpt loads it instead of recomputing
   it. This is the midway checkpoint: set a per-view outline threshold first, then measure the
   saved base against the traced outlines with `ixdar-cli outline-compare`, and have the judge
   record the base as round 0. Stage 2 starts only when the base meets the threshold. The
   sculptor need not see how the base was made, only the base and the pictures.
4. **Brief the sculptor** with only its worktree, its ticket and this skill. Do not mention the
   goal file, the judge directory, the seed or any number about the subject. If the ticket's
   text names any of those, give the sculptor the brief instead of the ticket.
5. **Stage 2: run rounds until the judge stops.** The sculptor works one round per turn and hands back.
   After each round, give the judge that round's snapshot; it scores it and answers `continue`
   with its feedback, or `stop`. On `continue`, resume the same sculptor (SendMessage) with
   "continue" followed by the judge's feedback block verbatim, and nothing of your own: no score,
   no direction, no comment. Before relaying, check the feedback holds no number, measurement,
   score, file path or goal file name; if it does, send it back to the judge to rephrase. Only the
   judge ends the run; the sculptor cannot, and neither can you on the sculptor's account of its
   work. Until the judge says `stop`, write no score or goal-derived number anywhere in the
   sculptor's worktree, including the ticket's measurements file; fill that in after the run ends.
6. **Report to the user**, after the judge's `stop` and the sculptor's final report. Send every
   item below, without being asked; the sculptor never gets any of them. `$SKILL` is
   `$REPO_HOME/ai-workspace/.claude/skills/stroke-sculpt`, `$W` the sculptor's worktree, `$D` its
   `resources/dsl/<subject>/`, and `X="uv run --directory $W ixdar-cli"` with a mesh viewer up
   (`$X run-scene --scene mesh-viewer --keep-alive`, `$X shutdown` at the end). Picture scripts
   run with `uv run --with pillow python -I $SKILL/<script>`.

   | Item | How |
   |---|---|
   | Reference strip | `stack_pictures.py $W/tmp/report/refs.png $W/tmp/references/ref_*.png --across` |
   | Base checkpoint: base against the traced outlines | the `overlay.png` from `outline-compare`, under the reference strip: `stack_pictures.py $W/tmp/report/base_vs_refs.png $W/tmp/report/refs.png $W/tmp/base-checkpoint/overlay.png`, with the per-view and summed pixels and the threshold |
   | Scores table | from the judge's `scores-<run>.json`: per round chamfer, image distance, Hausdorff, silhouette IoU, change or not; the floor, the best of each and the stop reason; the best chamfer of earlier runs |
   | Final sculpt beside the references | the sculptor's side-by-side from its final report (one row per view, its cell beside the closest reference) |
   | Any round against the references | `stack_pictures.py $W/tmp/report/roundNN_vs_refs.png $W/tmp/report/refs.png $W/tmp/rounds/roundNN/multiview.png`; send it whenever the user asks to see a round |
   | Rounds animation | `$X sculpt-animate --rounds $W/tmp/rounds --out $W/tmp/animation --shading clay`, send `animation.gif` |
   | Every stroke over the final sculpt | `$X model --path $D/<sculpt>.dsl`, `$X multiview --camera $D/<sculpt>.svg --shading clay --out $W/tmp/report/final_camera.png`, then `strokes_overlay.py $W/tmp/report/final_camera.png $D/<sculpt>.svg $W/tmp/report/strokes_on_final.png` (one colour per `<g id>` group) |
   | Measurements | `$W/tmp/<ticket>-measurements.json` with the base checkpoint and every round's numbers, written only now, and the same summary on the ticket (`generate_board.py update <ticket> --add-changes`) |
   | Tool problems | the open lines of the sculptor's `tmp/frictions.md`, put to the user as a ticket |

   Then name what the sculptor could not get and why, in its words and yours, and what waits on
   the user (landing, archiving, open tickets).
7. **Keep the run before it closes.** `tmp/` is ignored by git, so `ixd land` and `ixd wt archive`
   delete it. Before the user lands or archives the run, copy `$W/tmp/report/`, the measurements
   file, `tmp/rounds.md`, `tmp/subject.md`, `tmp/frictions.md`, the sculptor's own scripts and the
   round snapshots into `~/.cache/ixdar-sculpt-judge/<subject>/<run>-kept/`, and say where.

## Sculptor

You have pictures of a subject and a base mesh whose silhouettes already match them (or, when the
brief gives none, a sphere). Make it into the subject: the outlines are largely done, so the work is
what no outline shows, such as cavities, ridges and surface detail, plus outline corrections where
the base is still off.

1. **Study the references.** Open every `tmp/references/ref_*.png`. The names give only the rough
   view; the real angle is off by a few degrees, the lens differs between pictures (a wide lens
   exaggerates what is near the camera), and the subject's size in frame differs. Before sculpting,
   write `tmp/subject.md`: the subject's proportions (width : depth : height, read from pictures
   that agree), its symmetry, and its major masses and cavities, noting which picture each comes
   from and where pictures disagree.
2. **One pass, organised as named layers.** The sculpt is one DSL file under your ticket's
   `resources/dsl/<subject>/`: the base (`base = load_mesh(path="dsl/<subject>/base.ply")`, or a
   sphere when there is no base), then a single `stroke_sculpt` node reading one SVG. Every stroke
   is applied to the base at once, so strokes do not stack on each other's results and their order
   does not matter. Do not chain `stroke_sculpt` nodes (the node refuses it) and do not rebuild or
   edit the base mesh file. Inside the SVG, group strokes by the part they shape with
   `<g id="...">`: parts such as `cranium`, `eye_sockets`, `jaw`, `teeth`. A group owns its part:
   when that part is wrong later, revise that group rather than adding a correction elsewhere.
   Start by capturing a multiview of the base with the camera written into a blank SVG (see
   `ixdar-cli multiview --help`), draw on it, then run `ixdar-cli sculpt-sync`. Sync stores every
   stroke as a curve on the base and redraws it in every cell that sees it, under one `data-id`.
   After a sync, edit any stroke in any one cell (move its points, keeping `data-id` and
   `data-pts`), add shapes with no `data-id`, or delete one, then sync again. `ixdar-cli
   stroke-report` shows each stroke's radius, depth and peak move, and names any stroke that moved
   nothing and why. The sculpting tools are the focus, but the DSL may use any node in
   `docs/mesh-node-catalog.json`.
3. **Draw like line art.** The `stroke_sculpt` catalog entry gives every stroke attribute and the
   formula from them to the displacement; read it before drawing.
   - **Silhouette strokes** move an outline: draw where the subject's outline should be in a view.
     A plain stroke drawn on an outline lands edge-on and does nothing. Compare your multiview cell
     with the reference closest to that view, allowing for its angle and lens.
   - **Ridge and valley strokes** for brows, cheekbones, jaw lines and grooves.
   - **Filled shapes** only for cavities (eye sockets, a nasal opening); a bowl profile curves the
     floor up to the rim.
   - Size and depth are in world units on the stroke itself. Small features (teeth) need small
     radii.
   - Use the node's symmetry axis for a symmetric subject, and per-stroke mirroring only for
     single strokes on a node without it.
4. **Order of work:** proportion and outline first (silhouettes from the front, side and top),
   then major masses, then cavities, then ridges, then small detail.
5. **Look at your strokes on the sculpt every round.** Before writing a round's entry, capture
   the sculpt through the SVG's own camera (`ixdar-cli multiview --camera <sculpt>.svg --shading
   clay`), draw every stroke over it with
   `$REPO_HOME/ai-workspace/.claude/skills/stroke-sculpt/strokes_overlay.py` (usage in its
   docstring; run it with `uv run --with pillow python -I`), and open that picture beside each
   view's closest reference. Check the back, top and bottom too, not only the front and sides.
   This is how you see what each stroke did and what no stroke covers yet.
6. **Work in rounds.** A round is one set of edits (revise any groups, add new ones) ending in a
   synced DSL that evaluates. At the end of each round, write its snapshot with `ixdar-cli
   sculpt-snapshot`, check the snapshot holds every file the sculpt reads (the `.strokes` file
   beside each SVG included) and that it loads, write one entry in `tmp/rounds.md` (which groups changed,
   what you drew or undid, and how the sculpt now compares with the references, view by view),
   and hand back with the round's snapshot path. Then wait. You never decide the sculpt is
   finished: if you are told "continue", there is always a next round. "continue" comes with the
   judge's feedback: the parts it ranks as needing the most work, in words. Start the round with
   those parts; then attack whatever else differs most from the pictures.
   A tool limit is not a reason to stop working on a part. When a tool stops you (a fill that
   folds past some depth, no way to cut a hole), write it in `tmp/frictions.md` and keep
   improving that part another way, then move on to the next biggest difference. The subject's
   detail needs many strokes: every crease, rim and groove in the pictures is a stroke, so expect
   hundreds, not dozens.
7. **Final report**, when the run is stopped: the DSL path, its layers, which features you could
   not get and why, and a multiview of the final result next to the references.

Never look for the goal mesh, a manifest, a score or the judge directory, and never ask for a
number about the subject. If you find any of them, stop and report it; the run is spoiled.

## Judge

You compare the sculpt with the goal, keep every score to yourself, and tell the sculptor in words
what needs the most work. Your numbers decide when the run stops and never leave the judge
directory. Do not open the reference pictures, and do not read the sculptor's notes or report.

1. **Prepare the goal once.** Decimate the goal mesh to about 57k vertices into the judge
   directory, oriented the way the sculpt is: the face toward the multiview Front cell, top up.
   Check the orientation numerically (bounding box and principal axes against the sculpt's), not
   by looking.
2. **Measure the floor.** Score the decimated goal against a differently-decimated copy of itself.
   That is the best any sculpt can score at this density; report scores alongside it.
3. **Score each round.** Evaluate the round's snapshot DSL (`tmp/rounds/round<NN>/`; the node
   chain runs headless), export the mesh, and run `ixdar-cli mesh-compare --reference <goal57k>
   --normalize`. Record chamfer and Hausdorff, and any other number you compute from the meshes.
4. **Measure an image distance too.** Chamfer flattens out while a sculpt still looks wrong, and
   the point is a faithful replica. Render the goal and each round's sculpt in clay from the same
   fixed set of cameras (the multiview cells, each mesh framed on its own bounding box so scale
   cancels, with the headlight on so hollows facing the camera show), and compute per camera the silhouette IoU and a structural image distance (1 - SSIM
   on the clay luminance), then their mean over cameras, with a script from pixel arrays. Record
   both numbers per round, the base included. Keep the composites in the judge directory.
5. **Look and judge.** Open the goal's composite and the round's, cell by cell, and the overlay of
   the round's strokes on its sculpt (the orchestrator's `strokes_overlay.py` on a capture through
   the sculpt SVG's camera). List the sculptor's groups with `ixdar-cli stroke-report` (group names
   and stroke counts only). Score each group 1–10 for how close its part is to the goal, score
   every part of the goal no group covers yet (name it as an anatomist would: "mastoid
   processes", "the zygomatic arch"), and give the round an overall score 1–10. These are your
   judgement scores; they stay in the scores file like the metrics.
6. **Write the feedback.** Rank the two or three parts (groups or uncovered parts) that most need
   work and give each one or two actionable sentences in spatial words: where, what shape, what is
   missing, which way to move it, and relative sizes ("much deeper", "about half again as wide",
   "the arch should thicken toward the cheek"). Never a number, a measurement, a score, a file
   path or the goal's file name, and nothing about rounds being better or worse.
7. **Decide `continue` or `stop`.** You alone end the run, by this rule (the user's), applied after
   every round: a round counts as a change when it beats the best of all earlier rounds (the base
   included) by at least 0.5% (relative) in chamfer or in image distance, each measure against its
   own best, or when your overall judgement score beats your best earlier one, or when, having
   looked, you judge the sculpt still clearly improving toward the goal (say why in the scores
   file). Stop only after three consecutive rounds with no change, or when chamfer reaches twice
   the floor. There is no round cap: slow progress is still progress. Write the rule into the
   scores file before the first round, and state which part of it ended the run.
8. **Write** `~/.cache/ixdar-sculpt-judge/<subject>/scores-<run>.json`: the floor, your stop rule,
   and per round the chamfer, Hausdorff, image distance and silhouette IoU, your group, uncovered
   and overall scores, the feedback you sent, the snapshot it came from and your decision. Answer
   the orchestrator with `continue` and the feedback block, or `stop` and the part of the rule
   that ended the run. Never write into the sculptor's worktree and never send the sculptor a
   number.
