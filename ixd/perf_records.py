"""Recorded perf baselines: each landed ticket's benchmark times, reused as master's baseline.

``ixd land`` writes the numbers the landed ticket's last ``wt perf`` or ``wt done`` measured in its
worktree: after the land that code is master, so its times are master's. ``wt perf`` then takes a
benchmark's baseline from the newest record instead of running master twice, and runs master fresh
(recording that run too) only when no record applies.

Where the records live. One JSON-lines file per benchmark selector,
``<ticket store>/perf/<repository>/<selector>.jsonl``, newest line last. The ticket store, not the
measured repository, because both writers need it: ``land`` knows the landed commit only after the
squash commit exists, so the record cannot sit inside that commit, and the fresh baseline runs agents
make from ``wt perf`` can never be committed to master by them. The ticket store is the shared,
tracked place ``land`` already writes to (the DONE mark), so ``git log -p perf/`` there shows each
ticket's numbers next to its ticket history.

A record (one line): ``selector``, ``source`` (``landed`` or ``fresh``), ``ticket``, ``commit``
(the landed commit, or master's commit a fresh run timed), ``mean`` and ``noise`` in seconds,
``runs``, ``tests``, ``machine``, ``date``, ``fingerprint`` and ``files``. A landed record's mean is
the worktree's single run and its noise the spread of the two master runs it was compared against,
the noise of that benchmark on that machine; a fresh record's mean and noise are its two runs' mean
and spread. A fresh pair whose spread exceeds a quarter of its mean (a loaded machine) is not
recorded.

When a record applies. Three checks, newest record first, the first that passes all three is used:

- same machine: ``platform.node()`` must equal the record's ``machine``;
- in master's history: the record's commit must be an ancestor of master's current commit;
- unchanged code: the record's ``fingerprint`` must equal the fingerprint master's commit has now.

The fingerprint is a hash of every file the benchmark can reach, read from a commit's tree (or,
when ``wt perf`` measures, from the worktree's files written as a tree through a temporary index):
the class the selector names and, transitively, every class it imports or names from its own
package (Java imports and same-package simple names, read from the source text), every ``pom.xml``,
every file under a ``src/main/resources`` directory, and the other non-Java files whose
module-relative path, or whose directory's, appears in the text of a reached class (the mesh a
benchmark loads). So a later land that changes what a benchmark exercises without naming that
benchmark makes its record stale, and ``wt perf`` names the reached files that changed. Classes
reached only by reflection are not seen; ``--fresh-baseline`` reruns master regardless.

``land`` checks the same fingerprint before writing: the worktree's measured tree against the
landed commit, so a land whose sync took in another ticket's change to the benchmark's code, or an
edit made after the last measurement, records nothing for that benchmark.
"""

import datetime
import hashlib
import json
import platform
import re
import subprocess
from pathlib import Path

from . import worktree

RECORD_DIR = worktree.TICKET_REPO / "perf"
LANDED = "landed"
FRESH = "fresh"
# A fresh pair spread wider than this share of its mean was timed on a loaded machine.
NOISY_FRACTION = 0.25
IMPORT = re.compile(r"^\s*import\s+(static\s+)?([\w.]+?)(\.\*)?\s*;", re.MULTILINE)
PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
TYPE_NAME = re.compile(r"\b[A-Z]\w*\b")
SHOWN_CHANGES = 3


def safe(selector):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", selector)


def machine():
    """The name records compare machines by."""
    return platform.node() or "unknown"


def records_file(path, selector):
    """The record file of one selector of the repository ``path`` belongs to.

    :param path: any checkout of the repository
    :param selector: the Maven ``-Dtest`` selector
    :return: ``<ticket store>/perf/<repository>/<selector>.jsonl``
    """
    return RECORD_DIR / worktree.main_checkout_of(path).name / f"{safe(selector)}.jsonl"


def read_records(path, selector):
    """The selector's records, oldest first; unreadable lines are skipped.

    :param path: any checkout of the repository
    :param selector: the selector
    :return: the records as dictionaries
    """
    try:
        lines = records_file(path, selector).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def append_record(path, record):
    """Add one record as the newest line of its selector's file.

    :param path: any checkout of the repository
    :param record: the record, holding at least ``selector``
    :return: the file written
    """
    target = records_file(path, record["selector"])
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return target


def new_record(selector, source, ticket, commit, mean, noise, runs, tests, reach, when=None, where=None):
    """A record ready to append.

    :param selector: the selector
    :param source: ``landed`` or ``fresh``
    :param ticket: the ticket id that landed, or whose ``wt perf`` ran the fresh baseline
    :param commit: the landed commit, or master's commit the fresh run timed
    :param mean: seconds
    :param noise: seconds
    :param runs: how many runs the mean is of
    :param tests: tests the selector ran
    :param reach: the (fingerprint, file count) of the measured code
    :param when: ISO time of the measurement, now by default
    :param where: the machine, this one by default
    :return: the record
    """
    return {
        "selector": selector,
        "source": source,
        "ticket": ticket,
        "commit": commit,
        "mean": round(mean, 4),
        "noise": round(noise, 4),
        "runs": runs,
        "tests": tests,
        "machine": where or machine(),
        "date": when or datetime.datetime.now().isoformat(timespec="seconds"),
        "fingerprint": reach[0],
        "files": reach[1],
    }


def tree_blobs(path, treeish):
    """Every file of a tree with its blob id.

    :param path: any checkout of the repository
    :param treeish: a commit or tree id
    :return: {repository-relative path: blob id}
    """
    listing = worktree.git(path, "ls-tree", "-r", "-z", "--full-tree", treeish)
    blobs = {}
    for entry in listing.split("\0"):
        if not entry:
            continue
        meta, _, name = entry.partition("\t")
        parts = meta.split()
        if len(parts) == 3 and parts[1] == "blob":
            blobs[name] = parts[2]
    return blobs


def blob_texts(path, ids):
    """The contents of blobs, read in one ``git cat-file --batch``.

    :param path: any checkout of the repository
    :param ids: blob ids
    :return: {blob id: text}
    """
    unique = list(dict.fromkeys(ids))
    result = subprocess.run(
        ["git", "-C", str(path), "cat-file", "--batch"],
        input=("\n".join(unique) + "\n").encode(),
        capture_output=True,
        check=True,
    )
    out, texts, offset = result.stdout, {}, 0
    for blob in unique:
        header_end = out.index(b"\n", offset)
        header = out[offset:header_end].split()
        size = int(header[2]) if len(header) == 3 else 0
        texts[blob] = out[header_end + 1 : header_end + 1 + size].decode("utf-8", errors="replace")
        offset = header_end + 1 + size + 1
    return texts


def module_of(name, modules):
    """The module directory a repository path sits in, or "" for the root.

    :param name: repository-relative path
    :param modules: directories holding a ``pom.xml``
    :return: the deepest module directory holding the path
    """
    best = ""
    for module in modules:
        if module and name.startswith(module + "/") and len(module) > len(best):
            best = module
    return best


def reach(path, treeish, selector):
    """The files a benchmark can reach in a tree, and their fingerprint.

    :param path: any checkout of the repository
    :param treeish: a commit or tree id
    :param selector: the selector, whose class part (before ``#``) may hold wildcards
    :return: (fingerprint, the reached files sorted)
    """
    blobs = tree_blobs(path, treeish)
    java = {name: blob for name, blob in blobs.items() if name.endswith(".java")}
    texts = blob_texts(path, java.values())
    classes, by_package = {}, {}
    for name, blob in java.items():
        found = PACKAGE.search(texts[blob])
        package = found.group(1) if found else ""
        simple = Path(name).stem
        classes[f"{package}.{simple}"] = name
        by_package.setdefault(package, {})[simple] = name
    pattern = selector.partition("#")[0]
    start = [name for name in java if re.fullmatch(_glob(pattern), Path(name).stem)]
    reached, stack = set(start), list(start)
    while stack:
        name = stack.pop()
        for found in _references(texts[java[name]], classes, by_package):
            if found not in reached:
                reached.add(found)
                stack.append(found)
    modules = {name.rpartition("/")[0] for name in blobs if name.rpartition("/")[2] == "pom.xml"}
    reached_text = "\n".join(texts[java[name]] for name in reached)
    for name in blobs:
        if name.endswith(".java"):
            continue
        if name.rpartition("/")[2] == "pom.xml" or "src/main/resources/" in f"/{name}":
            reached.add(name)
            continue
        module = module_of(name, modules)
        relative = name[len(module) + 1 :] if module else name
        directory = relative.rpartition("/")[0]
        if relative in reached_text or (directory and f'"{directory}' in reached_text):
            reached.add(name)
    files = sorted(reached)
    digest = hashlib.sha256("\n".join(f"{name} {blobs[name]}" for name in files).encode()).hexdigest()
    return digest, files


def _glob(pattern):
    return "".join(".*" if char == "*" else "." if char == "?" else re.escape(char) for char in pattern)


def _references(text, classes, by_package):
    """The source files a Java file imports or names from its own package."""
    body = COMMENT.sub(" ", text)
    words = set(TYPE_NAME.findall(body))
    found = PACKAGE.search(text)
    own = by_package.get(found.group(1) if found else "", {})
    out = {own[word] for word in words if word in own}
    for match in IMPORT.finditer(text):
        name, star = match.group(2), match.group(3)
        if star and name in by_package:
            out |= {by_package[name][word] for word in words if word in by_package[name]}
            continue
        parts = name.split(".")
        for index in range(len(parts), 0, -1):
            candidate = ".".join(parts[:index])
            if candidate in classes:
                out.add(classes[candidate])
                break
    return out


def is_ancestor(path, older, newer):
    result = subprocess.run(
        ["git", "-C", str(path), "merge-base", "--is-ancestor", older, newer], capture_output=True
    )
    return result.returncode == 0


def recorded_baseline(path, commit, selector, here=None):
    """The newest record that still holds for master's commit, or why none does.

    :param path: any checkout of the repository
    :param commit: master's current commit
    :param selector: the selector
    :param here: the machine to match, this one by default
    :return: (record or None, reason text when None)
    """
    here = here or machine()
    records = read_records(path, selector)
    if not records:
        return None, "no recorded baseline"
    current, stale, elsewhere = None, None, []
    for record in reversed(records):
        if record.get("machine") != here:
            elsewhere.append(record.get("machine"))
            continue
        if not record.get("commit") or not is_ancestor(path, record["commit"], commit):
            continue
        if current is None:
            current = reach(path, commit, selector)
        if record.get("fingerprint") == current[0]:
            return record, ""
        stale = stale or record
    if stale is not None:
        changed = worktree.git(path, "diff", "--name-only", stale["commit"], commit).splitlines()
        touched = sorted(set(changed) & set(current[1]))
        shown = ", ".join(touched[:SHOWN_CHANGES]) + (
            f" and {len(touched) - SHOWN_CHANGES} more" if len(touched) > SHOWN_CHANGES else ""
        )
        return None, (
            f"the record from {describe(stale)} is stale: {len(touched)} file(s) the benchmark reaches "
            f"changed since ({shown or 'its reach changed'})"
        )
    if elsewhere:
        return None, f"recorded only on another machine ({', '.join(sorted(set(elsewhere)))}), not {here}"
    return None, "no recorded baseline in master's history"


def describe(record):
    """``CRAW-144 c1f8a49e`` for a landed record, ``fresh run c1f8a49e`` for a fresh one."""
    commit = str(record.get("commit", ""))[:8]
    if record.get("source") == LANDED:
        return f"{record.get('ticket')} {commit}"
    return f"fresh run {commit}"


def sidecar_path(path, branch):
    return path / "tmp" / f"{branch}-perf.json"


def record_landing(path, branch, landed):
    """Record the numbers the worktree's last perf check measured as master's, now it has landed.

    Reads ``tmp/<branch>-perf.json``, which every ``wt perf`` and ``wt done`` writes beside the
    table. A row is recorded when its verdict is ``ok`` or ``accepted`` (so it has a noise to carry)
    and the code it measured is the code that landed: the fingerprint of the measured worktree tree
    must equal the landed commit's. Nothing here refuses; ``land`` calls it after the merge.

    :param path: the worktree, before its removal
    :param branch: its branch
    :param landed: the landed commit
    :return: the records written
    """
    sidecar = sidecar_path(path, branch)
    try:
        measured = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print(
            f"== perf record: no readable {sidecar.name} (no wt perf or wt done measured it); nothing recorded"
        )
        return []
    ticket = measured.get("ticket") or branch.upper()
    written = []
    for row in measured.get("rows", []):
        selector = row.get("selector")
        if row.get("verdict") not in ("ok", "accepted") or row.get("noise") is None:
            print(
                f"== perf record: {selector} not recorded (verdict {row.get('verdict')}, nothing to compare with)"
            )
            continue
        fingerprint, files = reach(path, landed, selector)
        if fingerprint != row.get("fingerprint"):
            print(
                f"== perf record: {selector} not recorded: the code it reaches differs between what "
                f"was measured and {landed[:8]} (an edit after the measurement, or the land's sync took "
                f"in another change); the next wt perf runs master fresh"
            )
            continue
        record = new_record(
            selector,
            LANDED,
            ticket,
            landed,
            row["current"],
            row["noise"],
            1,
            row.get("tests", 0),
            (fingerprint, len(files)),
            when=measured.get("date"),
            where=measured.get("machine"),
        )
        target = append_record(path, record)
        written.append(record)
        print(f"== perf record: {selector} {row['current']:.3f}s as {ticket} {landed[:8]} in {target}")
    return written
