"""Time a worktree's benchmarks against master."""

from typing import Annotated

from ... import perf as perf_check
from ... import worktree
from ...registry import CliOption, cli_command


@cli_command
def perf(
    worktree_name: Annotated[str, CliOption(positional=True)] = "",
    fresh_baseline: bool = False,
    benchmark: Annotated[list[str], CliOption(multiple=True)] = (),
) -> int:
    """Run the ticket's perf-benchmarks in the worktree, compare with master's baseline, refuse a regression.

    The same check ``wt done`` runs after the build and the named tests; this never marks or
    changes the ticket. The benchmarks are the ticket's ``perf-benchmarks`` (Maven ``-Dtest``
    selectors, set with ``generate_board.py update ID --add-perf-benchmark
    CrawfishMeshRepairBenchmark``). A diff that touches any module's ``src/main`` with none named
    refuses: add the benchmarks that cover the change.

    Each selector runs once in the worktree. Its baseline is the newest recorded one that still
    holds: ``ixd land`` records each landed ticket's measured times as master's, and each fresh
    baseline run is recorded too, in ``<ticket store>/perf/<repository>/<selector>.jsonl``. A
    record holds when it was taken on this machine, its commit is in master's history, and no file
    the benchmark reaches (the classes it imports, transitively, the poms, the resources it names)
    has changed on master since; then master is not run at all. Otherwise master runs twice on its
    current commit, in the detached baseline worktree ``.claude/worktrees/.perf-baseline`` that ixd
    creates and keeps on master (never the main checkout), cached per commit and selector under
    ``~/.cache/ixd/perf-baseline/``, and that run is recorded. The output says which: the ticket and
    commit of the record, or ``fresh run <commit>``, with the reason a record did not hold.

    The baseline is the mean of master's two runs and the noise their spread (a record carries
    both); a worktree time above the baseline by more than the noise, or by two clock ticks
    (31.25 ms) when that is larger, is a regression. A benchmark that fails or errors fails the
    check; one master has no test for is ``new`` and not compared. The table (benchmark, baseline,
    worktree, change, noise, verdict, baseline source) is printed and saved to
    ``tmp/<ticket>-perf.txt``, and as JSON to ``tmp/<ticket>-perf.json``, which ``land`` records.

    A regression refuses unless the definition of done accepts it with a line
    ``Accepts perf regression <Selector>: <reason>``; failures are never accepted.

    :param worktree_name: worktree path or bare name, defaulting to the one holding the current directory
    :param fresh_baseline: run master twice again, ignoring the records and the cache, and record that run
    :param benchmark: a selector to time instead of the ticket's perf-benchmarks (repeatable)
    """
    path, branch, _ = worktree.resolve_worktree(worktree_name)
    perf_check.check(path, branch, fresh_baseline=fresh_baseline, benchmarks=benchmark)
    return 0
