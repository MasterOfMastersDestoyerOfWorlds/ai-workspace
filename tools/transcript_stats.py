#!/usr/bin/env python3
"""Summarise how agents spent their time and which tools they used, from Claude Code transcripts.

    transcript_stats.py <transcript.jsonl>...          one or more session/subagent transcripts
    transcript_stats.py --session <id>                 the session plus every subagent under it
    transcript_stats.py --latest [N]                   the N most recent sessions (default 1)

Prints, per transcript and in total: wall time, tool-call counts, wall time by activity
category (attributed to the call that started it, so it includes the model's thinking before
the next call), the slowest calls, calls whose result was an error, calls that completed with
no output, consecutive retries of the same command shape, and the most repeated Bash command
shapes (paths, numbers and quoted strings normalised). Read-only; used by /ix-tool-review.
"""
import argparse
import collections
import datetime
import json
import re
import sys
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"

CATEGORIES = [
    ("scene run/restart/wait", r"run-scene|shutdown|/health|ixdar-cli health"),
    ("build/test", r"\bmvn\b|teavm|pytest|unittest|checkstyle"),
    ("scene drive (hover/click/key/screenshot)", r"ixdar-cli (hover|click|key|screenshot|multiview|orbit|ui-state|probe)"),
    ("ixdar-cli other", r"ixdar-cli"),
    ("tickets", r"generate_board"),
    ("git/wt", r"^\s*(cd [^&]*&& )?(git|wt) "),
    ("edit via shell", r"python3? - <<|sed -i|cat > |tee |patch "),
    ("read/search via shell", r"^\s*(cd [^&]*&& )?(cat|sed -n|grep|rg|ls|head|tail|wc|find|diff|pdfinfo|which|for f)"),
]


def load_calls(path):
    """[(start, name, input, id, end, result_text, is_error)] in transcript order."""
    calls, results, seen = [], {}, set()
    for line in open(path, encoding="utf-8"):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        stamp = event.get("timestamp")
        when = datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")) if stamp else None
        content = (event.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "tool_use":
                if block["id"] in seen:
                    continue  # transcripts can repeat events after a context compaction
                seen.add(block["id"])
                calls.append([when, block["name"], block.get("input", {}), block["id"]])
            elif block.get("type") == "tool_result":
                text = block.get("content")
                if isinstance(text, list):
                    text = " ".join(part.get("text", "") for part in text if isinstance(part, dict))
                results[block["tool_use_id"]] = (when, str(text or ""), bool(block.get("is_error")))
    out = []
    for start, name, inp, call_id in calls:
        end, text, error = results.get(call_id, (None, "", False))
        out.append((start, name, inp, call_id, end, text, error))
    return out


def category(name, inp):
    if name != "Bash":
        return {"Edit": "edit tool", "Write": "edit tool", "Read": "read tool"}.get(name, name)
    command = inp.get("command", "")
    for label, pattern in CATEGORIES:
        if re.search(pattern, command):
            return label
    return "bash other"


def shape(command):
    """Normalise a command so repeats with different paths/numbers/strings group together."""
    s = re.sub(r"'[^']*'|\"[^\"]*\"", "STR", command)
    s = re.sub(r"<<'?\w+'?.*", "<<HEREDOC", s, flags=re.S)
    s = re.sub(r"/[\w./-]+", "/PATH", s)
    s = re.sub(r"\b\d+\b", "N", s)
    return re.sub(r"\s+", " ", s).strip()[:140]


def summarise(path, calls, top, idle):
    stamps = [c[0] for c in calls if c[0]] + [c[4] for c in calls if c[4]]
    if not stamps:
        print(f"{path}: no timestamped tool calls")
        return collections.Counter(), collections.Counter()
    wall = max(stamps) - min(stamps)
    print(f"\n=== {path}")
    print(f"wall {wall}  tool calls {len(calls)}  "
          + "  ".join(f"{n} {k}" for k, n in collections.Counter(c[1] for c in calls).most_common()))

    def describe(name, inp):
        text = inp.get("command") if name == "Bash" else (inp.get("file_path") or inp.get("pattern") or "")
        return str(text).replace("\n", " | ")[:150]

    by_cat, run_cat, n_cat = collections.Counter(), collections.Counter(), collections.Counter()
    rows = []
    for i, (start, name, inp, _, end, text, error) in enumerate(calls):
        nxt = calls[i + 1][0] if i + 1 < len(calls) and calls[i + 1][0] else end or start
        span = (nxt - start).total_seconds() if start and nxt else 0
        run = (end - start).total_seconds() if start and end else 0
        # A result recorded after the next call started (background agents, plan approval,
        # questions to the user) is waiting on someone else, not this tool running.
        run = min(run, span)
        cat = category(name, inp)
        if span - run > idle:
            # A long gap after the tool returned is the user (or a parent) being away, not
            # this tool's cost; count it separately so activity totals stay honest.
            by_cat["idle (gap > idle threshold)"] += span - run
            n_cat["idle (gap > idle threshold)"] += 1
            span = run
        by_cat[cat] += span
        run_cat[cat] += run
        n_cat[cat] += 1
        rows.append((run, span, name, inp, text, error))
    print("\nwall time by activity (span = until the next call, run = the tool itself):")
    for cat, span in by_cat.most_common():
        print(f"  {span/60:6.1f} min span  {run_cat[cat]/60:6.1f} min run  {n_cat[cat]:4d} calls  {cat}")

    pauses = sorted(((span - run, name, inp) for run, span, name, inp, _, _ in rows), key=lambda r: -r[0])
    think = sum(p for p, _, _ in pauses)
    print(f"\nthinking: {think/60:.1f} min between results and the next call "
          f"({think/max(len(rows),1):.0f}s mean); longest pauses and the call they led to:")
    for pause, name, inp in pauses[:top]:
        print(f"  {pause:6.0f}s  {name:6} {describe(name, inp)}")

    print(f"\nslowest {top} calls (run time):")
    for run, _, name, inp, _, _ in sorted(rows, key=lambda r: -r[0])[:top]:
        print(f"  {run:6.0f}s  {name:6} {describe(name, inp)}")
    errors = [(name, inp, text) for _, _, name, inp, text, error in rows if error]
    print(f"\nerror results: {len(errors)}")
    for name, inp, text in errors[:top]:
        print(f"  {name:6} {describe(name, inp)}\n         -> {text.strip()[:150]!r}")
    silent = [(name, inp) for _, _, name, inp, text, _ in rows if name == "Bash" and "completed with no output" in text]
    print(f"\nbash calls that completed with no output: {len(silent)}")
    for name, inp in silent[:top]:
        print(f"  {describe(name, inp)}")
    shapes = collections.Counter(shape(inp.get("command", "")) for _, _, name, inp, _, _ in rows if name == "Bash")
    print(f"\nmost repeated bash command shapes:")
    for s, n in shapes.most_common(top):
        if n > 1:
            print(f"  {n:3d}x  {s}")
    retries = 0
    previous = None
    for _, _, name, inp, _, _ in rows:
        current = shape(inp.get("command", "")) if name == "Bash" else None
        if current and current == previous:
            retries += 1
        previous = current
    print(f"\nconsecutive same-shape bash calls (retries or loops): {retries}")
    return by_cat, n_cat


def resolve(args):
    paths = [Path(p) for p in args.transcripts]
    if args.session:
        for project in PROJECTS.iterdir():
            main = project / f"{args.session}.jsonl"
            if main.exists():
                paths.append(main)
                paths += sorted((project / args.session / "subagents").glob("agent-*.jsonl"))
    if args.latest:
        sessions = sorted(PROJECTS.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime)[-args.latest:]
        for main in sessions:
            paths.append(main)
            paths += sorted((main.parent / main.stem / "subagents").glob("agent-*.jsonl"))
    return paths


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("transcripts", nargs="*")
    parser.add_argument("--session", help="session id; includes its subagents")
    parser.add_argument("--latest", type=int, nargs="?", const=1, help="N most recent sessions with subagents")
    parser.add_argument("--top", type=int, default=12, help="rows per list")
    parser.add_argument("--idle", type=float, default=600,
                        help="seconds of gap after a result that count as idle, not activity (default 600)")
    args = parser.parse_args(argv)
    paths = resolve(args)
    if not paths:
        raise SystemExit("no transcripts given")
    total_cat, total_n = collections.Counter(), collections.Counter()
    for path in paths:
        by_cat, n_cat = summarise(path, load_calls(path), args.top, args.idle)
        total_cat.update(by_cat)
        total_n.update(n_cat)
    if len(paths) > 1:
        print("\n=== all transcripts, wall time by activity:")
        for cat, span in total_cat.most_common():
            print(f"  {span/60:6.1f} min  {total_n[cat]:4d} calls  {cat}")


if __name__ == "__main__":
    main(sys.argv[1:])
