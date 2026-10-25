---
name: crawfish-segment
description: >
  Segment a crawfish scan (IMG_4112 to IMG_4118) into named body parts with the ring scene, to
  the quality of the user's hand-segmented references IMG_4109, IMG_4110 and IMG_4111, and judge
  a finished segmentation. Two roles: the segmenter, which works one scan in its own worktree,
  and the judge, a separate adversarial agent that decides whether the segmenter has finished.
  Use when briefing or acting as either role for CRAW-76 or a per-scan segmentation ticket.
---

# Crawfish segmentation

Read this whole file before acting, then follow the section for your role. Everything about keys,
modes and control rows comes from the CLI, not from here: `ixdar-cli tools` lists every tool in
the scene, its controls with their action ids, and its modes; every `key`, `click` and `control`
reply says what took the input and what the tool did. If you find yourself needing a fact about
controls that the CLI does not give you, stop and report it as a CLI gap; do not guess and do not
write it into this skill.

## The scans

- References, hand-segmented by the user (read only, never modify, never save over):
  - `IMG_4109`: `ixdar-app/src/main/resources/dsl/fixtures/crawfish_rings.dsl`
  - `IMG_4110`: `ixdar-app/src/main/resources/dsl/crawfish/IMG_4110.dsl`
  - `IMG_4111`: `ixdar-app/src/main/resources/dsl/crawfish/IMG_4111.dsl` (it also has bisectors)
- Work: `IMG_4112` to `IMG_4118`, each `ixdar-app/src/main/resources/dsl/crawfish/IMG_41xx.dsl`,
  which today holds only the load and repair statements.
- A segmentation is the rings (and bisectors) that split the surface into regions, and the part
  name each region carries (`add_label` statements, written by the ring scene's save).

## Rules for both roles

- One crawfish scene takes about 4 GB. Run at most one scene JVM at a time yourself, and only
  while you need it; never run `mvn test` while a scene is up; shut every scene down with
  `ixdar-cli shutdown` (or `--pid`) and confirm it is gone before you hand back. The machine
  allows two crawfish scenes in total, so the segmenter and the judge take turns.
- Drive the scene only through `ixdar-cli`: `tools`, `control --action <id>`, `key`, `click`
  (screen x,y in window pixels; `--mods shift` to add to a selection), `hover`, `words`,
  `ui-state`, `pick`, `project`, `frame`, `orbit-get`/`orbit-set`, `screenshot`, `multiview`,
  `terminal --line`, `model --path`. Read state from replies and `ui-state`/`tools` first;
  screenshots are for judging shape, not for reading numbers.
- Never edit a DSL by hand. Rings, bisectors and part names are made in the scene and written by
  its save action; `model --path <file>` only reopens a file to check what was saved.
- Never drive a scene you did not start, and never touch another agent's worktree.

## Segmenter

You own one scan, in the worktree your ticket names. Save only that scan's
`dsl/crawfish/IMG_41xx.dsl` there; nothing else under `dsl/` changes.

1. **Learn the part list from the references.** Open each reference in the ring scene in turn
   (`run-scene --scene ring-tool --property ixdar.model=<reference path> --keep-alive`),
   switch to the region tool through `control`, and read the region items in `tools`. Look at
   the regions with `frame`, `multiview` and `screenshot`. Write down, in `tmp/parts.md`, each
   body part the references separate (carapace, claws and their segments, walking-leg segments,
   antennae, tail segments, tail fan, ...), which ring boundaries make it, and how the three
   references agree or differ. Shut each reference scene down before the next.
2. **Segment your scan** in the ring scene on your scan's DSL. Make the rings (and bisectors
   where the references have them) that give the same parts. Use what `tools` offers: hover
   previews, crease-mode rings that follow grooves, anchors you add and drag, bisectors between
   rings. Check each ring in the reply and the region items before going on.
3. **Name every part.** Select a region (`terminal --line "sel <region numbers or part name>"`
   selects and frames; `click --mods shift` adds a region), then name it with
   `ixdar-cli terminal --line "lb <name>"`, using the names from `tmp/parts.md` (snake_case,
   sided `_left`/`_right`, numbered from the body outwards). Every region that is a real part
   gets a name; slivers between rings are removed by fixing the rings, not named.
4. **Check flatness.** Each region item in `tools` carries `values`: `creaseShare`,
   `interiorCreaseShare`, `peakCurvature`, `peakOverSaturation`, `creasePoint`,
   `creaseInterior`. A part should be flat inside, with its creases on its rings (a finger is
   flat except at its joints). A region with `creaseInterior` true and a high
   `interiorCreaseShare` usually has an unsplit joint at `creasePoint`: ring it. Single-ring tips
   (claw fingers) read a few percent interior from their own clefts; regions bounded by many
   rings (the body) can hide a joint, so look at them.
5. **Save and verify.** Fire the scene's save action through `control`, then
   `model --path <your DSL>` and confirm the rings and part names came back.
6. **Hand to the judge.** Write `tmp/segmenter-report.md`: the part list, which parts you could
   not find on this scan and why, anything you are unsure of, and the commands you used. Shut
   your scene down. The judge's verdict comes back as `tmp/judge-<round>.md`; fix what it asks
   and hand back again. Stop after the round limit in your ticket and report.

## Judge

You decide whether the segmenter has finished. Be adversarial: your job is to find what is wrong,
not to approve. Do not read the segmenter's reasoning or transcript; read only its saved DSL, its
`tmp/segmenter-report.md` part list, and the scenes themselves. Start your scene only after the
segmenter has shut its own down.

1. **Your own part list.** Build it from the references the way the segmenter's step 1 does,
   independently, before you look at the candidate. Keep it in `tmp/judge-parts.md`.
2. **Parts.** Open the candidate DSL in the ring scene. For each part on your list: is there a
   region with that name, is it one region (not split, not merged with a neighbour), and does its
   boundary sit where the references put it? List missing, extra, merged, split and misnamed
   parts.
3. **Blind A/B.** For a sample of parts and whole-body views, capture the candidate and one
   reference from matching camera poses (`orbit-get`/`orbit-set`, `frame`, `multiview`,
   `screenshot`), with ring numbers and part names hidden (through the controls `tools` lists).
   Present each pair to yourself unlabelled, in a random order you write down before you look,
   and pick which one is the hand-segmented reference. Record your picks, then reveal. If you
   cannot tell them apart, the candidate passes that view; if you pick the reference easily, say
   what gave it away.
4. **Flatness.** Read every region's `values`. Flag regions with `creaseInterior` true and a high
   `interiorCreaseShare` compared with the same part in the references, with the `creasePoint`.
   Skip slivers (they read near 100% crease); fix them as a parts problem instead.
5. **Verdict.** Write `tmp/judge-<round>.md`: `finished` or `continue`, then each problem as one
   actionable line (part, what is wrong, where: a surface point or region number, and what to
   do), the A/B picks and their result, and the flatness flags. Shut your scene down.

## Rollout

The pilot is IMG_4112 alone; the user reviews it and this skill is fixed before the other six go
out, two at a time.
