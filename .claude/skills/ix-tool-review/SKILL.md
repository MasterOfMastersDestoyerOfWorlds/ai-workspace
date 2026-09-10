---
name: ix-tool-review
description: >
  Review the tools agents used in a session (Bash, ixdar-cli, wt, generate_board, automation
  routes, MCP tools) and write a prioritised, numbered checklist report of what was funky,
  worked around, repeated, hard to find, or missing. Use after a session or a batch of agents
  finishes, or whenever the user asks "how did the agents spend their time", "what tools do we
  need", or invokes /ix-tool-review. Never creates tickets.
---

# Tool review

Produce `reports/tool-review-<YYYY-MM-DD>.md` in the ai-workspace repo (add `-2`, `-3` if
the date is taken). The report is evidence-based: every item cites a transcript, a command,
or a file. It records problems and proposals only. Do not create tickets, do not change
tools, do not fix anything while reviewing. If a finding was already resolved during the
reviewed session, tick its box and say where; everything else stays unticked for the user to
turn into tickets.

## Scope

Default scope is the current session plus every subagent it spawned. `/ix-tool-review <id>`
reviews that session; `/ix-tool-review --latest N` reviews the N newest. Transcripts live in
`~/.claude/projects/<project-slug>/<session>.jsonl` and
`~/.claude/projects/<project-slug>/<session>/subagents/agent-*.jsonl`; large tool outputs
that were spilled to disk are in `~/.claude/projects/<project-slug>/<session>/tool-results/`.

## Procedure

1. **Numbers first.** Run the statistics script on every transcript in scope:

   ```bash
   ixd stats --session <session-id>
   ```

   It prints wall time by activity, thinking time and the longest pauses, the slowest calls, error results, calls that completed
   with no output, retries, and the most repeated Bash command shapes. Put its activity table
   (per agent and total) at the top of the report. The single biggest number is usually the
   single biggest finding; explain it before anything else.

2. **Read the transcripts for the story behind each number.** For every slow call, error,
   silent completion, retry cluster, and repeated shape, find out what the agent was trying to
   do, what it believed the tool did, and what the tool actually did. Read the tool's source
   or `--help` when the two disagree. Note the exact command and the transcript it came from.

3. **Inventory the tools the agents could have used.** `uv run ixdar-cli --help` and the
   subcommand help, `ixdar_automation_cli/automation_routes.json`, `wt --help`,
   `generate_board.py --help`, the repo CLAUDE.md files, and the MCP/Claude tools available in
   the session. For each finding, check whether a tool already existed that would have avoided
   the workaround. "It exists but nobody found it" is a discoverability finding, not a
   missing-tool finding.

4. **Answer every question below**, each as its own section, even if the answer is "nothing
   found" (say so in one line). Do not pad; an empty section is fine.

## Questions

- **Time.** Where did wall time go: waiting, polling, building, restarting, thinking, reading?
  Which waits were avoidable (wrong port, wrong path, fixed sleeps, timeouts hit)?
- **Thinking.** How much time passed between a result and the next call, and where were the
  long pauses? A long pause before an edit or a new file means the plan or ticket left the
  agent to work something out; a long pause after a tool result means the output was hard to
  read. Report the longest pauses with what the agent did next and whether the ticket, the
  CLAUDE.md, or the tool's output could have made it obvious.
- **Funky tools.** Which tools behaved differently from what the agent assumed, and what was
  the workaround? Include silent failures: commands that returned no output or exit 0 while the
  intended effect did not happen.
- **Rapid-succession chains.** Which tool sequences recur (shutdown, copy, restart, poll,
  screenshot, read image) and deserve one higher-level command?
- **Findability.** Did `--help`, CLAUDE.md, or the route list lead to the right tool? Where did
  the agent read source code, guess flags, or try several variants (pytest vs unittest) to
  discover how to run something?
- **Repeated ad-hoc scripts.** Which Bash one-liners, Python heredocs, `for` loops, or `sed -i`
  edits appear again and again, here or across agents, and should become a tool or a flag?
- **CLI simplification.** Which commands need too many flags, need the same flags every time,
  or have defaults that are always overridden?
- **Post-processing.** Which tool outputs were piped through `grep`, `tail`, `python -c`,
  `jq`, or loops because the tool does not expose the right information or formats it badly?
  Which outputs were always truncated with `| tail` and should be quiet by default? Which
  needed more information than they gave?
- **Missing tools.** What did the agent need that nothing provided?
- **Permission friction.** Which calls were denied or avoided because of the deny list, and
  what did the agent do instead?
- **State leaks.** Which tools mutate fixtures, resources, or the running scene so that a
  later run is not clean (files the tool writes into `src/main/resources`, `target/classes`
  drifting from source, scenes left running, ports left bound)?
- **Verification cost.** How much did each verify loop cost (rebuild, restart, screenshot, read
  image) and what would cut it (hot reload, a probe route returning numbers instead of pixels,
  a readiness wait built into the launcher)?
- **Cross-agent repetition.** Workarounds that show up in more than one agent's transcript.
  These outrank single-agent findings.

## Report format

```markdown
# Tool review <date>

Scope: session <id> (<title>), agents: <label> (<wall>), ...

## Time
| activity | wall min | calls | agent |
...
One paragraph on the biggest cost, then one paragraph each on thinking and on the verify loop.

## Findings
- [ ] **1.** (time) <one-line finding>. Evidence: <agent label>, `<command or file>`.
  <One or two sentences: what happened, what the tool should do instead.>
- [x] **2.** (funky) ... Resolved in session: <where>.
- [ ] **3.** (chains) ...
```

Rules for items:

- **One flat list, in numeric order from 1 down the page.** Number 1 is the highest-priority
  item in the report; numbers increase as priority falls, and the list is printed in that order
  so the reader can find any number by scrolling. Never split items into per-question sections:
  the question each item answers goes in the parenthesised tag after the number (`time`,
  `thinking`, `funky`, `chains`, `findability`, `scripts`, `cli`, `post`, `missing`,
  `permission`, `state`, `verify`, `cross`). Assign numbers only after every finding is collected.
- Answer every question from the list above somewhere in the findings; if a question produced
  nothing, say so in one line under a short "Questions with nothing found" note after the list.
- Priority is by wall time lost times how often it will recur. A 40-minute one-off ranks
  below a 30-second cost paid by every agent every session only if the one-off cannot recur.
- `[x]` only when the fix already landed in the reviewed session; name the file or command.
  `[ ]` means it needs a ticket; do not create the ticket.
- Each item names the concrete tool, route, or script and says what it should do instead.
  "Improve the CLI" is not an item. Prefer changing the default behaviour over adding a flag:
  a flag is only right when both behaviours are wanted.
- Keep each item to three lines. Put long evidence (command listings, timelines) in an
  appendix at the end, referenced by item number.

Finish by telling the user the report path, the top three items, and how many items are
ticked versus open.
