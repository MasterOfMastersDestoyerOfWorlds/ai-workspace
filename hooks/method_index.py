#!/usr/bin/env python3
"""Duplicate-helper lookup for the checkstyle edit hook: "this already exists, did you mean X?".

On 2026-11-22 an agent wrote a ring centroid into MeshUnfold that the code already had as
MeshTopology.oneRings plus PackedPoints.ringMean; CPD missed it because the names and some steps
differed. This module indexes every method of a Maven module's src/main/java and, for a method an
edit adds, reports existing methods it may re-implement, by three deterministic rules:

- Body: the same body once every identifier and literal is replaced by a placeholder (a token
  hash, not CPD's token window), for bodies of at least MIN_BODY_TOKENS tokens.
- Signature: the same erased parameter and return types, and a shared name token.
- Receiver: a method declared on the type of one of the new method's parameters (or a supertype)
  whose name tokens contain the new method's or are contained in them, with centroid, mean and
  average read as one word. A parameter that suggestion needs and the new method does not have
  is traced to a method on the new method's parameter types returning it ("its int[][] from
  MeshTopology.oneRings()").

A fourth rule works below whole methods, for a block an edit adds inside a longer method (a convex
hull written into MeshUnfold that PolygonScan.convexHull already had, one counting loop pasted
twice): every method and constructor body is normalised the way the body rule does it, with
qualified names folded into one placeholder and called names cut to their last word, and
fingerprinted by winnowing its KGRAM-token windows. The added code's windows are looked up among
the module's fingerprints, its own file's and those of the change's other files, and the hits on
one body are chained in order, gaps of a few statements allowed, so a copy with a filter added or
a statement dropped (a Type-3 clone) still chains. A dense chain covering MIN_BLOCK_TOKENS tokens,
or MIN_LOCAL_BLOCK_TOKENS when the copy is in the same file or the same change, is reported as a
DuplicateBlock with both line ranges.

Parsing is a tokenizer and a brace-matching walk, not a compiler: types resolve by simple name.
The index is cached per module under ~/.cache/ai-workspace-hooks/method-index/, keyed by file
mtime and size, so an edit re-reads only the files that changed.

Run directly, ``python hooks/method_index.py <module>/src/main/java`` lists every suggestion on
the whole module, the way its hits on master were judged; ``--blocks`` lists the block clones
instead, and ``--diff <checkout>`` checks the lines a checkout's uncommitted diff adds, main and
test sources, against its modules.
"""

import bisect
import hashlib
import json
import os
import re
import subprocess
import sys
import zlib

CACHE_DIR = os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
    "ai-workspace-hooks",
    "method-index",
)

MIN_BODY_TOKENS = 40

# Block fingerprints: KGRAM normalised tokens a window, the smallest hash of every WINNOW
# consecutive windows kept, so any run of KGRAM + WINNOW - 1 shared tokens leaves a shared print.
KGRAM = 10

WINNOW = 6

# Normalised tokens a chain must cover on both sides to be reported, measured on Ixdar master's
# 1015 files (``--blocks``; the judged samples are in the TOOL-63 report). A copy elsewhere in the
# module needs 100: between 70 and 100 about a third of the hits were two unrelated runs of one
# shape (array declarations, builder calls), above 100 about one in ten. A copy in the same file
# or the same change needs 45, which is where a pasted counting loop (MeshRepair.clearAround's
# two root counts) lands, and is likelier to be a paste than a shared idiom.
MIN_BLOCK_TOKENS = 100

MIN_LOCAL_BLOCK_TOKENS = 45

# Covered tokens over the chain's extent, on each side: below it the chain is scattered idiom
# matches strung together, not one block.
BLOCK_DENSITY = 0.6

# How far apart, in tokens, two hits of one chain may be, and how much more one side may skip
# than the other: the room for a statement or a filter one copy has and the other does not.
BLOCK_GAP = 60

BLOCK_DRIFT = 40

INDEX_VERSION = f"7-{KGRAM}-{WINNOW}"

LITERAL_KINDS = ("number", "string", "char", "text")

# After these a minus sign is a sign, folded into the literal it precedes.
UNARY_CONTEXT = frozenset("( [ { , = ? : return + - * / < > <= >= == != && || ! ->".split())

DIFF_HUNK = re.compile(r"^@@ -\S+ \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")

MAX_SUGGESTIONS = 3

# A word that two or fewer of a type's methods use names a concept of that type; one most of them
# use (face, edge, vertex on a mesh) is the type's vocabulary and says nothing.
DISTINCTIVE_USES = 2

PLAIN_TYPES = frozenset("boolean byte char short int long float double String Object".split())

TOKEN = re.compile(
    r'(?P<block>/\*.*?\*/)|(?P<line>//[^\n]*)|(?P<text>"""(?:\\.|[^\\])*?""")'
    r'|(?P<string>"(?:\\.|[^"\\\n])*")|(?P<char>\'(?:\\.|[^\'\\\n])*\')'
    r"|(?P<number>\.?\d[\w.]*(?:[eEpP][+-]\d+)?[fFdDlL]?)|(?P<ident>[A-Za-z_$][\w$]*)"
    r"|(?P<punct>->|::|\.\.\.|\S)",
    re.S,
)

KEYWORDS = frozenset(
    "abstract assert boolean break byte case catch char class continue default do double else "
    "enum extends final finally float for if implements import instanceof int interface long "
    "native new package private protected public return short static strictfp super switch "
    "synchronized this throw throws transient try void volatile while var yield record true "
    "false null".split()
)

MODIFIERS = frozenset(
    "public private protected static final abstract native synchronized transient volatile "
    "strictfp default sealed non-sealed".split()
)

TYPE_KEYWORDS = frozenset({"class", "interface", "enum", "record"})

STOP_TOKENS = frozenset(
    "get set is has to of at in on for by from with and or the a an new compute calculate make "
    "do run build create apply update find into as".split()
)

PHRASING = frozenset("get compute calculate make build create do run of the a an".split())

SYNONYMS = {"mean": "centroid", "average": "centroid", "avg": "centroid"}

IRREGULAR = {"vertices": "vertex", "indices": "index", "matrices": "matrix"}

CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def name_tokens(name):
    """The canonical words of a camelCase name: lower case, singular, synonyms merged."""
    words = []
    for word in CAMEL.findall(name):
        word = word.lower()
        word = IRREGULAR.get(word, word)
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        words.append(SYNONYMS.get(word, word))
    return words


def meaningful_tokens(name):
    """The name's words that say what it does, not how it is phrased."""
    return frozenset(word for word in name_tokens(name) if word not in STOP_TOKENS and not word.isdigit())


def phrase(name):
    """The name's words in order, minus filler verbs, so computeBounds reads as bounds.

    Verbs that change the meaning (is, has, set, find, add) stay: hasFace is not faces.
    """
    return tuple(word for word in name_tokens(name) if word not in PHRASING)


def head(name):
    """The last meaningful word of a name, the noun it produces in camelCase English."""
    words = [word for word in name_tokens(name) if word not in STOP_TOKENS and not word.isdigit()]
    return words[-1] if words else None


def tokenize(source):
    """Returns (kind, text, offset) for every token, comments dropped."""
    tokens = []
    for match in TOKEN.finditer(source):
        kind = match.lastgroup
        if kind in ("block", "line"):
            continue
        tokens.append((kind, match.group(), match.start()))
    return tokens


def matching(tokens, index, opener, closer):
    """The index just past the token closing the bracket opened at ``index``."""
    depth = 0
    while index < len(tokens):
        text = tokens[index][1]
        if text == opener:
            depth += 1
        elif text == closer:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return index


def erase(type_tokens):
    """The simple name of a written type with generics dropped and array depth kept."""
    depth = 0
    kept = []
    for text in type_tokens:
        if text == "<":
            depth += 1
        elif text == ">":
            depth -= 1
        elif depth == 0 and text not in ("final", "@"):
            kept.append(text)
    dimensions = kept.count("[") + kept.count("...")
    names = [text for text in kept if re.match(r"[A-Za-z_$]", text)]
    simple = names[-1] if names else "?"
    return simple + "[]" * dimensions


def split_parameters(tokens):
    """Splits a parameter list's tokens at top-level commas, annotations dropped."""
    parameters = []
    current = []
    depth = 0
    index = 0
    while index < len(tokens):
        text = tokens[index]
        if text == "@":
            index += 2
            if index < len(tokens) and tokens[index] == "(":
                index = matching_texts(tokens, index)
            continue
        if text in ("<", "("):
            depth += 1
        elif text in (">", ")"):
            depth -= 1
        if text == "," and depth == 0:
            parameters.append(current)
            current = []
        else:
            current.append(text)
        index += 1
    if current:
        parameters.append(current)
    return [(erase(parameter[:-1]), parameter[-1]) for parameter in parameters if len(parameter) >= 2]


def matching_texts(texts, index):
    """``matching`` over plain token texts, for parentheses."""
    depth = 0
    while index < len(texts):
        if texts[index] == "(":
            depth += 1
        elif texts[index] == ")":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return index


def body_hash(tokens):
    """A hash of a body with identifiers and literals replaced, or None when it is too short.

    The names of called methods stay: with them gone, every loop copying one array into another
    hashes alike whatever it reads.
    """
    normalised = []
    for position, (kind, text, _) in enumerate(tokens):
        if kind == "ident":
            called = position + 1 < len(tokens) and tokens[position + 1][1] == "("
            normalised.append(text if text in KEYWORDS or called else "I")
        elif kind in ("number", "string", "char", "text"):
            normalised.append("L")
        else:
            normalised.append(text)
    if len(normalised) < MIN_BODY_TOKENS:
        return None
    return hashlib.sha1(" ".join(normalised).encode()).hexdigest()[:16]


def block_tokens(tokens, line_of):
    """A body's tokens for block matching, with the line each is on.

    Looser than ``body_hash``: a qualified name (``order.length``, ``this.count``) folds into one
    placeholder, and a called name keeps only its last word, so ``surface.faceIdAt(face)`` and
    ``vertexIdAt(vertex)`` read alike while ``get`` and ``add`` stay apart; a sign before a
    literal and ``final`` drop out.
    """
    texts = []
    lines = []
    index = 0
    while index < len(tokens):
        kind, text, offset = tokens[index]
        if text == "final" or text == "@" and kind == "punct":
            index += 2 if text == "@" else 1
            continue
        if kind == "ident" and (text not in KEYWORDS or text in ("this", "super")):
            while (
                index + 2 < len(tokens)
                and tokens[index + 1][1] == "."
                and tokens[index + 2][0] == "ident"
                and tokens[index + 2][1] not in KEYWORDS
            ):
                index += 2
            called = index + 1 < len(tokens) and tokens[index + 1][1] == "(" and texts[-1:] != ["new"]
            words = CAMEL.findall(tokens[index][1]) if called else ()
            text = words[-1].lower() if words else "I"
        elif kind in LITERAL_KINDS:
            text = "L"
        elif (
            text == "-"
            and (not texts or texts[-1] in UNARY_CONTEXT)
            and index + 1 < len(tokens)
            and tokens[index + 1][0] == "number"
        ):
            index += 1
            continue
        texts.append(text)
        lines.append(line_of(offset))
        index += 1
    return texts, lines


def kgram_hashes(texts):
    """A stable hash of every KGRAM-token window of a normalised body."""
    return [
        zlib.crc32(" ".join(texts[start : start + KGRAM]).encode()) for start in range(len(texts) - KGRAM + 1)
    ]


def winnow(hashes):
    """The positions winnowing keeps: the rightmost smallest hash of every WINNOW windows."""
    chosen = []
    for start in range(max(1, len(hashes) - WINNOW + 1) if hashes else 0):
        window = hashes[start : start + WINNOW]
        low = min(window)
        position = start + len(window) - 1 - window[::-1].index(low)
        if not chosen or chosen[-1] != position:
            chosen.append(position)
    return chosen


def body_prints(texts, lines, full):
    """A body's winnowed fingerprints with their token positions and line spans.

    ``full`` keeps every window's hash and every token's line as well, which a body being
    checked needs and the cached index does not.
    """
    hashes = kgram_hashes(texts)
    kept = winnow(hashes)
    prints = {
        "size": len(texts),
        "fp": [hashes[position] for position in kept],
        "at": kept,
        "from": [lines[position] for position in kept],
        "to": [lines[position + KGRAM - 1] for position in kept],
    }
    if full:
        prints["hashes"] = hashes
        prints["lines"] = lines
    return prints


def called_names(tokens):
    """The methods a body calls or references with ``::``: ``name`` for a bare call,
    ``Type.name`` through a capitalised type name, ``.name`` through any other receiver."""
    names = set()
    for position, (kind, text, _) in enumerate(tokens):
        if kind != "ident" or text in KEYWORDS:
            continue
        following = tokens[position + 1][1] if position + 1 < len(tokens) else ""
        preceding = tokens[position - 1][1] if position else ""
        if following != "(" and preceding != "::":
            continue
        if preceding not in (".", "::"):
            names.add(text)
            continue
        receiver = tokens[position - 2] if position >= 2 else ("", "", 0)
        capitalised = receiver[0] == "ident" and receiver[1][:1].isupper()
        names.add(f"{receiver[1]}.{text}" if capitalised else f".{text}")
    return sorted(names)


def delegates(caller, callee):
    """Whether ``caller``'s body calls ``callee``, read so that recursion is not delegation.

    A call to a differently named method counts in any form. For two methods of one name, only a
    call that can reach the other does: through the callee's class name, or through a receiver
    from a static caller; an instance method calling its own name on a receiver is walking a tree
    of its own type (GraphNodeContext.lastOfKind on each child).
    """
    name = callee["name"]
    owner = callee["owner"].rsplit(".", 1)[-1]
    calls = caller["calls"]
    if name != caller["name"]:
        return any(call == name or call.endswith("." + name) for call in calls)
    return f"{owner}.{name}" in calls or caller["static"] and f".{name}" in calls


def parse(source, full=False):
    """Indexes one Java source: its package, imports, types, methods and body fingerprints.

    ``full`` keeps each body's every window hash and token line, for checking it.
    """
    tokens = tokenize(source)
    newlines = [match.start() for match in re.finditer("\n", source)]
    result = {"package": "", "imports": {}, "types": [], "methods": [], "bodies": [], "full": full}

    def line_of(offset):
        return bisect.bisect_left(newlines, offset) + 1

    index = 0
    while index < len(tokens) and tokens[index][1] in ("package", "import", "@", ";"):
        text = tokens[index][1]
        end = index
        while end < len(tokens) and tokens[end][1] != ";":
            end += 1
        words = [token[1] for token in tokens[index + 1 : end] if token[1] != "static"]
        if text == "package":
            result["package"] = "".join(words)
        elif text == "import":
            name = "".join(words)
            result["imports"][name.rsplit(".", 1)[-1]] = name
        elif text == "@":
            break
        index = end + 1
    parse_members(tokens, index, len(tokens), [], result, line_of)
    del result["full"]
    return result


def parse_members(tokens, index, end, enclosing, result, line_of):
    """Walks one type body (or the compilation unit) from ``index`` to ``end``."""
    while index < end:
        text = tokens[index][1]
        if text in (";", "}"):
            index += 1
            continue
        annotations = []
        while (
            index < end
            and tokens[index][1] == "@"
            and index + 1 < end
            and tokens[index + 1][1] != "interface"
        ):
            annotations.append(tokens[index + 1][1])
            index += 2
            while index + 1 < end and tokens[index][1] == "." and tokens[index + 1][0] == "ident":
                index += 2
            if index < end and tokens[index][1] == "(":
                index = matching(tokens, index, "(", ")")
        scan = index
        keyword = None
        while scan < end and tokens[scan][1] not in ("(", "{", ";", "="):
            if tokens[scan][1] in TYPE_KEYWORDS and tokens[scan][0] == "ident":
                keyword = tokens[scan][1]
                break
            scan += 1
        if keyword is not None:
            index = parse_type(tokens, scan, end, enclosing, result, line_of, keyword)
            continue
        if scan >= end:
            return
        stop = tokens[scan][1]
        if stop == "{":
            index = matching(tokens, scan, "{", "}")
            continue
        if stop in (";", "="):
            index = skip_declaration(tokens, scan, end)
            continue
        header = [token[1] for token in tokens[index:scan]]
        modifiers = {word for word in header if word in MODIFIERS}
        declared = [word for word in header if word not in MODIFIERS]
        if declared and declared[0] == "<":
            closing = 0
            depth = 0
            for position, word in enumerate(declared):
                depth += (word == "<") - (word == ">")
                if depth == 0:
                    closing = position
                    break
            declared = declared[closing + 1 :]
        close = matching(tokens, scan, "(", ")")
        after = close
        while after < end and tokens[after][1] not in ("{", ";"):
            after += 1
        if after >= end:
            return
        body_end = matching(tokens, after, "{", "}") if tokens[after][1] == "{" else after + 1
        if declared and tokens[scan - 1][0] == "ident" and tokens[after][1] == "{":
            texts, lines = block_tokens(tokens[after + 1 : body_end - 1], line_of)
            if len(texts) >= KGRAM:
                result["bodies"].append(
                    {
                        "owner": ".".join(enclosing),
                        "name": tokens[scan - 1][1],
                        "line": line_of(tokens[scan - 1][2]),
                        **body_prints(texts, lines, result["full"]),
                    }
                )
        if len(declared) >= 2 and tokens[scan - 1][0] == "ident":
            name = tokens[scan - 1][1]
            parameters = split_parameters([token[1] for token in tokens[scan + 1 : close - 1]])
            body = tokens[after + 1 : body_end - 1] if tokens[after][1] == "{" else None
            result["methods"].append(
                {
                    "owner": ".".join(enclosing),
                    "name": name,
                    "line": line_of(tokens[scan - 1][2]),
                    "returns": erase(declared[:-1]),
                    "parameters": [kind for kind, _ in parameters],
                    "parameterNames": [label for _, label in parameters],
                    "private": "private" in modifiers,
                    "static": "static" in modifiers,
                    "override": "Override" in annotations,
                    "annotated": bool(annotations),
                    "hash": body_hash(body) if body else None,
                    "calls": called_names(body) if body else [],
                }
            )
        index = body_end


def skip_declaration(tokens, index, end):
    """Skips a field declaration to the index past its semicolon, initializers included."""
    depth = 0
    while index < end:
        text = tokens[index][1]
        if text in ("(", "{", "["):
            depth += 1
        elif text in (")", "}", "]"):
            depth -= 1
        elif text == ";" and depth <= 0:
            return index + 1
        index += 1
    return index


def parse_type(tokens, index, end, enclosing, result, line_of, keyword):
    """Indexes a type declaration whose keyword is at ``index``; returns the index past it."""
    name = tokens[index + 1][1] if index + 1 < end else "?"
    scan = index + 2
    supertypes = []
    depth = 0
    if keyword == "record" and scan < end and tokens[scan][1] in ("(", "<"):
        while scan < end and tokens[scan][1] != "(":
            scan += 1
        scan = matching(tokens, scan, "(", ")")
    while scan < end and tokens[scan][1] != "{":
        text = tokens[scan][1]
        if text == "<":
            depth += 1
        elif text == ">":
            depth -= 1
        elif depth == 0 and tokens[scan][0] == "ident" and text not in ("extends", "implements", "permits"):
            if scan + 1 < end and tokens[scan + 1][1] == ".":
                scan += 1
                continue
            supertypes.append(text)
        scan += 1
    body_end = matching(tokens, scan, "{", "}")
    nested = enclosing + [name]
    result["types"].append({"name": name, "qualified": ".".join(nested), "supertypes": supertypes})
    body_start = scan + 1
    if keyword == "enum":
        level = 0
        while body_start < body_end - 1:
            text = tokens[body_start][1]
            if text in ("(", "{"):
                level += 1
            elif text in (")", "}"):
                level -= 1
            elif text == ";" and level == 0:
                break
            body_start += 1
    parse_members(tokens, body_start, body_end - 1, nested, result, line_of)
    return body_end


def module_root(path):
    """The src/main/java directory a file belongs to, or None."""
    marker = os.sep + os.path.join("src", "main", "java") + os.sep
    absolute = os.path.abspath(path)
    position = absolute.find(marker)
    return absolute[: position + len(marker) - 1] if position >= 0 else None


def load_index(root):
    """The module's index, re-reading only files whose mtime or size changed since the cache."""
    key = hashlib.sha1(os.path.normcase(os.path.abspath(root)).encode()).hexdigest()[:16]
    cache_path = os.path.join(CACHE_DIR, f"{key}.json")
    try:
        with open(cache_path, encoding="utf-8") as handle:
            cached = json.load(handle)
        if cached.get("version") != INDEX_VERSION:
            cached = {}
    except (OSError, ValueError):
        cached = {}
    old_files = cached.get("files", {})
    files = {}
    changed = False
    for directory, _, names in os.walk(root):
        for file_name in names:
            if not file_name.endswith(".java"):
                continue
            path = os.path.join(directory, file_name)
            relative = os.path.relpath(path, root)
            status = os.stat(path)
            stamp = [status.st_mtime_ns, status.st_size]
            entry = old_files.get(relative)
            if entry is None or entry["stamp"] != stamp:
                try:
                    with open(path, encoding="utf-8", errors="replace") as handle:
                        entry = {"stamp": stamp, **parse(handle.read())}
                except (OSError, RecursionError):
                    continue
                changed = True
            files[relative] = entry
    if changed or len(files) != len(old_files):
        os.makedirs(CACHE_DIR, exist_ok=True)
        pending = f"{cache_path}.{os.getpid()}"
        with open(pending, "w", encoding="utf-8") as handle:
            json.dump({"version": INDEX_VERSION, "files": files}, handle)
        os.replace(pending, cache_path)
    return Index(files)


class Index:
    """Methods by body hash, by signature and by owning type, plus each type's supertypes."""

    def __init__(self, files):
        self.files = files
        self.by_hash = {}
        self.by_signature = {}
        self.by_owner = {}
        self.supertypes = {}
        self.bodies = []
        for relative, entry in files.items():
            self.bodies.extend((relative, body) for body in entry["bodies"])
            for declared in entry["types"]:
                self.supertypes.setdefault(declared["name"], set()).update(declared["supertypes"])
            for method in entry["methods"]:
                record = (relative, method)
                if method["hash"]:
                    self.by_hash.setdefault(method["hash"], []).append(record)
                self.by_signature.setdefault(signature(method), []).append(record)
                owner = method["owner"].rsplit(".", 1)[-1]
                self.by_owner.setdefault(owner, []).append(record)

    def lineage(self, type_name):
        """A type and every supertype the index can resolve by simple name."""
        seen = []
        pending = [type_name]
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.append(current)
            pending.extend(self.supertypes.get(current, ()))
        return seen

    def is_project_type(self, kind):
        """Whether a parameter type is a class the index holds, not a primitive or library type."""
        return kind in self.supertypes

    def methods_of(self, type_name):
        """The callable methods declared on a type or its supertypes."""
        found = []
        for owner in self.lineage(type_name):
            found.extend(record for record in self.by_owner.get(owner, ()) if not record[1]["private"])
        return found


def signature(method):
    """The erased return and parameter types, which the signature rule compares."""
    return method["returns"] + "(" + ",".join(method["parameters"]) + ")"


def describe(record):
    """How a suggestion names an existing method: owner, name, parameters and where it is."""
    relative, method = record
    parameters = ", ".join(
        f"{kind} {label}" for kind, label in zip(method["parameters"], method["parameterNames"])
    )
    owner = method["owner"].rsplit(".", 1)[-1]
    return f"{owner}.{method['name']}({parameters}) ({relative.replace(os.sep, '/')}:{method['line']})"


def is_same(record, relative, method):
    """Whether an index record is the method being checked."""
    return (
        record[0] == relative and record[1]["name"] == method["name"] and record[1]["line"] == method["line"]
    )


def suggestions(index, relative, method):
    """The existing methods a new one may re-implement, each with the rule that found it."""
    found = []
    seen = set()

    def add(record, reason):
        key = (record[0], record[1]["name"], record[1]["line"])
        if key not in seen and not is_same(record, relative, method):
            seen.add(key)
            found.append(f"{describe(record)}: {reason}")

    own_lineage = set(index.lineage(method["owner"].rsplit(".", 1)[-1]))

    def elsewhere(record):
        """Neither the method's own class or supertypes, nor a delegate it calls or that calls it."""
        other = record[1]
        return (
            other["owner"].rsplit(".", 1)[-1] not in own_lineage
            and not delegates(method, other)
            and not delegates(other, method)
        )

    if method["hash"]:
        for record in index.by_hash.get(method["hash"], ()):
            if record[0] != relative:
                add(record, "the same body with identifiers and literals aside")
    words = meaningful_tokens(method["name"])
    if method["private"] and words and any(index.is_project_type(kind) for kind in method["parameters"]):
        for record in index.by_signature.get(signature(method), ()):
            other = meaningful_tokens(record[1]["name"])
            if elsewhere(record) and other and (other <= words or words <= other):
                add(record, f"the same signature {signature(method)} and name words")
    own_parameters = set(method["parameters"])
    own_phrase = phrase(method["name"])
    own_head = head(method["name"])
    for parameter in dict.fromkeys(method["parameters"]) if method["static"] else ():
        if not index.is_project_type(parameter):
            continue
        candidates = []
        inherited = set()
        for record in index.methods_of(parameter):
            overridden = (record[1]["name"], signature(record[1]))
            if elsewhere(record) and overridden not in inherited:
                inherited.add(overridden)
                candidates.append(record)
        frequency = {}
        for record in candidates:
            for word in meaningful_tokens(record[1]["name"]):
                frequency[word] = frequency.get(word, 0) + 1
        for record in candidates:
            candidate = meaningful_tokens(record[1]["name"])
            same_name = bool(own_phrase) and phrase(record[1]["name"]) == own_phrase
            part_of_name = (
                len(candidate) >= 2
                and candidate < words
                and own_head in candidate
                and any(frequency[word] <= DISTINCTIVE_USES for word in candidate)
            )
            if not (same_name or part_of_name):
                continue
            reason = f"a {parameter} method named like it"
            missing = [kind for kind in record[1]["parameters"] if kind not in own_parameters]
            for kind in dict.fromkeys(missing):
                producer = producer_of(index, kind, own_parameters, candidate)
                if producer:
                    reason += f", its {kind} from {producer}"
            add(record, reason)
    return found[:MAX_SUGGESTIONS]


def producer_of(index, kind, parameter_types, candidate_words):
    """A method on the given parameter types returning ``kind`` and sharing a name word.

    Primitives and strings are left alone: every type has methods returning an int.
    """
    if kind in PLAIN_TYPES:
        return None
    for parameter in sorted(parameter_types):
        if not index.is_project_type(parameter):
            continue
        for _, method in index.methods_of(parameter):
            if method["returns"] == kind and candidate_words & meaningful_tokens(method["name"]):
                return f"{method['owner'].rsplit('.', 1)[-1]}.{method['name']}()"
    return None


def added_method_reports(path, added):
    """The "did you mean" reports for methods whose declaration line ``added`` holds.

    ``added`` is None when the whole file is new. Overrides and annotated methods are skipped: an
    implementation shares its signature with its siblings by design.
    """
    root = module_root(path)
    if root is None:
        return []
    index = load_index(root)
    relative = os.path.relpath(os.path.abspath(path), root)
    entry = index.files.get(relative)
    if entry is None:
        return []
    reports = []
    for method in entry["methods"]:
        if method["annotated"] or (added is not None and method["line"] not in added):
            continue
        found = suggestions(index, relative, method)
        if found:
            listed = "; ".join(found)
            reports.append(
                f"{os.path.basename(path)}:{method['line']}: '{method['name']}()' may already exist. "
                f"Did you mean {listed}? Call it instead of re-implementing it, or say in the "
                f"report why it does not fit. [DuplicateHelper]"
            )
    return reports


def module_of(path):
    """The module directory and its src/main/java for a main or test source, or None."""
    directory = os.path.dirname(os.path.abspath(path))
    while True:
        main_root = os.path.join(directory, "src", "main", "java")
        if os.path.isdir(main_root):
            return directory, main_root
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent


def source_label(module, main_root, path):
    """A file's name in reports: under src/main/java as the index has it, else under the module."""
    absolute = os.path.abspath(path)
    inside = absolute.startswith(main_root + os.sep)
    return os.path.relpath(absolute, main_root if inside else module)


def read_source(path, full):
    """A file parsed for block matching, or None when it cannot be read."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return parse(handle.read(), full)
    except (OSError, RecursionError):
        return None


def print_lookup(wanted, targets):
    """The fingerprints of ``targets`` whose hash is in ``wanted`` (all when None), by hash.

    Common windows (a counting for header) stay: dropping them leaves holes in real copies that
    no gap allowance bridges, and the chain's size, not any one window, decides a report.
    """
    found = {}
    for target, (_, body) in enumerate(targets):
        for position, value in enumerate(body["fp"]):
            if wanted is None or value in wanted:
                found.setdefault(value, []).append((target, body["at"][position], position))
    return found


def best_chain(hits):
    """The hits, in order on both sides, that cover the most query tokens, gaps allowed."""
    score = [KGRAM] * len(hits)
    back = [-1] * len(hits)
    for current, (query_at, target_at, _) in enumerate(hits):
        previous = current - 1
        while previous >= 0 and query_at - hits[previous][0] <= BLOCK_GAP:
            step = query_at - hits[previous][0]
            target_step = target_at - hits[previous][1]
            if step > 0 and 0 < target_step <= BLOCK_GAP and abs(step - target_step) <= BLOCK_DRIFT:
                candidate = score[previous] + min(KGRAM, step)
                if candidate > score[current]:
                    score[current] = candidate
                    back[current] = previous
            previous -= 1
    end = max(range(len(hits)), key=score.__getitem__)
    chain = []
    while end >= 0:
        chain.append(hits[end])
        end = back[end]
    return chain[::-1]


def chains_between(hits, same_body):
    """The separate clone chains in one query body's hits on one target body.

    Within one body a chain whose two copies overlap is a run of like statements (x, y and z
    written in turn), not a copy, and is dropped.
    """
    hits = sorted(hits)
    found = []
    for _ in range(4):
        if not hits:
            break
        chain = best_chain(hits)
        first, last = chain[0], chain[-1]
        hits = [hit for hit in hits if not first[0] <= hit[0] <= last[0]]
        overlapping = first[0] < last[1] + KGRAM and first[1] < last[0] + KGRAM
        if len(chain) > 1 and not (same_body and overlapping):
            found.append(chain)
    return found


def block_clones(queries, targets, lookup, change=()):
    """The block clones of the queries' added code among the targets.

    ``queries`` holds (label, full body, added lines or None for all); ``targets`` holds (label,
    body) and includes the queries' own files; ``change`` names the files of the change. Each
    clone is a dict naming both line ranges, how many added tokens the chain covers, and whether
    the copy is local: in the query's own file or another file of the change.
    """
    clones = []
    for label, body, added in queries:
        local = {label, *change}
        lines = body["lines"]
        flags = [added is None or line in added for line in lines]
        if not any(flags):
            continue
        prefix = [0]
        for flag in flags:
            prefix.append(prefix[-1] + flag)
        by_target = {}
        for query_at, value in enumerate(body["hashes"]):
            if prefix[query_at + KGRAM] == prefix[query_at]:
                continue
            for target, target_at, position in lookup.get(value, ()):
                other_label, other = targets[target]
                same_body = other_label == label and other["line"] == body["line"]
                if same_body and abs(target_at - query_at) < KGRAM:
                    continue
                by_target.setdefault(target, []).append((query_at, target_at, position))
        for target, hits in by_target.items():
            other_label, other = targets[target]
            same_body = other_label == label and other["line"] == body["line"]
            for chain in chains_between(hits, same_body):
                covered = set()
                for query_at, _, _ in chain:
                    covered.update(range(query_at, query_at + KGRAM))
                added_tokens = sum(flags[position] for position in covered)
                target_tokens = len(
                    {at for _, target_at, _ in chain for at in range(target_at, target_at + KGRAM)}
                )
                clones.append(
                    {
                        "label": label,
                        "body": body,
                        "lines": (lines[chain[0][0]], lines[chain[-1][0] + KGRAM - 1]),
                        "target": (other_label, other),
                        "targetLines": (other["from"][chain[0][2]], other["to"][chain[-1][2]]),
                        "tokens": added_tokens,
                        "covered": len(covered),
                        "targetTokens": target_tokens,
                        "span": chain[-1][0] + KGRAM - chain[0][0],
                        "targetSpan": chain[-1][1] + KGRAM - chain[0][1],
                        "local": other_label in local,
                        "distinct": len({body["hashes"][query_at] for query_at, _, _ in chain}),
                    }
                )
    return clones


def reported_clones(clones):
    """The clones big enough to report, each pair once, best first."""
    kept = []
    seen = set()
    for clone in sorted(clones, key=lambda clone: -clone["tokens"]):
        floor = MIN_LOCAL_BLOCK_TOKENS if clone["local"] else MIN_BLOCK_TOKENS
        if min(clone["tokens"], clone["targetTokens"]) < floor:
            continue
        if min(clone["covered"] / clone["span"], clone["targetTokens"] / clone["targetSpan"]) < BLOCK_DENSITY:
            continue
        key = tuple(sorted([(clone["label"], clone["lines"]), (clone["target"][0], clone["targetLines"])]))
        if key not in seen:
            seen.add(key)
            kept.append(clone)
    return kept


def describe_block(label, body, lines):
    """How a report names a block: its method, its lines and its file."""
    owner = body["owner"].rsplit(".", 1)[-1]
    return f"{owner}.{body['name']} lines {lines[0]}-{lines[1]} ({label.replace(os.sep, '/')})"


def block_report_lines(clones):
    """One DuplicateBlock report per added block, naming up to MAX_SUGGESTIONS copies of it."""
    groups = []
    for clone in reported_clones(clones):
        for group in groups:
            first = group[0]
            if first["label"] == clone["label"] and (
                first["lines"][0] <= clone["lines"][1] and clone["lines"][0] <= first["lines"][1]
            ):
                group.append(clone)
                break
        else:
            groups.append([clone])
    reports = []
    for group in groups:
        first = group[0]
        copies = "; ".join(
            describe_block(clone["target"][0], clone["target"][1], clone["targetLines"])
            for clone in group[:MAX_SUGGESTIONS]
        )
        start, end = first["lines"]
        reports.append(
            f"{os.path.basename(first['label'])}:{start}: this block (lines {start}-{end}) repeats {copies}; "
            f"call it or extract a shared helper. [DuplicateBlock]"
        )
    return reports


def changed_sources(module):
    """The Java files the checkout's uncommitted diff touches under a module, each with its added
    lines (None for an untracked file)."""
    found = {}
    try:
        diff = subprocess.run(
            ["git", "-C", module, "diff", "-U0", "--relative", "HEAD", "--", "*.java"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.splitlines()
        untracked = subprocess.run(
            ["git", "-C", module, "ls-files", "--others", "--exclude-standard", "--", "*.java"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return found
    current = None
    for raw in diff:
        if raw.startswith("+++ "):
            name = raw[4:].strip()
            current = None if name == "/dev/null" else os.path.join(module, name[2:])
            if current is not None:
                found[os.path.normpath(current)] = set()
            continue
        match = DIFF_HUNK.match(raw)
        if match and current is not None:
            start = int(match.group("start"))
            found[os.path.normpath(current)].update(range(start, start + int(match.group("count") or 1)))
    for name in untracked:
        found[os.path.normpath(os.path.join(module, name))] = None
    return found


def block_targets(index, module, main_root, extra):
    """The bodies a block is checked against: the module's index plus changed sources outside it."""
    targets = list(index.bodies)
    for path, parsed in extra.items():
        if not os.path.abspath(path).startswith(main_root + os.sep):
            targets.extend((source_label(module, main_root, path), body) for body in parsed["bodies"])
    return targets


def added_block_reports(path, added):
    """The DuplicateBlock reports for blocks the change adds to one main or test source.

    The added code is checked against its own file, the change's other files and every body of
    the module's src/main/java.
    """
    located = module_of(path)
    if located is None:
        return []
    module, main_root = located
    index = load_index(main_root)
    parsed = read_source(path, True)
    if parsed is None:
        return []
    label = source_label(module, main_root, path)
    extra = {os.path.normpath(os.path.abspath(path)): parsed}
    changed = changed_sources(module)
    for other in changed:
        if other not in extra and not other.startswith(main_root + os.sep) and os.path.isfile(other):
            other_parsed = read_source(other, False)
            if other_parsed is not None:
                extra[other] = other_parsed
    targets = block_targets(index, module, main_root, extra)
    wanted = {value for body in parsed["bodies"] for value in body["hashes"]}
    queries = [(label, body, added) for body in parsed["bodies"]]
    change = {source_label(module, main_root, other) for other in changed}
    return block_report_lines(block_clones(queries, targets, print_lookup(wanted, targets), change))


def diff_reports(checkout):
    """Every DuplicateHelper and DuplicateBlock report on the lines a checkout's diff adds."""
    reports = []
    by_module = {}
    for path, added in changed_sources(checkout).items():
        located = module_of(path)
        if located is not None and os.path.isfile(path):
            by_module.setdefault(located, {})[path] = added
    for (module, main_root), changed in sorted(by_module.items()):
        index = load_index(main_root)
        parsed = {path: read_source(path, True) for path in changed}
        parsed = {path: entry for path, entry in parsed.items() if entry is not None}
        targets = block_targets(index, module, main_root, parsed)
        queries = [
            (source_label(module, main_root, path), body, changed[path])
            for path, entry in sorted(parsed.items())
            for body in entry["bodies"]
        ]
        wanted = {value for _, body, _ in queries for value in body["hashes"]}
        for path in sorted(parsed):
            if path.startswith(main_root + os.sep):
                reports.extend(added_method_reports(path, changed[path]))
        change = {source_label(module, main_root, path) for path in parsed}
        lookup = print_lookup(wanted, targets)
        reports.extend(block_report_lines(block_clones(queries, targets, lookup, change)))
    return reports


def module_blocks(root):
    """Every block clone between two bodies of a module, each pair once."""
    index = load_index(root)
    lookup = print_lookup(None, index.bodies)
    queries = []
    for relative in sorted(index.files):
        parsed = read_source(os.path.join(root, relative), True)
        if parsed is not None:
            queries.extend((relative, body, None) for body in parsed["bodies"])
    return reported_clones(block_clones(queries, index.bodies, lookup))


def main():
    """Lists every suggestion over a whole module, for judging the rules' hits.

    ``--blocks <module>/src/main/java`` lists the block clones instead, with the tokens each
    covers; ``--diff <checkout>`` prints the reports for the lines a checkout's uncommitted diff
    adds.
    """
    if sys.argv[1] == "--diff":
        reports = diff_reports(os.path.abspath(sys.argv[2]))
        for report in reports:
            print(report)
        print(f"{len(reports)} reports", file=sys.stderr)
        return 0
    if sys.argv[1] == "--blocks":
        clones = module_blocks(os.path.abspath(sys.argv[2]))
        for clone in clones:
            print(
                f"{min(clone['tokens'], clone['targetTokens'])} tokens, "
                f"{'same file' if clone['local'] else 'module'}: "
                f"{describe_block(clone['label'], clone['body'], clone['lines'])} ~ "
                f"{describe_block(clone['target'][0], clone['target'][1], clone['targetLines'])}"
            )
        print(f"{len(clones)} block clones", file=sys.stderr)
        return 0
    root = os.path.abspath(sys.argv[1])
    index = load_index(root)
    total = 0
    for relative, entry in sorted(index.files.items()):
        for method in entry["methods"]:
            if method["annotated"]:
                continue
            found = suggestions(index, relative, method)
            for suggestion in found:
                total += 1
                print(f"{relative}:{method['line']}: {method['name']} -> {suggestion}")
    print(f"{total} suggestions", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
