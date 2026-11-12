---
name: body-plan
description: >
  Research a subject's anatomy and write its body plan for Ixdar: a .dsl of one body_plan statement
  naming segmented scans and a tree of body_part slots, each slot a label pattern the scans' part
  labels fill. Checks the plan against the labels the scans already carry. Use when asked for a
  body plan, when adding a subject (an animal, a hand, a figure) to the body plan tool, or when
  reading or writing body_plan or body_part statements.
---

# Body plans

A body plan says what parts a subject is made of and how they hang together, so the body plan tool
(ring scene, ctrl+B) can lead the user through picking, for every slot, one labelled part from
several segmented scans, and then join the picks into one mesh. Your job is the plan, not the
picking: the user picks.

Ports, defaults and node docs come from `docs/mesh-node-catalog.json` (`body_plan`, `body_part`),
not from here. If you need a fact neither gives you, stop and report it as a gap.

## 1. Research the anatomy

Work out the subject's parts before looking at any label. Use what you know, and search the web
when the subject is not common knowledge or the user asks for a specific taxon or reference. Write
down, in your report, the source of every structural claim (a reference page, a textbook name, or
"general knowledge").

- Name the major body regions first (for a crayfish: cephalothorax and abdomen; for a hand: palm
  and digits), then what attaches to each, then the segments of each appendage in order from the
  body outward.
- Decide what is one part and what is a chain. A chain is a run of segments, each attached to the
  previous one: an arthropod leg's segments, a finger's phalanges, an abdomen's segments. Each
  segment of a chain is its own slot whose parent is the segment before it.
- Count paired and repeated parts exactly: four pairs of walking legs, six abdominal segments,
  five fingers. Every instance gets its own slot.
- Leave out what no scan could show (internal organs, parts finer than the scan resolution) and
  say so in the report.

## 2. Read the labels the scans carry

The plan is checked against the scans' existing segmentations, never the other way round: the
plan does not ask anyone to relabel a scan.

- Every scan is a .dsl ending in its `add_label(...)` statements (see the mesh-segment skill).
  List each scan's label names with `grep -o 'label="[^"]*"'` over the file.
- Note how the segmenters named things: which token carries the side (`left`, `right`), which the
  instance number, which suffixes split a part into pieces (`carapace_left`, `tail_segment_2_upper`).
- Scans disagree. One scan has `claw_left_merus`, another `claw_left_merus_upper` and
  `claw_left_merus_lower`. The slot's pattern must take every spelling a scan uses for that part.

## 3. Write the plan

The file goes next to the scans' own .dsl files, `<subject>/body_plan.dsl` under
`ixdar-app/src/main/resources/dsl/`. Open it with `#` comments summarising the anatomy and naming
the sources, then:

```
plan = body_plan(scans="dsl/<subject>/A.dsl; dsl/<subject>/B.dsl; dsl/<subject>/C.dsl", mirror_axis="Z")
torso = body_part(parent=plan.geometry, labels="torso; torso_*", choice="")
arm_left_upper = body_part(parent=torso.geometry, labels="arm_left_upper", choice="")
arm_left_lower = body_part(parent=arm_left_upper.geometry, labels="arm_left_lower; arm_left_lower_*", choice="")
arm_right_upper = body_part(parent=torso.geometry, labels="arm_right_upper", choice="", mirror_of=arm_left_upper.geometry)
arm_right_lower = body_part(parent=arm_right_upper.geometry, labels="arm_right_lower; arm_right_lower_*", choice="", mirror_of=arm_left_lower.geometry)
```

- `scans`: the segmented scans, `;`-separated, as paths the loader resolves (checkout- or
  resource-relative). At least three scans when the subject has them.
- `mirror_axis`: the axis across which the subject's left and right are mirror images in the scans'
  frame (X, Y or Z). Check it on a scan: a left part's coordinate on that axis has the opposite
  sign of its right partner's.
- One `body_part` per slot. The first slot's `parent` is `plan.geometry`; every other slot's parent
  is the part it attaches to. The slots form a tree, and the statement order is the order the tool
  walks: parent before child, and a chain's segments in order from the body outward.
- Parent slots follow the scans' segmentation: a child is placed by the boundary its scan cut it
  from its parent along, so make a slot's parent the part its labels actually border in the scans
  (a leg cut off the head shield hangs from the head shield, not the carapace). A child from the
  parent's own scan with no shared boundary stays where that scan put it.
- `mirror_of=<left slot>.geometry` on every right-side slot of a pair: while its choice is empty it
  takes its partner's part reflected, so the user chooses each pair once; a choice of its own breaks
  the symmetry and clearing it restores it. Midline parts (torso, tail segments) are single slots,
  and a midline part a scan split into halves is one slot whose pattern takes both halves
  (`carapace; carapace_*`).
- `choice=""` on every slot: the tool writes the user's picks there.
- Statement ids are the slot names, lower case with `_`, distinct from every label pattern's
  wildcards.

### Label patterns

A pattern is label tokens joined by `_`, with `;` separating alternatives:

| Token | Matches | Use |
|---|---|---|
| a word | that token | `telson` |
| `#` | one all-digit token; candidates with different numbers stay separate | `walking_leg_left_#_segment_1` |
| `*` | one or more tokens; everything it matches stays in one candidate | `carapace_*` takes `carapace_left` and `carapace_right` together |
| `left`, `right` | either side; a part from the other side is mirrored across `mirror_axis` | `eye_left` also offers every `eye_right`, reflected |

Numbers and sides are interchangeable on purpose: every left walking leg slot offers every walking
leg of every scan, right legs mirrored, and the user picks which fills which. So give the slots of
one repeated part the same pattern (`walking_leg_left_#_segment_1` for all four left first
segments), not one pattern per number.

Add alternatives for every spelling a scan uses: `claw_left_merus; claw_left_merus_*` takes a whole
merus in one scan and its upper and lower pieces in another.

## 4. Check the plan

Load it and read what the tool sees:

```
uv run ixdar-cli run-scene --scene ring-tool --mesh <path to body_plan.dsl> --keep-alive
uv run ixdar-cli body-plan
uv run ixdar-cli shutdown
```

`body-plan` lists every slot with its candidates (scan, labels, mirrored) and `missing_in`, the
scans with no part for it.

- A slot with no candidates at all can never be filled, and the plan can never finish: fix its
  pattern against the labels, or, when no scan has the part, remove the slot and say so.
- A slot missing in some scans is fine. List those slots in the report so the user knows where
  the choice is narrow.
- A candidate that gathers labels it should not (a `*` swallowing a neighbouring part) means the
  pattern is too loose: tighten it.
- Loading several scans takes a few GiB of heap and tens of seconds. Every chosen slot cuts its
  part again on load, so a filled plan loads more slowly.

## 5. Report

Report the plan's path, the anatomy with its sources, the tree (one line per slot: id, parent,
pattern, candidate count, scans missing it), what you left out and why, and every pattern you had
to widen for a scan's spelling.
