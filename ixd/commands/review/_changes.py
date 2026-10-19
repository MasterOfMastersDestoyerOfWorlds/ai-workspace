"""What a worktree's change touches, read from its diff against its base, for `ixd review`.

The diff is the one ``stage-moves`` reads: everything from the change's start commit (the stack
fork, or the merge base with the base branch) to the working tree, untracked files included, built
in a scratch index so the worktree's own index is never touched. Which hunks are mechanical
(renames, imports naming a moved class, comment-only Java files) is decided by
:func:`ixd.worktree.move_patch`, and which hunks repeat one edit by :func:`ixd.clusters.cluster`;
this module only counts and labels what those leave.
"""

import re
from dataclasses import dataclass, field

from ... import clusters as hunk_clusters
from ... import worktree as wt

HUNK_HEADER = wt.HUNK_HEADER
DIFF_HEADER = wt.DIFF_HEADER
change_diff = wt.change_diff
sections_of = wt.sections_of
# A public or protected method or constructor declaration line, up to its opening parenthesis.
SIGNATURE = re.compile(
    r"^\s*(?:@\w+(?:\([^)]*\))?\s+)*(public|protected)\s+((?:[\w$<>\[\],.?& ]+?\s+)?)([\w$]+)\s*\("
)
# A public or protected field declaration line, up to its initialiser or semicolon.
FIELD = re.compile(
    r"^\s*(?:public|protected)\s+(?:(?:static|final|volatile|transient)\s+)*[\w$<>\[\],.?]+\s+[\w$]+\s*(?=[=;])"
)
TYPE_KEYWORDS = re.compile(r"\b(class|interface|enum|record|@interface)\b")
JAVA_ROOTS = ("/java/", "/test/")


@dataclass
class FileChange:
    """One file of the diff: its paths, how it changed, and its non-mechanical hunks."""

    old: str
    new: str
    kind: str  # "added", "deleted", "renamed" or "modified"
    changed_lines: int = 0
    real_lines: int = 0
    # Real lines outside every cluster: what is left to read once the repeated edits are read once.
    unclustered_lines: int = 0
    first_real_line: int | None = None
    binary: bool = False
    added: list = field(default_factory=list)
    removed: list = field(default_factory=list)


@dataclass
class Change:
    """The whole change: where it starts and what each file does."""

    start: str
    base: str
    files: list
    clustering: object = None


def signature_of(line):
    """A public/protected method, constructor or field declared on this line, normalised, or None."""
    field_match = FIELD.match(line)
    if field_match:
        return " ".join(field_match.group(0).split())
    if TYPE_KEYWORDS.search(line.split("(", 1)[0]) or "=" in line.split("(", 1)[0]:
        return None
    match = SIGNATURE.match(line)
    if not match:
        return None
    text = line.strip().rstrip("{").strip()
    text = re.sub(r"^(?:@\w+(?:\([^)]*\))?\s+)+", "", text)
    return " ".join(text.split())


def read_change(worktree, base):
    """The change in a worktree: every file, its real (non-mechanical) lines, and its signatures.

    :param worktree: the worktree directory
    :param base: its base branch
    :return: a :class:`Change`
    """
    start, diff = change_diff(worktree, base)
    mechanical_patch = wt.move_patch(diff)[0]
    mechanical = {
        header[0]: {hunk[0] for hunk in hunks} | ({"*"} if not hunks else set())
        for header, hunks in sections_of(mechanical_patch)
    }
    clustering = hunk_clusters.cluster(diff, hunk_clusters.worktree_source(worktree, start), start)
    clustered = {(hunk.header[0], hunk.lines[0]) for item in clustering.clusters for hunk in item.hunks}
    files = []
    for header, hunks in sections_of(diff):
        names = DIFF_HEADER.match(header[0])
        if not names:
            continue
        old, new = names.groups()
        for line in header:
            if line.startswith("rename from "):
                old = line[len("rename from ") :]
            elif line.startswith("rename to "):
                new = line[len("rename to ") :]
        kind = "modified"
        if any(line.startswith("new file mode") for line in header):
            kind = "added"
        elif any(line.startswith("deleted file mode") for line in header):
            kind = "deleted"
        elif any(line.startswith("rename from ") for line in header):
            kind = "renamed"
        change = FileChange(old=old, new=new, kind=kind)
        change.binary = any(line.startswith(("Binary files", "GIT binary")) for line in header)
        skip = mechanical.get(header[0], set())
        first_clustered = None
        for hunk in hunks:
            lines = [line for line in hunk[1:] if line[:1] in "+-"]
            change.changed_lines += len(lines)
            if hunk[0] in skip:
                continue
            change.real_lines += len(lines)
            if (header[0], hunk[0]) in clustered:
                position = HUNK_HEADER.match(hunk[0])
                first_clustered = first_clustered or (max(int(position.group(3)), 1) if position else 1)
                continue
            change.unclustered_lines += len(lines)
            if change.first_real_line is None:
                position = HUNK_HEADER.match(hunk[0])
                change.first_real_line = max(int(position.group(3)), 1) if position else 1
        change.first_real_line = change.first_real_line or first_clustered
        if new.endswith(".java") or old.endswith(".java"):
            for hunk in hunks:
                for line in hunk[1:]:
                    signature = signature_of(line[1:]) if line[:1] in "+-" else None
                    if signature:
                        (change.added if line[0] == "+" else change.removed).append(signature)
            added, removed = set(change.added), set(change.removed)
            change.added = sorted(added - removed)
            change.removed = sorted(removed - added)
        files.append(change)
    return Change(start=start, base=base, files=files, clustering=clustering)


def java_type(path):
    """(package, class name) a .java path declares, read from its source-root-relative path."""
    posix = "/" + path
    for root in JAVA_ROOTS:
        if root in posix:
            posix = posix.split(root, 1)[1]
            break
    parts = posix.strip("/").split("/")
    return ".".join(parts[:-1]), parts[-1].removesuffix(".java")


def boundaries(change):
    """(added classes, deleted classes, {(old package, new package): [classes]}, signature changes).

    Classes are (package, name); signature changes are (path, added signatures, removed ones) for
    every Java file that gained or lost a public or protected declaration.
    """
    added, deleted, moved, signatures = [], [], {}, []
    for item in change.files:
        if item.kind == "added" and item.new.endswith(".java"):
            added.append(java_type(item.new))
        elif item.kind == "deleted" and item.old.endswith(".java"):
            deleted.append(java_type(item.old))
        elif item.kind == "renamed" and item.new.endswith(".java"):
            old_package, old_name = java_type(item.old)
            new_package, new_name = java_type(item.new)
            label = new_name if old_name == new_name else f"{old_name} -> {new_name}"
            moved.setdefault((old_package, new_package), []).append(label)
        if item.kind != "deleted" and (item.added or item.removed) and item.kind != "added":
            signatures.append((item.new, item.added, item.removed))
    return sorted(added), sorted(deleted), moved, signatures


def is_supporting(path):
    """Whether a path is a test or the editor's launch configuration rather than the change itself."""
    posix = "/" + path
    return "/test/" in posix or "/tests/" in posix or path.endswith(("Test.java", "launch.json"))


def read_first(change):
    """(files with unclustered real lines, most first; files whose real lines are all in clusters;
    files whose changes are all mechanical).

    A line in a cluster is read once, through the cluster, so it does not make a file worth
    opening. Source files come before tests and launch.json, which say how the change was checked
    rather than what it is. Deleted files are left out: there is nothing to open, and the
    boundaries list them.
    """
    live = [item for item in change.files if item.kind != "deleted"]
    real = sorted(
        (item for item in live if item.unclustered_lines),
        key=lambda item: (is_supporting(item.new), -item.unclustered_lines, item.new),
    )
    clustered_only = sorted(
        (item for item in live if item.real_lines and not item.unclustered_lines),
        key=lambda item: (-item.real_lines, item.new),
    )
    mechanical = sorted((item for item in live if not item.real_lines), key=lambda item: item.new)
    return real, clustered_only, mechanical
