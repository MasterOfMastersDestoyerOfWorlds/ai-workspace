"""Find the code that already implements a ticket's papers, from the citations in its comments.

Ixdar cites papers at the port site in comments and Javadoc (``See also: LCBK19 Section 6.1``,
``L03 section 6``, ``BZK09 §5.2``, ``Liepa's density refinement``). A ticket that asks for a
paper's step names that paper by its cite key or by author and year, so listing every file, class
and method that cites the ticket's keys, with the section each cites, tells an agent what exists
before it writes anything.

The keys are the paper library's file names, ``<key> - <author> - <year> - <title>.pdf`` in
``~/QuadLayoutsPapersCompleted`` and ``~/QuadLayoutsPapersToRead``, with ``_`` standing for the
``*`` a file name cannot hold (``BCE_13`` is ``BCE*13``). A key matches its spellings with the
initials in any order (code writes ``LCBK19`` for the library's ``LCKB19``), with or without the
``*``. A paper whose author has no other paper in the library, or no other one that year, is also
found by name (``Liepa``, ``Liepa 2003``).
"""

import itertools
import re
import subprocess
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

PAPER_DIRS = (Path.home() / "QuadLayoutsPapersCompleted", Path.home() / "QuadLayoutsPapersToRead")
FIELD_SEPARATOR = re.compile(r" [-|] ")
KEY_PARTS = re.compile(r"^([A-Za-z]+)([*_+]?)(\d{2})([a-z]?)$")
KEY_TOKEN = re.compile(r"(?<![\w*])([A-Z][A-Za-z]{0,5}[*_+]?\d{2}[a-z]?)(?!\w)")
YEAR = re.compile(r"^(\d{4})")
TICKET_TEXT_FIELDS = ("title", "description", "definition-of-done", "testing-plan")
CITE_KEYS_FIELD = "cite-keys"
SECTION = (
    r"(?:Section|Sec\.?|§|Def(?:inition)?\.?|Eq(?:uation)?s?\.?|Alg(?:orithm)?\.?|Fig(?:ure)?\.?"
    r"|Theorem|Thm\.?|Lemma|Prop(?:osition)?\.?|Table|Appendix|App\.?|operator|step)"
    r"\s*(?:\(\d+\)|[A-Z]?\d+(?:\.\d+)*)"
)
SECTION_AFTER = re.compile(r"^(?:'s)?[\s,;:(]*(?:\d{4}\)?[\s,;:]*)?(" + SECTION + ")", re.IGNORECASE)
SECTION_BEFORE = re.compile("(" + SECTION + r")\s+(?:of|in)\s+$", re.IGNORECASE)
CODE_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|//|/\*')
COMMENT_LEAD = re.compile(r"^\s*\*+/?\s?")
MODIFIERS = r"(?:(?:public|protected|private|static|final|abstract|synchronized|native|default|strictfp|sealed|non-sealed|transient|volatile)\s+)*"
ANNOTATIONS = r"(?:@[\w.]+(?:\([^)]*\))?\s+)*"
CLASS_DECL = re.compile(r"(?<![.\w])(?:class|interface|enum|record)\s+([A-Z]\w*)")
METHOD_DECL = re.compile(
    "^" + ANNOTATIONS + MODIFIERS + r"(?:<[^>]*>\s+)?(?:[\w.$]+(?:<[^()]*?>)?(?:\[\])*\s+)?(\w+)\s*\("
)
FIELD_DECL = re.compile("^" + ANNOTATIONS + MODIFIERS + r"[\w.$]+(?:<[^=;]*>)?(?:\[\])*\s+(\w+)\s*(?:=|;|,)")
NOT_A_DECLARATION = re.compile(r"^(?:package|import)\b|^@[\w.]+(?:\(.*\))?\s*$")
STATEMENT_WORDS = frozenset(
    "if for while switch catch return new throw else synchronized try do super this assert yield".split()
)
SOURCE_SUFFIX = "*.java"
MEMBERS_PER_KEY = 40


@dataclass(frozen=True)
class Paper:
    """One paper of the library: its cite key as code writes it, first author, year and title."""

    key: str
    author: str
    year: str
    title: str

    def label(self):
        """Author, year and title in ASCII, so a Windows console prints the brief without an encoding error."""
        text = ", ".join(part for part in (f"{self.author} {self.year}".strip(), self.title) if part)
        text = re.sub("[‐-―]", "-", unicodedata.normalize("NFKD", text))
        return text.encode("ascii", "ignore").decode("ascii")


@dataclass(frozen=True)
class Citation:
    """One comment line citing a paper: where, which declaration it documents or sits in, and the section."""

    path: str
    line: int
    owner: str
    section: str
    by_name: bool


def canonical(key):
    """The form two spellings of one key share: initials sorted, no ``*``, digits and suffix kept.

    :param key: a cite key such as ``LCBK19``, ``BCE*13`` or ``BCE_13``
    :return: the canonical form, or None when the text is not shaped like a key
    """
    parts = KEY_PARTS.match(key.strip())
    if not parts:
        return None
    letters, _marker, digits, suffix = parts.groups()
    return "".join(sorted(letters.upper())) + digits + suffix


def library(directories=PAPER_DIRS):
    """Every paper in the library folders, keyed by canonical cite key.

    The fields are split on `` - `` (Windows, where a file name cannot hold ``|`` or ``*``) or on
    `` | `` (Linux, where the key keeps its ``*``, as in ``BCE*13 | Bommes | 2013 | ...``).

    :param directories: the folders whose ``<key> - <author> - <year> - <title>.pdf`` files name the papers
    :return: {canonical key: Paper}
    """
    papers = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        for pdf in sorted(directory.glob("*.pdf")):
            parts = [part.strip() for part in FIELD_SEPARATOR.split(pdf.stem)]
            key = parts[0].replace("_", "*")
            form = canonical(key)
            if not form or form in papers:
                continue
            rest = parts[1:]
            author = year = ""
            if rest and not YEAR.match(rest[0]):
                author = rest.pop(0)
            if rest and YEAR.match(rest[0]):
                year = YEAR.match(rest[0]).group(1)
                rest[0] = rest[0][4:].lstrip("_ ")
            papers[form] = Paper(key, author, year, " - ".join(part for part in rest if part))
    return papers


def name_patterns(paper, papers):
    """The patterns that find a paper by its author's name, when the name alone or with the year is unambiguous.

    :param paper: the paper to find
    :param papers: the whole library, to tell whether the author has other papers
    :return: compiled patterns, possibly none
    """
    if not paper.author or not re.fullmatch(r"[A-Z][\w'-]+", paper.author):
        return []
    same_author = [other for other in papers.values() if other.author == paper.author]
    author = re.escape(paper.author)
    if len(same_author) == 1:
        return [re.compile(rf"\b{author}\b")]
    if paper.year and sum(other.year == paper.year for other in same_author) == 1:
        return [re.compile(rf"\b{author}\b[^\n]{{0,15}}?\b{paper.year}\b")]
    return []


def ticket_keys(ticket, papers):
    """The cite keys a ticket names: its ``cite-keys`` field, then keys and author-year mentions in its text.

    :param ticket: the ticket JSON
    :param papers: the library, {canonical key: Paper}
    :return: [(key as written, canonical key)] in first-mention order, one per paper
    """
    found = {}
    for key in ticket.get(CITE_KEYS_FIELD) or []:
        form = canonical(key)
        if form:
            found.setdefault(form, key.strip())
    text = "\n".join(str(ticket.get(field) or "") for field in TICKET_TEXT_FIELDS)
    for token in KEY_TOKEN.findall(text):
        form = canonical(token)
        if form in papers:
            found.setdefault(form, token)
    for form, paper in papers.items():
        if not paper.year:
            continue
        mention = (
            re.compile(rf"\b{re.escape(paper.author)}\b[^\n]{{0,15}}?\b{paper.year}\b")
            if paper.author
            else None
        )
        if form not in found and mention and mention.search(text) and len(name_patterns(paper, papers)) == 1:
            found[form] = paper.key
    return [(written, form) for form, written in found.items()]


def key_pattern(key):
    """The pattern matching every spelling of a key: its initials in any order, with or without ``*``.

    :param key: the key as written
    :return: a compiled pattern
    """
    letters, _marker, digits, suffix = KEY_PARTS.match(key.strip()).groups()
    orders = {"".join(order) for order in itertools.permutations(letters)} if len(letters) <= 5 else {letters}
    spellings = sorted(
        {order + marker for order in orders for marker in ("", "*", "_", "+")}, key=len, reverse=True
    )
    alternatives = "|".join(re.escape(spelling) for spelling in spellings)
    return re.compile(rf"(?<![\w*])(?:{alternatives}){digits}{suffix}(?!\w)")


def split_line(line, in_block):
    """Separate one source line into its code and its comment text.

    :param line: the line
    :param in_block: whether a ``/*`` comment is open at the line's start
    :return: (code with string literals blanked, comment text, whether a block comment is still open)
    """
    code, comment = [], []
    index = 0
    while index < len(line):
        if in_block:
            end = line.find("*/", index)
            if end < 0:
                comment.append(line[index:])
                break
            comment.append(line[index:end])
            index, in_block = end + 2, False
            continue
        token = CODE_TOKEN.search(line, index)
        if not token:
            code.append(line[index:])
            break
        code.append(line[index : token.start()])
        if token.group() == "//":
            comment.append(line[token.end() :])
            break
        if token.group() == "/*":
            in_block = True
        else:
            code.append('""')
        index = token.end()
    text = " ".join(COMMENT_LEAD.sub("", part).strip() for part in comment).strip()
    return "".join(code), text, in_block


def section_near(text, start, end):
    """The section a citation names right after (or just before) the key: ``Section 6.1``, ``§5``, ``Def 6.2``.

    :param text: the comment text, with the next comment line joined on so a wrapped section is seen
    :param start: where the key starts in it
    :param end: where the key ends in it
    :return: the section, whitespace collapsed, or ""
    """
    found = SECTION_AFTER.match(text[end:]) or SECTION_BEFORE.search(text[:start])
    if not found:
        return ""
    return " ".join(found.group(1).replace("§", "Section ").split())


def scan_file(path, relative, matchers):
    """Every citation of the wanted papers in one Java file's comments.

    A Javadoc or block comment between members documents the declaration after it; a comment
    inside a method body belongs to that method.

    :param path: the file
    :param relative: its path as reported
    :param matchers: {canonical key: [(pattern, by name)]}
    :return: {canonical key: [Citation]}
    """
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    split, in_block = [], False
    for line in lines:
        code, comment, in_block = split_line(line, in_block)
        split.append((code, comment))
    found = {}
    scopes = []
    pending = []
    pending_class = None
    depth = 0
    for number, (code, comment) in enumerate(split, start=1):
        if comment:
            following = split[number][1] if number < len(split) and not split[number][0].strip() else ""
            joined = f"{comment} {following}"
            for form, patterns in matchers.items():
                for pattern, by_name in patterns:
                    match = pattern.search(comment)
                    if not match:
                        continue
                    section = section_near(joined, match.start(), match.end())
                    inside = scopes and depth > scopes[-1][1]
                    if inside and scopes[-1][2]:
                        owner = f"{'.'.join(scope[0] for scope in scopes)}.{scopes[-1][2]}()"
                        found.setdefault(form, []).append(Citation(relative, number, owner, section, by_name))
                    else:
                        pending.append((form, number, section, by_name))
                    break
        stripped = code.strip()
        if not stripped:
            continue
        if NOT_A_DECLARATION.search(stripped):
            continue
        prefix = ".".join(scope[0] for scope in scopes)
        declared_class = CLASS_DECL.search(stripped)
        member = ""
        at_body = not scopes or depth == scopes[-1][1]
        if declared_class:
            pending_class = (declared_class.group(1), depth + 1)
            owner = f"{prefix}.{declared_class.group(1)}" if prefix else declared_class.group(1)
        elif at_body and scopes:
            method = METHOD_DECL.match(stripped)
            field = FIELD_DECL.match(stripped)
            if method and method.group(1) not in STATEMENT_WORDS:
                member = method.group(1)
                scopes[-1][2] = member
                owner = f"{prefix}.{member}()"
            elif field:
                owner = f"{prefix}.{field.group(1)}"
            else:
                owner = prefix
        else:
            owner = prefix or path.stem
        for form, line_number, section, by_name in pending:
            found.setdefault(form, []).append(Citation(relative, line_number, owner, section, by_name))
        pending = []
        depth += stripped.count("{") - stripped.count("}")
        if pending_class and depth >= pending_class[1]:
            scopes.append([pending_class[0], pending_class[1], ""])
            pending_class = None
        while scopes and depth < scopes[-1][1]:
            scopes.pop()
        if scopes and depth == scopes[-1][1] and not member and stripped.endswith("}"):
            scopes[-1][2] = ""
    return found


def scan(worktree, keys, papers):
    """Every citation of the given keys in the worktree's Java sources, tracked and new files alike.

    :param worktree: the checkout to scan
    :param keys: [(key as written, canonical key)] from ``ticket_keys``
    :param papers: the library, {canonical key: Paper}
    :return: {canonical key: [Citation]}
    """
    matchers = {}
    for written, form in keys:
        patterns = [(key_pattern(written), False)]
        paper = papers.get(form)
        if paper:
            patterns += [(pattern, True) for pattern in name_patterns(paper, papers)]
        matchers[form] = patterns
    if not matchers:
        return {}
    listing = subprocess.run(
        ["git", "-C", str(worktree), "ls-files", "-co", "--exclude-standard", "--", SOURCE_SUFFIX],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.splitlines()
    found = {}
    for relative in listing:
        path = Path(worktree) / relative
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not any(pattern.search(text) for patterns in matchers.values() for pattern, _ in patterns):
            continue
        for form, citations in scan_file(path, relative, matchers).items():
            found.setdefault(form, []).extend(citations)
    return found


def report_lines(worktree, ticket, papers=None):
    """The brief's list of the code that already cites the ticket's papers, one block per key.

    :param worktree: the checkout to scan
    :param ticket: the ticket JSON, or None
    :param papers: the library; read from the paper folders when not given
    :return: the lines to print, empty when the ticket names no paper
    """
    papers = library() if papers is None else papers
    keys = ticket_keys(ticket or {}, papers)
    if not keys:
        return []
    started = time.perf_counter()
    found = scan(worktree, keys, papers)
    elapsed = time.perf_counter() - started
    lines = [
        f"papers:   code that already cites the ticket's papers (comments and Javadoc; scanned in {elapsed:.1f}s);",
        "          start from it: say per section what exists, what is missing and what will change before coding",
    ]
    for written, form in keys:
        paper = papers.get(form)
        label = f" ({paper.label()})" if paper else " (not in the paper library)"
        citations = found.get(form, [])
        if not citations:
            lines.append(f"  {written}{label}: nothing in the code cites it")
            continue
        files = sorted({citation.path for citation in citations})
        lines.append(f"  {written}{label}: {len(citations)} citation(s) in {len(files)} file(s)")
        shown = 0
        for file in files:
            members = {}
            for citation in citations:
                if citation.path == file:
                    sections, first, by_name = members.get(citation.owner, (set(), citation.line, True))
                    if citation.section:
                        sections.add(citation.section)
                    members[citation.owner] = (
                        sections,
                        min(first, citation.line),
                        by_name and citation.by_name,
                    )
            if shown >= MEMBERS_PER_KEY:
                break
            lines.append(f"    {file}")
            for owner, (sections, first, by_name) in sorted(members.items(), key=lambda item: item[1][1]):
                if shown >= MEMBERS_PER_KEY:
                    break
                cited = ", ".join(sorted(sections)) or ("by name" if by_name else "no section")
                lines.append(f"      {owner:<48} {cited}  :{first}")
                shown += 1
        total = sum(len({c.owner for c in citations if c.path == file}) for file in files)
        if total > shown:
            lines.append(f"    ... {total - shown} more declaration(s); grep the key for the rest")
    return lines
