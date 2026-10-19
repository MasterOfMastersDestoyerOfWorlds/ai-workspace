"""Group the hunks of a change by edit pattern, so a rewrite repeated in thirty files reads once.

A change like "replace 70 hand-built error objects with ``failure(msg)``" buries its few real code
changes under one edit made over and over. This module puts every hunk of the diff that is not
mechanical (``stage-moves`` owns renames, imports of moved classes and comment-only files) into a
cluster with the hunks that make the same edit, at the first of three levels that joins them:

  1. identical   the same removed and added lines once whitespace is collapsed (blank lines dropped)
  2. token       the same token-level rewrite once the tokens that differ are abstracted: a run of
                 tokens both sides share becomes ``$1``, ``$2``... (the message both
                 ``err.addProperty(ERROR, msg)`` and ``failure(msg)`` carry), local names become
                 ``$v1``, constants and literals ``$k1``; a removed declaration of a variable the
                 added side never names is part of the same edit and is dropped, and a statement
                 repeated with only its abstracted tokens changed counts once
  3. tree        the same edit read off the syntax tree (tree-sitter through ast-grep): each hunk is
                 widened to the whole statements it touches and read as leaf tokens classified by
                 the parser, so rewrapping, comments and a hunk that cuts a statement in half no
                 longer split a cluster; and a hunk adding the same statements as an established
                 pattern while removing a subsequence of its statements joins it, because the diff
                 cut that edit into two hunks

Hunks joined at any level are one cluster (union-find), labelled with the highest level it needed.
A cluster has at least two hunks; the rest are unclustered, which is what a reviewer reads.

ast-grep comes from the ``ast-grep-py`` package (prebuilt wheels for Linux, macOS and Windows), a
dependency of this project rather than a system tool; without it level 3 is skipped and says so.
"""

import difflib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import worktree as wt

MIN_CLUSTER = 2
# A hunk widened to whole statements may not grow past this many times its own lines (plus slack):
# a changed ``} else {`` would otherwise widen to the whole if-statement.
WIDEN_FACTOR = 3
WIDEN_SLACK = 6
TREE_LANGUAGES = {".java": "java", ".py": "python", ".js": "javascript", ".ts": "typescript"}
LEVEL_NAMES = {1: "identical", 2: "token rewrite", 3: "syntax tree"}

TOKEN = re.compile(
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|\d[\w.]*|[A-Za-z_$][\w$]*'
    r"|->|::|==|!=|<=|>=|&&|\|\||\+\+|--|\+=|-=|\*=|/=|<<|>>|\S"
)
KEYWORDS = frozenset(
    "abstract assert boolean break byte case catch char class const continue default do double else "
    "enum extends final finally float for goto if implements import instanceof int interface long "
    "native new package private protected public return short static strictfp super switch "
    "synchronized this throw throws transient try void volatile while var record yield true false "
    "null def lambda pass None True False self elif in is not and or from as with".split()
)
CONSTANT = re.compile(r"^[A-Z][A-Z0-9_]*$")
STATEMENT_END = frozenset({";", "{", "}"})
OPENERS = {"(": ")", "[": "]", "{": "}"}
CLOSERS = {value: key for key, value in OPENERS.items()}
EDGE_PUNCTUATION = frozenset({";", ","})
# Roles a token can have: kept as written, or abstracted to a numbered placeholder of its kind.
# Constants and literals share one placeholder kind: ``addProperty(ERROR, m)`` and
# ``addProperty("error", m)`` are the same edit.
KEEP, VARIABLE, CONST, LITERAL = "keep", "v", "k", "k"
STATEMENT_KINDS = frozenset(
    {
        "local_variable_declaration",
        "field_declaration",
        "constant_declaration",
        "import_declaration",
        "package_declaration",
        "explicit_constructor_invocation",
        "annotation_type_element_declaration",
        "enum_constant",
        "expression_statement",
        "return_statement",
        "throw_statement",
        "assignment",
        "import_statement",
        "import_from_statement",
        "lexical_declaration",
        "variable_declaration",
    }
)
LITERAL_KINDS = frozenset(
    {
        "string_literal",
        "character_literal",
        "text_block",
        "decimal_integer_literal",
        "hex_integer_literal",
        "decimal_floating_point_literal",
        "string",
        "integer",
        "float",
        "number",
        "template_string",
    }
)
COMMENT_KINDS = frozenset({"line_comment", "block_comment", "comment"})
IDENTIFIER_KINDS = frozenset({"identifier", "property_identifier", "shorthand_property_identifier"})


@dataclass
class Hunk:
    """One ``-U0`` hunk: the file it belongs to, its lines and where they sit on each side."""

    number: int
    header: list
    lines: list
    old_path: str
    new_path: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int

    @property
    def removed(self):
        return [line[1:] for line in self.lines[1:] if line.startswith("-")]

    @property
    def added(self):
        return [line[1:] for line in self.lines[1:] if line.startswith("+")]

    @property
    def size(self):
        return len(self.removed) + len(self.added)

    @property
    def path(self):
        return self.new_path if self.new_path != "/dev/null" else self.old_path

    @property
    def line(self):
        """The line a reader opens: the hunk's first line in the new file (at least 1)."""
        return max(self.new_start + (1 if self.new_count == 0 else 0), 1)

    def covers(self, line):
        """Whether a new-file line number falls on this hunk (or right beside a pure deletion)."""
        if self.new_count == 0:
            return line in (self.new_start, self.new_start + 1)
        return self.new_start <= line < self.new_start + self.new_count


@dataclass
class Cluster:
    """Hunks that make the same edit, the level that joined them, and the pattern they share."""

    number: int
    level: int
    hunks: list
    pattern: tuple = ()
    representative: Hunk | None = None

    @property
    def files(self):
        counts = {}
        for hunk in self.hunks:
            counts[hunk.path] = counts.get(hunk.path, 0) + 1
        return counts

    @property
    def lines(self):
        return sum(hunk.size for hunk in self.hunks)


@dataclass
class Clustering:
    """Every hunk of the change, sorted into clusters, unclustered hunks and mechanical ones."""

    start: str
    hunks: list
    clusters: list
    unclustered: list
    mechanical: int
    tree_note: str = ""
    by_hunk: dict = field(default_factory=dict)

    def cluster_of(self, hunk):
        return self.by_hunk.get(hunk.number)


def hunk_range(header):
    """(old start, old count, new start, new count) of a ``@@`` line."""
    match = wt.HUNK_HEADER.match(header)
    if not match:
        raise ValueError(f"not a hunk header: {header}")
    old_start, old_count, new_start, new_count = match.groups()
    return (
        int(old_start),
        1 if old_count is None else int(old_count),
        int(new_start),
        1 if new_count is None else int(new_count),
    )


def file_paths(header):
    """(old path, new path) of one file's diff header, ``/dev/null`` for an added or deleted side."""
    names = wt.DIFF_HEADER.match(header[0])
    old, new = names.groups() if names else ("", "")
    for line in header:
        if line.startswith("rename from "):
            old = line[len("rename from ") :]
        elif line.startswith("rename to "):
            new = line[len("rename to ") :]
        elif line.startswith("new file mode"):
            old = "/dev/null"
        elif line.startswith("deleted file mode"):
            new = "/dev/null"
    return old, new


def hunks_of(diff):
    """Every textual hunk of a diff, numbered in diff order; binary files have none."""
    found = []
    for header, hunks in wt.sections_of(diff):
        if any(line.startswith(("Binary files", "GIT binary")) for line in header):
            continue
        old, new = file_paths(header)
        for lines in hunks:
            found.append(Hunk(len(found), header, lines, old, new, *hunk_range(lines[0])))
    return found


def mechanical_keys(diff):
    """(file header line, hunk header) of every hunk ``stage-moves`` stages as mechanical."""
    return {
        (header[0], hunk[0]) for header, hunks in wt.sections_of(wt.move_patch(diff)[0]) for hunk in hunks
    }


def lexical_tokens(lines):
    """(text, role) tokens of source lines, roles guessed from spelling: the token level's view.

    A lower-case name not followed by ``(`` or preceded by ``.`` is a local, an ALL_CAPS name a
    constant, a quoted or numeric token a literal; method names, members, types, keywords and
    punctuation are kept as written. Comment lines are dropped.
    """
    texts = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(("//", "/*", "*", "#")):
            continue
        texts += TOKEN.findall(stripped)
    tokens = []
    for index, text in enumerate(texts):
        after = texts[index + 1] if index + 1 < len(texts) else ""
        before = texts[index - 1] if index else ""
        tokens.append((text, lexical_role(text, before, after)))
    return tokens


def lexical_role(text, before, after):
    """The role of one token from its spelling and its neighbours."""
    if text[0] in "\"'" or text[0].isdigit():
        return LITERAL
    if not (text[0].isalpha() or text[0] in "_$") or text in KEYWORDS or before == "." or after == "(":
        return KEEP
    if CONSTANT.match(text) and len(text) > 1:
        return CONST
    if text[0].islower() or text[0] == "_":
        return VARIABLE
    return KEEP


def balanced_core(run):
    """A shared token run trimmed of edge separators and of brackets it does not close itself."""
    start, end = 0, len(run)
    changed = True
    while changed and start < end:
        changed = False
        if run[start][0] in EDGE_PUNCTUATION:
            start, changed = start + 1, True
        elif run[end - 1][0] in EDGE_PUNCTUATION:
            end, changed = end - 1, True
        else:
            texts = [text for text, _ in run[start:end]]
            for closer, opener in CLOSERS.items():
                if texts[-1] == closer and texts.count(closer) > texts.count(opener):
                    end, changed = end - 1, True
                    break
                if texts[0] == opener and texts.count(opener) > texts.count(closer):
                    start, changed = start + 1, True
                    break
    return start, end


def shared_runs(minus, plus):
    """Mark the runs of tokens both sides carry with one placeholder each, in place.

    Only a run holding a name or a literal counts: a shared ``(`` or ``return`` says nothing.
    """
    matcher = difflib.SequenceMatcher(None, [t for t, _ in minus], [t for t, _ in plus], autojunk=False)
    runs = []
    for left, right, size in matcher.get_matching_blocks():
        if not size:
            continue
        start, end = balanced_core(minus[left : left + size])
        if any(meaningful(token) for token in minus[left + start : left + end]):
            runs.append((left + start, left + end, right + start, right + end))
    minus_out, plus_out = list(minus), list(plus)
    for number, (left_start, left_end, right_start, right_end) in reversed(list(enumerate(runs, 1))):
        token = (f"${number}", KEEP)
        minus_out[left_start:left_end] = [token]
        plus_out[right_start:right_end] = [token]
    return minus_out, plus_out


def meaningful(token):
    """Whether a token says something: a literal, a constant, or a name that is not a keyword."""
    text, role = token
    return role != KEEP or ((text[0].isalpha() or text[0] in "_$") and text not in KEYWORDS)


def statements(tokens):
    """A token list split after each ``;``, ``{`` and ``}``."""
    found, current = [], []
    for token in tokens:
        current.append(token)
        if token[0] in STATEMENT_END:
            found.append(current)
            current = []
    if current:
        found.append(current)
    return found


def edit_key(minus, plus):
    """The abstracted (removed, added) pattern of one hunk's tokens, or None when it has none.

    :param minus: (text, role) tokens of the removed side
    :param plus: (text, role) tokens of the added side
    :return: a hashable key: two tuples of statement strings
    """
    if not minus and not plus:
        return None
    minus, plus = shared_runs(minus, plus)
    names = {}

    def name(token):
        text, role = token
        if role == KEEP:
            return text
        return names.setdefault((role, text), f"${role}{sum(r == role for r, _ in names) + 1}")

    minus_text = [[name(token) for token in statement] for statement in statements(minus)]
    plus_text = [[name(token) for token in statement] for statement in statements(plus)]
    added_names = {text for statement in plus_text for text in statement}
    kept = [statement for statement in minus_text if not vanishing_declaration(statement, added_names)]
    if kept and (len(kept) < len(minus_text)) and (plus_text or kept):
        minus_text = kept
    return canonical(collapse(minus_text), collapse(plus_text))


def vanishing_declaration(statement, added_names):
    """Whether a removed statement declares a local (``Type $v1 = ...;``) the added side never names."""
    if "=" not in statement:
        return False
    target = statement[statement.index("=") - 1]
    head = statement[: statement.index("=") - 1]
    return (
        target.startswith("$v")
        and target not in added_names
        and bool(head)
        and all(not part.startswith("$") for part in head)
        and statement.index("=") <= 6
    )


def collapse(side):
    """Statements with consecutive repeats dropped, where a repeat differs only in placeholders."""
    shape = [re.sub(r"\$([a-z]?)\d+", r"$\1", " ".join(statement)) for statement in side]
    return [
        statement for index, statement in enumerate(side) if index == 0 or shape[index] != shape[index - 1]
    ]


def canonical(minus, plus):
    """Both sides' statements as display strings, placeholders renumbered by first appearance.

    The numbering is shared, so ``$v1`` on the removed side is the same name as ``$v1`` on the added.
    """
    numbers, counts = {}, {}

    def renumber(match):
        key, kind = match.group(0), match.group(1)
        if key not in numbers:
            counts[kind] = counts.get(kind, 0) + 1
            numbers[key] = f"${kind}{counts[kind]}"
        return numbers[key]

    def side(statements_text):
        return tuple(re.sub(r"\$([vk]?)\d+", renumber, tidy(statement)) for statement in statements_text)

    return side(minus), side(plus)


def tidy(tokens):
    """Tokens joined as source text: no space before closers and separators or after openers."""
    text = " ".join(tokens)
    text = re.sub(r"\s+([.,;)\]])", r"\1", text)
    text = re.sub(r"([.(\[])\s+", r"\1", text)
    return re.sub(r"(\w)\s+\(", r"\1(", text)


def exact_key(hunk):
    """Level 1: the removed and added lines with whitespace collapsed and blank lines dropped."""
    removed = tuple(" ".join(line.split()) for line in hunk.removed if line.strip())
    added = tuple(" ".join(line.split()) for line in hunk.added if line.strip())
    return (removed, added) if removed or added else ("whitespace only",)


def token_key(hunk):
    """Level 2: the abstracted token-level rewrite of a hunk's changed lines."""
    return edit_key(lexical_tokens(hunk.removed), lexical_tokens(hunk.added))


class TreeReader:
    """Level 3: hunks widened to whole statements and read as parser-classified leaf tokens.

    :param source: callable (side, path) -> file text or None, side being "old" or "new"
    """

    def __init__(self, source):
        self.source = source
        self.roots = {}
        try:
            import ast_grep_py
        except ImportError:
            self.parser = None
            self.note = (
                "syntax-tree level skipped: ast-grep-py is not installed in this environment "
                "(`ixd setup`, or `uv tool install --editable --reinstall .` in ai-workspace)"
            )
        else:
            self.parser = ast_grep_py.SgRoot
            self.note = ""

    def root(self, side, path):
        language = TREE_LANGUAGES.get(Path(path).suffix)
        if self.parser is None or language is None or path == "/dev/null":
            return None
        if (side, path) not in self.roots:
            text = self.source(side, path)
            self.roots[(side, path)] = None if text is None else self.parser(text, language).root()
        return self.roots[(side, path)]

    def key(self, hunk):
        """The tree-level key of one hunk, or None when its language has no parser."""
        if TREE_LANGUAGES.get(Path(hunk.path).suffix) is None or self.parser is None:
            return None
        sides = []
        for side, path, start, count in (
            ("old", hunk.old_path, hunk.old_start, hunk.old_count),
            ("new", hunk.new_path, hunk.new_start, hunk.new_count),
        ):
            if count == 0:
                sides.append([])
                continue
            root = self.root(side, path)
            if root is None:
                return None
            tokens = widened_tokens(root, start - 1, start - 1 + count - 1, count)
            if tokens is None:
                return None
            sides.append(tokens)
        return edit_key(*sides)


def widened_tokens(root, first, last, count):
    """Leaf tokens of the smallest statements covering rows ``first..last`` (0-based), or None.

    None when covering them would take much more than the hunk itself, so one changed brace does
    not stand for a whole block.
    """
    chosen = []
    for row in range(first, last + 1):
        node = statement_at(root, row)
        if node is None:
            continue
        if not any(other.range() == node.range() for other in chosen):
            chosen.append(node)
    chosen = [
        node for node in chosen if not any(other is not node and contains(other, node) for other in chosen)
    ]
    if not chosen:
        return []
    span = sum(node.range().end.line - node.range().start.line + 1 for node in chosen)
    if span > WIDEN_FACTOR * count + WIDEN_SLACK:
        return None
    chosen.sort(key=lambda node: node.range().start.index)
    tokens = []
    for node in chosen:
        tokens += leaves(node)
    return tokens


def contains(outer, inner):
    outer_range, inner_range = outer.range(), inner.range()
    return (
        outer_range.start.index <= inner_range.start.index and inner_range.end.index <= outer_range.end.index
    )


def statement_at(root, row):
    """The smallest statement-like node holding code on a row, or None for a blank or comment row."""
    best = None
    stack = [root]
    while stack:
        node = stack.pop()
        span = node.range()
        if span.start.line > row or span.end.line < row:
            continue
        if node.kind() in COMMENT_KINDS:
            continue
        if node.kind() in STATEMENT_KINDS or node.kind().endswith(("_statement", "_declaration")):
            if best is None or contains(best, node):
                best = node
        stack.extend(node.children())
    return best


def leaves(node):
    """(text, role) leaf tokens of a node, literals whole, comments skipped, roles from the parser."""
    found = []
    stack = [node]
    while stack:
        current = stack.pop()
        kind = current.kind()
        if kind in COMMENT_KINDS:
            continue
        if kind in LITERAL_KINDS:
            found.append((current.text(), LITERAL))
            continue
        children = current.children()
        if not children:
            found.append((current.text(), tree_role(current)))
            continue
        stack.extend(reversed(children))
    return found


def tree_role(node):
    """The role of one leaf, from its kind and where it sits in its parent."""
    text = node.text()
    if node.kind() not in IDENTIFIER_KINDS or text in KEYWORDS:
        return KEEP
    parent = node.parent()
    if parent is not None:
        if parent.kind() in ("method_invocation", "call_expression", "call") and parent.field("name") == node:
            return KEEP
        if parent.kind() in ("method_declaration", "constructor_declaration", "function_definition"):
            return KEEP
        if (
            parent.kind() in ("field_access", "member_expression", "attribute")
            and parent.field("field") == node
        ):
            return KEEP
    if CONSTANT.match(text) and len(text) > 1:
        return CONST
    return VARIABLE if text[0].islower() or text[0] == "_" else KEEP


def cluster(diff, source, start=""):
    """Sort a diff's non-mechanical hunks into clusters.

    :param diff: the ``-M -U0`` diff of the change
    :param source: callable (side, path) -> text of that file before ("old") or after ("new")
    :param start: the commit the diff starts from, carried for display
    :return: a :class:`Clustering`
    """
    every = hunks_of(diff)
    mechanical = mechanical_keys(diff)
    hunks = [hunk for hunk in every if (hunk.header[0], hunk.lines[0]) not in mechanical]
    reader = TreeReader(source)
    keys = {1: {}, 2: {}, 3: {}}
    parent = {hunk.number: hunk.number for hunk in hunks}

    def find(number):
        while parent[number] != number:
            parent[number] = parent[parent[number]]
            number = parent[number]
        return number

    for hunk in hunks:
        keys[1][hunk.number] = exact_key(hunk)
        keys[2][hunk.number] = token_key(hunk)
        keys[3][hunk.number] = reader.key(hunk)
    for level in (1, 2, 3):
        first = {}
        for hunk in hunks:
            key = keys[level][hunk.number]
            if key is None:
                continue
            if key in first:
                parent[find(hunk.number)] = find(first[key])
            else:
                first[key] = hunk.number
    for left, right in partial_pairs(hunks, keys):
        parent[find(left)] = find(right)
    groups = {}
    for hunk in hunks:
        groups.setdefault(find(hunk.number), []).append(hunk)
    found, unclustered = [], []
    for members in groups.values():
        if len(members) < MIN_CLUSTER:
            unclustered += members
            continue
        level = next(
            (level for level in (1, 2) if len({keys[level][hunk.number] for hunk in members}) == 1),
            # Without a parser only the partial-hunk rule joins beyond level 2, on token keys.
            3 if reader.parser else 2,
        )
        shown = 3 if level == 3 and most_common([keys[3][hunk.number] for hunk in members]) else 2
        shown = 1 if level == 1 else shown
        pattern = most_common([keys[shown][hunk.number] for hunk in members]) or ()
        typical = next((hunk for hunk in members if keys[shown][hunk.number] == pattern), members[0])
        found.append(Cluster(0, level, members, pattern, typical))
    found.sort(key=lambda item: (-len(item.hunks), -item.lines, item.hunks[0].number))
    by_hunk = {}
    for number, item in enumerate(found, 1):
        item.number = number
        for hunk in item.hunks:
            by_hunk[hunk.number] = item
    unclustered.sort(key=lambda hunk: hunk.number)
    return Clustering(start, hunks, found, unclustered, len(every) - len(hunks), reader.note, by_hunk)


def shape(statement):
    """A pattern statement with its placeholder numbers dropped."""
    return re.sub(r"\$([vk]?)\d+", r"$\1", statement)


def is_subsequence(short, long):
    remaining = iter(long)
    return all(item in remaining for item in short)


def partial_pairs(hunks, keys):
    """Pairs of hunks where one does part of the other's edit, because the diff cut it differently.

    Both add the same statements (by shape, at the tree level when there is one) and one removes a
    subsequence of what the other removes: ``err.addProperty(ERROR, m); return err;`` replaced by
    ``return failure(m);`` is the failure rewrite whose ``addProperty(OK, false)`` line landed in a
    hunk of its own. Hunks that add nothing or remove nothing never pair this way.
    """
    buckets = {}
    for hunk in hunks:
        key = keys[3].get(hunk.number) or keys[2].get(hunk.number)
        if not key or len(key) != 2 or not key[0] or not key[1]:
            continue
        removed = tuple(shape(statement) for statement in key[0])
        added = tuple(shape(statement) for statement in key[1])
        buckets.setdefault(added, []).append((hunk.number, removed))
    pairs = []
    for members in buckets.values():
        seen = {}
        for _, removed in members:
            seen[removed] = seen.get(removed, 0) + 1
        for index, (left, left_removed) in enumerate(members):
            for right, right_removed in members[index + 1 :]:
                shorter, longer = sorted((left_removed, right_removed), key=len)
                # The longer side must be an established pattern, so a hunk that removes the whole
                # rewrite plus real code of its own is not swallowed by it.
                if (
                    len(shorter) < len(longer)
                    and seen[longer] >= MIN_CLUSTER
                    and is_subsequence(shorter, longer)
                ):
                    pairs.append((left, right))
    return pairs


def most_common(values):
    """The value appearing most often (the first such), ignoring None."""
    counts = {}
    for value in values:
        if value is not None:
            counts[value] = counts.get(value, 0) + 1
    return max(counts, key=counts.get) if counts else None


def worktree_source(worktree, start):
    """The (side, path) -> text reader for a worktree: old from the start commit, new from disk."""

    def read(side, path):
        if side == "new":
            try:
                return (Path(worktree) / path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                return None
        return show(worktree, f"{start}:{path}")

    return read


def commit_source(repo, start, commit):
    """The (side, path) -> text reader for a commit's diff: both sides from git objects."""
    return lambda side, path: show(repo, f"{start if side == 'old' else commit}:{path}")


def show(repo, spec):
    result = subprocess.run(
        ["git", "-C", str(repo), "show", spec], capture_output=True, text=True, errors="replace"
    )
    return result.stdout if result.returncode == 0 else None


def of_worktree(worktree, base):
    """The clustering of a worktree's change against its base, untracked files included."""
    start, diff = wt.change_diff(worktree, base)
    return cluster(diff, worktree_source(worktree, start), start), diff


def of_commit(repo, commit):
    """The clustering of one commit's diff against its first parent: a landed change, read only."""
    start = wt.git(repo, "rev-parse", f"{commit}^")
    diff = wt.git(
        repo, "diff", "-M", "-U0", "--no-color", "--src-prefix=a/", "--dst-prefix=b/", start, commit
    )
    return cluster(diff + "\n", commit_source(repo, start, commit), start), diff


def patch_for(hunks):
    """A ``-U0`` patch holding exactly these hunks, each file's header once, ``index`` lines dropped."""
    by_file = {}
    for hunk in sorted(hunks, key=lambda item: item.number):
        by_file.setdefault(hunk.header[0], (hunk.header, []))[1].append(hunk)
    out = []
    for header, members in by_file.values():
        out += [line for line in header if not line.startswith("index ")]
        for hunk in members:
            out += hunk.lines
    return "\n".join(out) + "\n" if out else ""


def report(clustering, label, show_hunks=False, width=110):
    """The text ``ixd wt clusters`` prints: each cluster's pattern, files and one representative.

    :param clustering: a :class:`Clustering`
    :param label: what was clustered, for the first line
    :param show_hunks: list every hunk of each cluster, not just the representative
    :param width: where long lines are cut
    """
    clustered = sum(len(item.hunks) for item in clustering.clusters)
    lines = [
        f"{label}: {len(clustering.hunks)} hunk(s) from {clustering.start[:10]}; {clustered} in "
        f"{len(clustering.clusters)} cluster(s), {len(clustering.unclustered)} unclustered, "
        f"{clustering.mechanical} mechanical (stage-moves)"
    ]
    if clustering.tree_note:
        lines.append(f"note: {clustering.tree_note}")
    for item in clustering.clusters:
        lines.append("")
        lines.append(
            f"cluster {item.number}  [{LEVEL_NAMES[item.level]}]  {len(item.hunks)} hunks, "
            f"{len(item.files)} file(s), {item.lines} changed lines"
        )
        removed, added = item.pattern if len(item.pattern) == 2 else ((), ())
        for sign, side in (("-", removed), ("+", added)):
            if side:
                text = " ".join(side)
                lines.append(f"  {sign} " + (text if len(text) <= width else text[: width - 4] + " ..."))
        names = [Path(path).name + (f" ({count})" if count > 1 else "") for path, count in item.files.items()]
        lines += wrapped("  files: ", names, width)
        shown = item.hunks if show_hunks else [item.representative or item.hunks[0]]
        for hunk in shown:
            described = describe(hunk, width - 4)
            lines.append(("  " if show_hunks else "  e.g. ") + described[0])
            lines += ["  " + line for line in described[1:]]
    if clustering.unclustered:
        lines.append("")
        lines.append(f"unclustered ({len(clustering.unclustered)}): the hunks to read")
        for hunk in clustering.unclustered:
            lines.append(f"  {hunk.path}:{hunk.line}  ({hunk.size} line(s))")
    return lines


def wrapped(prefix, items, width):
    """Comma-separated items on as many lines as the width needs, continuation lines indented."""
    lines, current = [], prefix
    for index, item in enumerate(items):
        piece = item + ("," if index + 1 < len(items) else "")
        if len(current) + len(piece) + 1 > width and current.strip() != prefix.strip():
            lines.append(current.rstrip())
            current = " " * len(prefix)
        current += piece + " "
    lines.append(current.rstrip())
    return lines


def hunk_at(clustering, path, line):
    """The non-mechanical hunk of a file covering a new-file line, or exit naming the nearest ones."""
    in_file = [hunk for hunk in clustering.hunks if hunk.path == path or hunk.old_path == path]
    for hunk in in_file:
        if hunk.covers(line):
            return hunk
    if not in_file:
        raise SystemExit(f"{path} has no hunk outside the mechanical ones (or is not in the change)")
    nearest = sorted(in_file, key=lambda hunk: abs(hunk.line - line))[:3]
    raise SystemExit(
        f"no hunk of {path} covers line {line}; nearest: "
        + ", ".join(f"{hunk.line} ({hunk.new_count} line(s))" for hunk in nearest)
    )


def stage_hunks(worktree, branch, hunks, what):
    """Replace the worktree's index with exactly these hunks and print what is staged.

    :param worktree: the worktree directory, already uncommitted to its start
    :param branch: its branch
    :param hunks: the hunks to stage
    :param what: what they are, for the summary
    """
    wt.stage_patch(worktree, branch, patch_for(hunks), what)
    files = wt.git(worktree, "diff", "--cached", "--name-only").splitlines()
    stat = wt.git(worktree, "diff", "--cached", "--shortstat")
    print(
        f"{branch}: staged {what}: {len(hunks)} hunk(s) in {len(files)} file(s) ({stat.strip()}); "
        f"`git diff --cached` shows them, `git diff` the rest; `ixd wt stage-moves {branch}` puts the "
        f"review layout back"
    )


def describe(hunk, width=110):
    """``path:line`` of a hunk and its changed lines, indented, cut to the width."""
    lines = [f"{hunk.path}:{hunk.line}"]
    for line in hunk.lines[1:]:
        if line[:1] in "+-":
            text = line[0] + " " + line[1:].strip()
            lines.append("    " + (text if len(text) <= width else text[: width - 4] + " ..."))
    return lines
