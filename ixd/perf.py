"""Time a ticket's benchmarks in its worktree and on master, and refuse a regression.

A ticket names its benchmarks in ``perf-benchmarks`` (Maven ``-Dtest`` selectors, set with
``generate_board.py update ID --add-perf-benchmark CrawfishMeshRepairBenchmark``). Each selector
runs once in the worktree and twice on master's current commit, and the times surefire writes to
``target/surefire-reports/TEST-*.xml`` are compared.

The baseline checkout. Master's side never runs in the user's main checkout, whose ``target/`` the
IDE and the user's own builds own. It runs in ``<repo>/.claude/worktrees/.perf-baseline``, a
detached-HEAD worktree ixd creates on first use and moves to master's current commit before each
baseline run. Its name starts with a dot, which no ticket branch can, and it has no branch, so
``wt status``, ``wt done`` and ``land`` (which refuse a detached HEAD) and the snapshot hooks
(which only match ticket-shaped names) never take it for a ticket's worktree. It is ixd's own
scratch: a tracked change found in it refuses rather than being discarded, and its ``target/`` is
deleted whenever the commit moves, so no class of a removed source survives into a baseline. One
run at a time holds it, through a lock file; another waits.

Recorded baselines (``ixd/perf_records.py``). Before running master, each selector looks for a
record: ``ixd land`` records the landed ticket's measured worktree times as master's, and every
fresh baseline run is recorded too. The newest record taken on this machine, in master's history,
whose fingerprint of the files the benchmark reaches still matches master, is the baseline, and
master does not run for that selector. Otherwise master runs as below. ``--fresh-baseline`` skips
records and the cache. Each table row names its baseline's source: the ticket and commit of a
landed record, or ``fresh run <commit>``. ``tmp/<ticket>-perf.json`` beside the table holds the
machine-readable result, with the measured tree's fingerprint per selector, which ``land`` reads.

The cache. Baseline times are kept in ``~/.cache/ixd/perf-baseline/<master commit>.json``, one
entry per selector, so a second ticket or a rerun on the same master costs only the worktree run.

The noise rule. The two baseline runs give the baseline (their mean) and the noise (their spread,
``|run1 - run2|``); a recorded baseline carries its own mean and noise. A worktree time above the
baseline by more than ``max(noise, floor)`` is a
regression. The floor is two ticks of the clock surefire times with: surefire takes
``System.currentTimeMillis`` differences and rounds to the millisecond, and that clock advances in
steps of up to 1/64 s (15.625 ms, the default Windows timer interrupt), so each reading is off by up
to one tick and the difference of two readings by up to two. Two baseline runs that happen to agree
closely cannot shrink the threshold below what the clock can resolve.

Accepting a regression. As with named diagnostics, the ticket's definition of done decides: a line
``Accepts perf regression <Selector>: <reason>`` (case-insensitive, a non-empty reason required)
lets that benchmark be slower. A failing or erroring benchmark is never accepted, and a selector
master has no test for is reported as ``new`` and not compared.
"""

import fnmatch
import json
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from pathlib import Path

from . import perf_records, snapshots, worktree

PERF_BENCHMARKS = "perf-benchmarks"
BASELINE_SLOT = ".perf-baseline"
CACHE_DIR = Path.home() / ".cache" / "ixd" / "perf-baseline"
BASELINE_RUNS = 2
# Surefire's times come from System.currentTimeMillis, whose clock steps by up to 1/64 s.
CLOCK_TICK_SECONDS = 1 / 64
FLOOR_SECONDS = 2 * CLOCK_TICK_SECONDS
LOCK_NAME = ".ixd-perf.lock"
LOCK_POLL_SECONDS = 10
LOCK_STALE_SECONDS = 4 * 3600
MAIN_SOURCE = re.compile(r"(?:^|/)src/main/")
ACCEPT_MARKER = "accepts perf regression"
OUTPUT_TAIL = 3000

PASSED = "passed"
FAILED = "failed"
MISSING = "missing"
# Maven failed before any report was written: a compile error or the wrong JDK, nothing measured.
BROKEN = "broken"


@dataclass
class Run:
    """One selector's run: its status, the tests it ran, and their summed wall time."""

    status: str
    tests: int = 0
    seconds: float = 0.0
    detail: str = ""

    def as_json(self):
        return {"status": self.status, "tests": self.tests, "seconds": self.seconds, "detail": self.detail}


@dataclass
class Row:
    """One line of the table: a benchmark, both sides, and the verdict."""

    selector: str
    baseline: float | None
    current: float | None
    noise: float | None
    verdict: str
    detail: str = ""
    source: str = ""

    def change(self):
        if self.baseline is None or self.current is None or self.baseline == 0:
            return None
        return (self.current - self.baseline) / self.baseline


def selectors_of(ticket):
    """The ticket's perf-benchmarks selectors, in order.

    :param ticket: the parsed ticket, possibly empty
    :return: the selectors
    """
    return list((ticket or {}).get(PERF_BENCHMARKS) or [])


def main_sources_changed(path, commit):
    """The paths the worktree changes from ``commit`` that sit under some module's ``src/main``.

    :param path: the worktree directory
    :param commit: master's commit, which the change is measured from (committed or not)
    :return: repository-relative paths, untracked files included
    """
    tracked = worktree.git(path, "diff", "--name-only", commit).splitlines()
    untracked = worktree.git(path, "ls-files", "--others", "--exclude-standard").splitlines()
    return [name for name in tracked + untracked if MAIN_SOURCE.search(name)]


def accepted_regressions(definition_of_done):
    """The selectors the definition of done accepts a regression for, each with a reason.

    :param definition_of_done: the ticket's DoD text, possibly empty
    :return: {lower-cased selector: reason}
    """
    found = {}
    pattern = re.compile(re.escape(ACCEPT_MARKER) + r"\s+(\S+?)\s*:\s*(\S[^\n]*)", re.IGNORECASE)
    for match in pattern.finditer(definition_of_done or ""):
        found[match.group(1).lower()] = match.group(2).strip()
    return found


def run_selector(directory, selector, log):
    """Run one selector with Maven and read its tests' times from the surefire reports.

    :param directory: the checkout to run in
    :param selector: a Maven ``-Dtest`` selector, such as ``Ring*Benchmark#cold``
    :param log: file the Maven output is written to
    :return: the :class:`Run`
    """
    started = time.time()
    result = subprocess.run(
        worktree.resolved(["mvn", "-q", "test", f"-Dtest={selector}"]),
        cwd=str(directory),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    class_pattern, _, method_pattern = selector.partition("#")
    run = Run(PASSED)
    broken = []
    for report in directory.glob("*/target/surefire-reports/TEST-*.xml"):
        if report.stat().st_mtime < started:
            continue
        for case in ElementTree.parse(report).getroot().iter("testcase"):
            simple = str(case.get("classname", "")).rsplit(".", 1)[-1]
            if not fnmatch.fnmatchcase(simple, class_pattern):
                continue
            if method_pattern and not fnmatch.fnmatchcase(str(case.get("name", "")), method_pattern):
                continue
            run.tests += 1
            run.seconds += float(case.get("time", 0) or 0)
            for kind in ("failure", "error"):
                problem = case.find(kind)
                if problem is not None:
                    broken.append(
                        f"{case.get('name')}: {kind} {(problem.get('message') or '').strip()[:300]}"
                    )
    if broken:
        run.status, run.detail = FAILED, "; ".join(broken)
    elif run.tests == 0:
        tail = (result.stderr or result.stdout).strip()[-OUTPUT_TAIL:]
        if result.returncode != 0:
            run.status, run.detail = BROKEN, f"maven exited {result.returncode} with no report: {tail}"
        else:
            run.status, run.detail = MISSING, "no test matched"
    elif result.returncode != 0:
        run.status, run.detail = FAILED, f"maven exited {result.returncode}; see {log}"
    return run


def baseline_path(path):
    """The baseline checkout of the repository a worktree belongs to.

    :param path: any worktree of the repository
    :return: ``<main checkout>/.claude/worktrees/.perf-baseline``
    """
    return worktree.main_checkout_of(path) / ".claude" / "worktrees" / BASELINE_SLOT


def prepare_baseline(path, commit):
    """Create the baseline checkout, or move it to ``commit``, clearing its build when it moves.

    :param path: any worktree of the repository
    :param commit: master's current commit
    :return: the baseline directory
    """
    main = worktree.main_checkout_of(path)
    slot = baseline_path(path)
    if not (slot / ".git").exists():
        if slot.exists():
            raise SystemExit(f"{slot} exists but is not a worktree; delete it so ixd can recreate it")
        print(f"== perf baseline: creating {slot} at {commit[:8]}")
        worktree.git(main, "worktree", "add", "--detach", str(slot), commit)
        return slot
    dirty = worktree.git(slot, "status", "--porcelain", "--untracked-files=no")
    if dirty and not worktree.git(slot, "diff", "HEAD", "--ignore-cr-at-eol", check=False):
        # The baseline's own build regenerates tracked files (the node catalog, the automation
        # routes) and rewrites their line endings. Their content still matches HEAD, so nothing
        # is lost by putting them back.
        print(f"== perf baseline: discarding line-ending-only changes its build made\n{dirty}")
        worktree.git(slot, "checkout", "--quiet", "--", ".")
        dirty = worktree.git(slot, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise SystemExit(
            f"the perf baseline {slot} holds tracked changes, which ixd never makes; it is left as it "
            f"is. Look at them, then remove it with `git worktree remove --force {slot}` so ixd recreates it.\n{dirty}"
        )
    if worktree.git(slot, "rev-parse", "HEAD") != commit:
        print(f"== perf baseline: moving {slot.name} to {commit[:8]} and clearing its target/")
        worktree.git(slot, "checkout", "--quiet", "--detach", commit)
        for target in slot.glob("*/target"):
            shutil.rmtree(target, ignore_errors=True)
        shutil.rmtree(slot / "target", ignore_errors=True)
    return slot


class BaselineLock:
    """Exclusive use of the baseline checkout, waiting while another perf run holds it."""

    def __init__(self, slot):
        self.file = slot.parent / (slot.name + LOCK_NAME)

    def __enter__(self):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        announced = False
        while True:
            try:
                handle = os.open(str(self.file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(handle, str(os.getpid()).encode())
                os.close(handle)
                return self
            except FileExistsError:
                if time.time() - self.file.stat().st_mtime > LOCK_STALE_SECONDS:
                    self.file.unlink(missing_ok=True)
                    continue
                if not announced:
                    print(f"== perf baseline: another run holds {self.file.name}; waiting")
                    announced = True
                time.sleep(LOCK_POLL_SECONDS)

    def __exit__(self, *_):
        self.file.unlink(missing_ok=True)


def cache_file(commit):
    return CACHE_DIR / f"{commit}.json"


def load_cache(commit):
    try:
        return json.loads(cache_file(commit).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_cache(commit, cache):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file(commit).write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")


def baseline_runs(path, commit, selectors, force=False):
    """Master's runs of each selector, from the cache or run twice in the baseline checkout.

    :param path: the worktree, which names the repository
    :param commit: master's current commit
    :param selectors: the selectors to time
    :param force: run every selector again, ignoring the cache
    :return: {selector: [Run, Run]}
    """
    cache = load_cache(commit)
    wanted = [selector for selector in selectors if force or not complete(cache.get(selector, []))]
    for selector in selectors:
        if selector not in wanted:
            print(f"== perf baseline: {selector} cached for {commit[:8]}")
    fresh = {}
    if wanted:
        slot = baseline_path(path)
        with BaselineLock(slot):
            prepare_baseline(path, commit)
            cache = load_cache(commit)
            for selector in wanted:
                runs = []
                for number in range(1, BASELINE_RUNS + 1):
                    print(f"== perf baseline: {selector} on {commit[:8]}, run {number} of {BASELINE_RUNS}")
                    log = slot / "tmp" / f"perf-{safe(selector)}-{number}.log"
                    runs.append(run_selector(slot, selector, log).as_json())
                    if runs[-1]["status"] in (MISSING, BROKEN):
                        break
                if any(run["status"] == BROKEN for run in runs):
                    # Maven itself failed (a build error, a wrong JDK): nothing was measured, so
                    # nothing is cached and the next run tries again.
                    fresh[selector] = runs
                    continue
                cache[selector] = runs
                save_cache(commit, cache)
    return {
        selector: [Run(**run) for run in fresh.get(selector) or cache[selector]] for selector in selectors
    }


def complete(runs):
    """Whether cached runs settle a selector: both runs measured, or master has no such test.

    :param runs: the cached runs, as JSON
    :return: True when nothing needs running again
    """
    statuses = [run.get("status") for run in runs]
    return BROKEN not in statuses and (len(runs) >= BASELINE_RUNS or MISSING in statuses)


safe = perf_records.safe


def compare(selector, master, current, accepted, recorded=None):
    """The table row for one benchmark.

    :param selector: the selector
    :param master: its baseline runs, empty when a record is the baseline
    :param current: its worktree run
    :param accepted: {lower-cased selector: reason} from the definition of done
    :param recorded: the record standing in for master's runs, if one applies
    :return: the :class:`Row`
    """
    if recorded is not None:
        baseline, noise = float(recorded["mean"]), float(recorded["noise"])
    else:
        measured = [run.seconds for run in master if run.status in (PASSED, FAILED) and run.tests]
        baseline = sum(measured) / len(measured) if len(measured) == len(master) and measured else None
        noise = max(measured) - min(measured) if baseline is not None else None
    note = "master fails it too; " if any(run.status == FAILED for run in master) else ""
    if current.status != PASSED:
        detail = current.detail if current.status != MISSING else "no test matched in the worktree"
        return Row(selector, baseline, current.seconds or None, noise, "FAIL", note + detail)
    if any(run.status == MISSING for run in master):
        return Row(selector, None, current.seconds, None, "new", "master has no such test; not compared")
    if note:
        # A failing run often stops early, so its time is no baseline; a change that makes the
        # benchmark pass is compared against nothing rather than against an aborted run.
        return Row(
            selector,
            None,
            current.seconds,
            None,
            "fixed",
            "master fails it; this change passes; not compared",
        )
    if baseline is None:
        broken = next((run.detail for run in master if run.status == BROKEN), "no baseline")
        return Row(selector, None, current.seconds, None, "FAIL", f"master's side did not run: {broken}")
    threshold = max(noise, FLOOR_SECONDS)
    if current.seconds - baseline <= threshold:
        return Row(selector, baseline, current.seconds, noise, "ok", note.rstrip("; "))
    reason = accepted.get(selector.lower())
    if reason:
        return Row(selector, baseline, current.seconds, noise, "accepted", note + reason)
    return Row(selector, baseline, current.seconds, noise, "REGRESSION", note.rstrip("; "))


def seconds_text(value):
    return "-" if value is None else f"{value:.3f}s"


def table(rows, commit):
    """The rows as a fixed-width text table, with the rule that judged them.

    :param rows: the compared rows
    :param commit: master's current commit
    :return: the table text
    """
    header = ("benchmark", "baseline", "worktree", "change", "noise", "verdict", "baseline source")
    lines = []
    for row in rows:
        change = row.change()
        lines.append(
            (
                row.selector,
                seconds_text(row.baseline),
                seconds_text(row.current),
                "-" if change is None else f"{change:+.1%}",
                seconds_text(row.noise),
                row.verdict,
                row.source or "-",
            )
        )
    widths = [max(len(str(cell)) for cell in column) for column in zip(header, *lines)]
    out = [
        f"perf: master is {commit[:8]}; a baseline is a landed ticket's recorded run (ticket, commit) or a",
        f"fresh run of master (the mean of {BASELINE_RUNS} runs, noise their spread); a regression is a worktree",
        f"time above the baseline by more than max(noise, {FLOOR_SECONDS * 1000:.2f} ms).",
        "  ".join(cell.ljust(width) for cell, width in zip(header, widths)),
        "  ".join("-" * width for width in widths),
    ]
    out += ["  ".join(cell.ljust(width) for cell, width in zip(line, widths)) for line in lines]
    notes = [f"  {row.selector}: {row.detail}" for row in rows if row.detail]
    if notes:
        out += ["notes:"] + notes
    return "\n".join(out)


def recorded_baselines(path, commit, selectors):
    """The records that stand in for master's runs, printing each selector's source or why none.

    :param path: the worktree
    :param commit: master's current commit
    :param selectors: the selectors
    :return: {selector: record} for the selectors a record covers
    """
    found = {}
    for selector in selectors:
        record, reason = perf_records.recorded_baseline(path, commit, selector)
        if record is None:
            print(f"== perf baseline: {selector}: {reason}; running master")
            continue
        found[selector] = record
        print(
            f"== perf baseline: {selector} from {perf_records.describe(record)} ({record['mean']:.3f}s, "
            f"noise {record['noise']:.3f}s, recorded {record.get('date')} on {record.get('machine')}); "
            f"master not run"
        )
    return found


def record_fresh_runs(path, commit, master, ticket_id):
    """Record each selector master measured cleanly, so the next check reuses it.

    A pair that did not both pass, or whose spread is above ``NOISY_FRACTION`` of its mean (a
    loaded machine), is left unrecorded.

    :param path: the worktree
    :param commit: master's commit the runs timed
    :param master: {selector: [Run, Run]}
    :param ticket_id: the ticket whose check ran them
    """
    for selector, runs in master.items():
        if len(runs) < BASELINE_RUNS or any(run.status != PASSED or not run.tests for run in runs):
            continue
        seconds = [run.seconds for run in runs]
        mean, noise = sum(seconds) / len(seconds), max(seconds) - min(seconds)
        if mean and noise > perf_records.NOISY_FRACTION * mean:
            print(
                f"== perf record: {selector} not recorded: spread {noise:.3f}s of {mean:.3f}s, a loaded machine"
            )
            continue
        fingerprint, files = perf_records.reach(path, commit, selector)
        record = perf_records.new_record(
            selector,
            perf_records.FRESH,
            ticket_id,
            commit,
            mean,
            noise,
            len(runs),
            runs[0].tests,
            (fingerprint, len(files)),
        )
        target = perf_records.append_record(path, record)
        print(f"== perf record: {selector} {mean:.3f}s (fresh run {commit[:8]}) in {target}")


def write_sidecar(path, branch, ticket_id, commit, measured_tree, rows, current):
    """Save the result as JSON beside the table, with what ``land`` needs to record it.

    :param path: the worktree
    :param branch: its branch
    :param ticket_id: the ticket
    :param commit: master's commit when measured
    :param measured_tree: the tree of the worktree's files the runs measured
    :param rows: the compared rows
    :param current: {selector: Run} of the worktree
    """
    data = {
        "ticket": ticket_id,
        "master": commit,
        "tree": measured_tree,
        "machine": perf_records.machine(),
        "date": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "rows": [
            {
                "selector": row.selector,
                "verdict": row.verdict,
                "baseline": row.baseline,
                "current": row.current,
                "noise": row.noise,
                "source": row.source,
                "tests": current[row.selector].tests,
                "fingerprint": perf_records.reach(path, measured_tree, row.selector)[0],
            }
            for row in rows
        ],
    }
    target = perf_records.sidecar_path(path, branch)
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def check(path, branch, fresh_baseline=False, benchmarks=()):
    """Time the ticket's benchmarks against master, print and save the table, refuse on a problem.

    Refuses when the diff touches a module's ``src/main`` and the ticket names no benchmarks, when
    a benchmark fails, errors or matches no test in the worktree, and when one regresses without
    an ``Accepts perf regression <Selector>: <reason>`` line in the definition of done.

    :param path: the worktree directory
    :param branch: its branch, whose upper-cased name is the ticket id
    :param fresh_baseline: run master's side again, ignoring the records and the cache
    :param benchmarks: selectors to time instead of the ticket's perf-benchmarks
    :return: the rows, when nothing refused
    """
    ticket = worktree.ticket_for(branch) or {}
    ticket_id = ticket.get("id", branch.upper())
    selectors = list(benchmarks) or selectors_of(ticket)
    commit = worktree.git(path, "rev-parse", worktree.main_branch_of(path))
    touched = main_sources_changed(path, commit)
    if not selectors:
        if touched:
            listing = "\n".join(f"  {name}" for name in touched[:20])
            raise SystemExit(
                f"perf: the diff changes {len(touched)} file(s) under src/main and {ticket_id} names no "
                f"perf-benchmarks.\n{listing}\nAdd the benchmarks that cover the change (the "
                f"ixdar-app/test/benchmark/ classes exercising the code you touched): generate_board.py "
                f"update {ticket_id} --add-perf-benchmark <Selector>"
            )
        print("== perf: no src/main change and no perf-benchmarks; skipped")
        return []
    measured_tree = snapshots.tree_of(path)
    if measured_tree is None:
        raise SystemExit(f"perf: could not write {path}'s files as a tree to fingerprint what is measured")
    current = {}
    for selector in selectors:
        print(f"== perf worktree: {selector}")
        log = path / "tmp" / f"{branch}-perf-{safe(selector)}.log"
        current[selector] = run_selector(path, selector, log)
    recorded = {} if fresh_baseline else recorded_baselines(path, commit, selectors)
    unrecorded = [selector for selector in selectors if selector not in recorded]
    master = baseline_runs(path, commit, unrecorded, force=fresh_baseline) if unrecorded else {}
    record_fresh_runs(path, commit, master, ticket_id)
    accepted = accepted_regressions(ticket.get("definition-of-done", ""))
    rows = []
    for selector in selectors:
        record = recorded.get(selector)
        row = compare(selector, master.get(selector, []), current[selector], accepted, record)
        row.source = perf_records.describe(record) if record else f"fresh run {commit[:8]}"
        rows.append(row)
    text = table(rows, commit)
    print(text)
    saved = path / "tmp" / f"{branch}-perf.txt"
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text(text + "\n", encoding="utf-8")
    write_sidecar(path, branch, ticket_id, commit, measured_tree, rows, current)
    print(f"== perf: table saved to {saved}")
    failed = [row.selector for row in rows if row.verdict == "FAIL"]
    regressed = [row.selector for row in rows if row.verdict == "REGRESSION"]
    if failed or regressed:
        problems = []
        if failed:
            problems.append(
                f"{', '.join(failed)} failed, errored, ran no test or could not run on master (see the "
                f"notes; a failure is never accepted: fix the code, the selector or the build)"
            )
        if regressed:
            problems.append(
                f"{', '.join(regressed)} regressed; make it fast again, or when the cost is meant, "
                f"accept it: generate_board.py update {ticket_id} --append-definition-of-done "
                f'"Accepts perf regression <Selector>: <reason>"'
            )
        raise SystemExit("perf refused: " + "; ".join(problems))
    return rows
