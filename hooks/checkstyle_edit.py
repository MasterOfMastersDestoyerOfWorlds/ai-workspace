#!/usr/bin/env python3
"""PostToolUse hook on Edit and Write: runs checkstyle on the one Java file that changed.

JavadocDescriptionLength is the top build blocker in the 2026-09-08 tool review — 16 violations
across four agents, and one agent spent three full module compiles trimming a description from
81 words to 65 to 54. Checkstyle on a single file takes about a second, so the violation can
reach the model at edit time instead of after a compile.

The configuration is the one the Ixdar build uses: `checkstyle.xml` is read off the classpath
out of the autofix-tool artifact, exactly as maven-checkstyle-plugin reads it. The resolved
classpath is cached under ~/.cache, so only the first edit of a session pays maven.

A second pass runs two checks the build leaves off because the codebase holds many old
violations: SingleCallerHelperCheck (a private method with one or two callers should be inlined there)
and MethodVisibilityCheck (a method is public or private, never protected or package-private,
which is how a helper used to dodge the single-caller check). Here the pass is incremental: only a
method declared on a line the file's uncommitted diff adds is reported, so new code is caught when
it is written and old code stays quiet. There is no opt-out comment. The visibility rule applies
only under src/main/java, matching the build, which does not check test sources.

The same pass runs MethodLength at 150 lines (master holds 36 methods past it, the longest 911,
so the build cannot enforce it). A long method is reported when the change adds any line inside
it, and the message asks for a rethink: repeated code and mixed jobs moved into reusable pieces
with more than one user, not single-caller helpers that hide the same complexity. On 2026-10-31
a 480-line node method and a method past HotSpot's 8000-byte JIT limit (about ten times slower,
never compiled) both went through review unflagged.

It also flags a hand-written union-find (a parent array walked to its root, or path-halved) and
points at ixdar.numeric.graph.UnionFind: the same day a node re-implemented it inline.

Two more checks hold Ixdar CLAUDE.md's prose rules on added lines. SystemProperty flags a new
System.getProperty (or Boolean.getBoolean and the like) knob, which the "No system properties"
section forbids: on 2026-11-22 an agent added one for a debug flag. The comment pass flags a new //
comment, which the "Comments" section defaults to none, and says where it sits: inside a method
body it is LineComment (keep only a non-obvious why); outside one, at file level or between a
class's members, it is CommentOutsideMethod, which has no legitimate use: the same agent moved a
Javadoc past its length limit into // lines between the Javadoc and the class instead of
shortening it. Braces are counted on the source with strings, characters and comments blanked, and
a block opened after a class, interface, enum or record keyword is a type body.

SingleCallerHelperCheck sees one file and so only private methods; on 2026-10-06 two agents made a
one-caller helper public so a test could call it. A third pass covers that: every public method a
main source adds is looked up across the checkout's src/main/java trees by name, and one with two
call sites or fewer there, all in its own file, is reported. Test sources are not searched, so test calls never count.
The lookup is by name, so an overload or a same-named method elsewhere can hide a real single
caller; methods carrying an annotation (@Override and the framework hooks) are skipped.

Two more catch code written somewhere other than where its concept lives (TOOL-63), both on main
sources only. FeatureEnvyCheck, in the checkstyle pass, reports an added method that uses none of
its class's instance state and mostly another type it takes as a parameter ("lastOfKind() mostly
uses GraphNodeContext: move it there"). method_index.py reports an added method that may already
exist in the module: the same normalised body, the same signature and name words, or a method
named like it on one of its parameter types ("ringCentroid: did you mean PackedPoints.ringMean,
its int[][] from MeshTopology.oneRings()?"). It also reports a block the change adds, in a main or
a test source, that repeats one in the same file, the change or the module, gapped copies
included ("this block (lines a-b) repeats PolygonScan.convexHull lines c-d [DuplicateBlock]").
Its index is cached under ~/.cache, so only the first edit in a module pays the full read. Package boundaries are not checked here: they are ArchUnit
tests in Ixdar's unit suite.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, HOOKS_DIR)
sys.path.insert(1, os.path.dirname(HOOKS_DIR))

from hook_common import block, read_event  # noqa: E402
from ixd.paths import repo_path  # noqa: E402
from method_index import added_block_reports, added_method_reports  # noqa: E402

CACHE_DIR = os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
    "ai-workspace-hooks",
)

CLASSPATH_CACHE = os.path.join(CACHE_DIR, "checkstyle-classpath.txt")

AUTOFIX_CHECKOUT = repo_path("autofix")

AUTOFIX_CHECKOUT_POM = str(AUTOFIX_CHECKOUT / "pom.xml")

CHECKSTYLE_MAIN = "com.puppycrawl.tools.checkstyle.Main"

CHECKSTYLE_CONFIGURATION = "checkstyle.xml"

# Seconds allowed for maven to resolve the classpath and for checkstyle to audit one file.
MAVEN_TIMEOUT_SECONDS = 120

CHECKSTYLE_TIMEOUT_SECONDS = 60

VIOLATION_LINE = re.compile(r"^\[(?:ERROR|WARN)\]\s*(?P<body>.*)$")

INCREMENTAL_CONFIGURATION = os.path.join(CACHE_DIR, "incremental-checkstyle.xml")

# A helper with this many call sites or fewer is reported, matching SingleCallerHelperCheck.
MOST_CALLERS_FLAGGED = 2

INCREMENTAL_CONFIGURATION_TEXT = """<?xml version="1.0"?>
<!DOCTYPE module PUBLIC "-//Checkstyle//DTD Checkstyle Configuration 1.3//EN"
    "https://checkstyle.org/dtds/configuration_1_3.dtd">
<module name="Checker">
  <module name="TreeWalker">
    <module name="ixdar.autofix.checkstyle.SingleCallerHelperCheck"/>
    <module name="ixdar.autofix.checkstyle.MethodVisibilityCheck"/>
    <module name="ixdar.autofix.checkstyle.FeatureEnvyCheck"/>
    <module name="MethodLength">
      <property name="max" value="150"/>
      <property name="tokens" value="METHOD_DEF,CTOR_DEF"/>
      <message key="maxLen.method"
               value="Method is {0} lines (rethink past {1}): a method this long hides its structure. Find the code it repeats and the separate jobs it mixes, and move each into a reusable piece with more than one user (an existing class or node, or a new named concept); splitting it into single-caller private helpers only hides the same complexity."/>
    </module>
    <module name="RegexpSinglelineJava">
      <property name="id" value="InlineUnionFind"/>
      <property name="format"
                value="while\\s*\\(\\s*(\\w+)\\[(\\w+)\\]\\s*!=\\s*\\2\\s*\\)|(\\w+)\\[\\w+\\]\\s*=\\s*\\3\\[\\3\\["/>
      <property name="ignoreComments" value="true"/>
      <property name="message"
                value="Hand-written union-find (a parent array walked to its root): use ixdar.numeric.graph.UnionFind (singletons, find, union, unionByRank, grow) instead. [InlineUnionFind]"/>
    </module>
    <module name="RegexpSinglelineJava">
      <property name="id" value="SystemProperty"/>
      <property name="format"
                value="\\b(System\\.getProperty|Boolean\\.getBoolean|Integer\\.getInteger|Long\\.getLong)\\s*\\("/>
      <property name="ignoreComments" value="true"/>
      <property name="message"
                value="A system property knob: Ixdar CLAUDE.md (No system properties) forbids them. Make it a public field on the owning class with a behaviour-describing name, or delete the switch; only properties that choose an input file (ixdar.model, benchmark.off) are allowed."/>
    </module>
  </module>
</module>
"""

METHOD_LENGTH_SPAN = re.compile(r"Method is (?P<length>\d+) lines")

VIOLATION_POSITION = re.compile(r"^[^:]+:(?P<line>\d+):")

METHOD_VISIBILITY_TAG = "[MethodVisibility]"

FEATURE_ENVY_TAG = "[FeatureEnvy]"

MAIN_SOURCE_SEGMENT = os.path.join("src", "main", "java") + os.sep

CHARACTER_OR_STRING_LITERAL = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')

TYPE_KEYWORD = re.compile(r"\b(?:class|interface|enum|record)\b")

LINE_COMMENT_ADVICE = (
    "A line comment in a method: Ixdar CLAUDE.md (Comments) defaults to none. Keep it only for a "
    "non-obvious why (a hidden constraint, a citation, a workaround); otherwise delete it."
)

COMMENT_OUTSIDE_METHOD_ADVICE = (
    "A // comment outside a method body (at file level or between a class's members): what a "
    "class or member is goes in its Javadoc, shortened to fit the length limit, never in // lines "
    "beside it. Fold it into the Javadoc or delete it."
)

PUBLIC_METHOD = re.compile(
    r"^\s*public\s+(?:(?:static|final|synchronized|native|abstract|default)\s+)*"
    r"(?:<[^>]*>\s+)?[\w.$<>\[\],? ]+?\s+(?P<name>[a-zA-Z_$][\w$]*)\s*\("
)

ANNOTATION_LINE = re.compile(r"^\s*@\w")

# Declarations look like `<type> name(`; anything else naming `name(` or `::name` is a use.
DECLARATION_OF_TEMPLATE = (
    r"^\s*(?:(?:public|private|protected|static|final|synchronized|abstract|native|default)\s+)*"
    r"(?:<[^>]*>\s+)?(?!(?:return|new|throw|else|case|yield)\b)[\w$][\w.$<>\[\],? ]*?\s+{0}\s*\("
)

# POSIX extended syntax, shared by grep -E and Python: no (?:...) groups.
CALL_OF_TEMPLATE = r"\b{0}\s*\(|::\s*{0}\b"

DIFF_HUNK = re.compile(r"^@@ -\S+ \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")

DEPENDENCY_VERSION_TEMPLATE = r"<artifactId>{0}</artifactId>\s*<version>([^<]+)</version>"

GENERATED_POM_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>ai.workspace.hooks</groupId>
  <artifactId>checkstyle-classpath</artifactId>
  <version>0.0.1</version>
  <packaging>pom</packaging>
  <dependencies>
    <dependency>
      <groupId>com.puppycrawl.tools</groupId>
      <artifactId>checkstyle</artifactId>
      <version>{checkstyle}</version>
    </dependency>
    <dependency>
      <groupId>IXDAR</groupId>
      <artifactId>autofix-tool</artifactId>
      <version>{autofix}</version>
    </dependency>
  </dependencies>
</project>
"""

UNAVAILABLE_ADVICE = (
    "The ai-workspace checkstyle hook could not assemble a checkstyle classpath, so Java edits "
    "are not being checked at edit time. Build Ixdar once (mvn -q compile from its root) to "
    "populate ~/.m2, then edits will be checked again. Until then the "
    "first compile is still the only place violations show up."
)


class ClasspathUnavailable(Exception):
    """Raised when no jar set can be assembled, so the hook must fall back to a message."""


def edited_file(event):
    """Returns the path an Edit or Write event touched, or None."""
    tool_input = event.get("tool_input") or {}
    path = tool_input.get("file_path")
    return path if isinstance(path, str) and path else None


def find_ixdar_root(path):
    """Returns the checkout or worktree root whose pom runs checkstyle with autofix-tool.

    Every Ixdar worktree carries its own root pom, so this also identifies a worktree.
    """
    current = os.path.dirname(os.path.abspath(path))
    while True:
        candidate = os.path.join(current, "pom.xml")
        if os.path.isfile(candidate):
            try:
                with open(candidate, encoding="utf-8") as handle:
                    text = handle.read()
            except OSError:
                text = ""
            if "maven-checkstyle-plugin" in text and "autofix-tool" in text:
                return current, text
        parent = os.path.dirname(current)
        if parent == current:
            return None, ""
        current = parent


def dependency_version(pom_text, artifact):
    """Returns the version the pom pins for an artifact, or None."""
    match = re.search(DEPENDENCY_VERSION_TEMPLATE.format(artifact), pom_text)
    return match.group(1).strip() if match else None


def autofix_artifact_jar(version):
    """Returns the installed autofix-tool jar, or its class directory, or None."""
    jar = os.path.expanduser(f"~/.m2/repository/IXDAR/autofix-tool/{version}/autofix-tool-{version}.jar")
    if os.path.isfile(jar):
        return jar
    classes = str(AUTOFIX_CHECKOUT / "target" / "classes")
    return classes if os.path.isdir(classes) else None


def run_build_classpath(pom_path, output_path, offline):
    """Asks maven for a pom's runtime classpath, returning True when it wrote the file.

    The executable is resolved through PATH first: on Windows maven is ``mvn.cmd``, which a bare
    ``mvn`` never starts without a shell, and the failure would read as an unresolvable classpath.
    """
    command = [
        shutil.which("mvn") or "mvn",
        "-B",
        "-q",
        "dependency:build-classpath",
        f"-Dmdep.outputFile={output_path}",
        "-f",
        pom_path,
    ]
    if offline:
        command.insert(1, "-o")
    try:
        subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=MAVEN_TIMEOUT_SECONDS,
            check=False,
            cwd=os.path.dirname(pom_path) or None,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return os.path.isfile(output_path) and os.path.getsize(output_path) > 0


def resolve_classpath(pom_text):
    """Assembles the jars maven-checkstyle-plugin would run with, caching the result."""
    cached = read_cached_classpath()
    if cached:
        return cached

    os.makedirs(CACHE_DIR, exist_ok=True)
    checkstyle_version = dependency_version(pom_text, "checkstyle")
    autofix_version = dependency_version(pom_text, "autofix-tool")
    if not checkstyle_version or not autofix_version:
        raise ClasspathUnavailable("the Ixdar pom does not pin checkstyle and autofix-tool")

    generated_pom = os.path.join(CACHE_DIR, "pom.xml")
    with open(generated_pom, "w", encoding="utf-8") as handle:
        handle.write(GENERATED_POM_TEMPLATE.format(checkstyle=checkstyle_version, autofix=autofix_version))

    output_path = os.path.join(CACHE_DIR, f"classpath.raw.{os.getpid()}")
    attempts = [(generated_pom, True)]
    if os.path.isfile(AUTOFIX_CHECKOUT_POM):
        attempts.append((AUTOFIX_CHECKOUT_POM, True))
    attempts.append((generated_pom, False))

    entries = []
    for pom_path, offline in attempts:
        if os.path.exists(output_path):
            os.remove(output_path)
        if not run_build_classpath(pom_path, output_path, offline):
            continue
        with open(output_path, encoding="utf-8") as handle:
            entries = [entry for entry in handle.read().strip().split(os.pathsep) if entry]
        if entries:
            break

    if not entries:
        raise ClasspathUnavailable("maven could not resolve the checkstyle dependencies")

    artifact = autofix_artifact_jar(autofix_version)
    if artifact is None:
        raise ClasspathUnavailable("the autofix-tool artifact is not installed in ~/.m2")
    if artifact not in entries:
        entries.append(artifact)

    classpath = os.pathsep.join(entries)
    pending = f"{CLASSPATH_CACHE}.{os.getpid()}"
    with open(pending, "w", encoding="utf-8") as handle:
        handle.write(classpath)
    os.replace(pending, CLASSPATH_CACHE)
    if os.path.exists(output_path):
        os.remove(output_path)
    return classpath


def read_cached_classpath():
    """Returns the cached classpath when every entry it names still exists."""
    try:
        with open(CLASSPATH_CACHE, encoding="utf-8") as handle:
            classpath = handle.read().strip()
    except OSError:
        return None
    entries = [entry for entry in classpath.split(os.pathsep) if entry]
    if not entries or not all(os.path.exists(entry) for entry in entries):
        return None
    return classpath


def run_checkstyle(classpath, path, configuration=CHECKSTYLE_CONFIGURATION):
    """Audits one Java file, returning checkstyle's combined output."""
    java = os.path.join(os.environ["JAVA_HOME"], "bin", "java") if os.environ.get("JAVA_HOME") else "java"
    try:
        finished = subprocess.run(
            [java, "-cp", classpath, CHECKSTYLE_MAIN, "-c", configuration, path],
            capture_output=True,
            text=True,
            timeout=CHECKSTYLE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ClasspathUnavailable(f"checkstyle did not run ({error})") from error
    output = finished.stdout + finished.stderr
    # A configuration checkstyle cannot load reports no violations at all, which would read as a
    # clean file.
    if "Unable to create Root Module" in output or "unable to parse configuration" in output:
        raise ClasspathUnavailable(f"checkstyle could not load {configuration}: {output.strip()[:300]}")
    return output


def added_lines(path):
    """Returns the line numbers the file's uncommitted diff adds, or None when all of it is new.

    In an Ixdar worktree HEAD is the base tip, so this is exactly the proposed change. An untracked
    file that git sees as a rename of a file the change deletes (a class moved to another package)
    counts only the lines the move changed, so existing helpers are not reported as new.
    """
    directory = os.path.dirname(os.path.abspath(path))
    try:
        tracked = subprocess.run(
            ["git", "-C", directory, "ls-files", "--error-unmatch", path],
            capture_output=True,
            text=True,
            check=False,
        )
        if tracked.returncode != 0:
            return moved_file_added_lines(directory, path)
        diff = subprocess.run(
            ["git", "-C", directory, "diff", "-U0", "HEAD", "--", path],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    return hunk_lines(diff.stdout.splitlines())


def moved_file_added_lines(directory, path):
    """The added lines of an untracked file that is a rename, or None when it is genuinely new.

    The working tree is staged into a scratch index so the real index is untouched, then diffed
    against HEAD with rename detection.
    """
    toplevel = subprocess.run(
        ["git", "-C", directory, "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
    ).stdout.strip()
    relative = os.path.relpath(os.path.abspath(path), toplevel)
    with tempfile.TemporaryDirectory() as scratch:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(scratch, "index")}
        for step in (["read-tree", "HEAD"], ["add", "-A", "--", "*.java"]):
            subprocess.run(["git", "-C", toplevel, *step], env=env, capture_output=True, check=False)
        diff = subprocess.run(
            ["git", "-C", toplevel, "diff", "--cached", "-M", "--no-prefix", "-U0", "HEAD", "--", "*.java"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        ).stdout.splitlines()
    section = []
    for raw in diff:
        if raw.startswith("diff --git "):
            if section and f"rename to {relative}" in section:
                return hunk_lines(section)
            section = []
        section.append(raw)
    if section and f"rename to {relative}" in section:
        return hunk_lines(section)
    return None


def hunk_lines(diff_lines):
    """The new-file line numbers covered by the hunks of a ``-U0`` diff."""
    lines = set()
    for raw in diff_lines:
        match = DIFF_HUNK.match(raw)
        if match:
            start = int(match.group("start"))
            count = int(match.group("count") or 1)
            lines.update(range(start, start + count))
    return lines


def new_method_violations(classpath, path):
    """Returns the single-caller and visibility violations on lines this change adds."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(INCREMENTAL_CONFIGURATION, "w", encoding="utf-8") as handle:
        handle.write(INCREMENTAL_CONFIGURATION_TEXT)
    flagged = violation_lines(run_checkstyle(classpath, path, INCREMENTAL_CONFIGURATION), path)
    if not flagged:
        return []
    main_source = MAIN_SOURCE_SEGMENT in os.path.abspath(path)
    added = added_lines(path)
    reports = []
    for line in flagged:
        position = VIOLATION_POSITION.match(line)
        if position is None:
            continue
        start = int(position.group("line"))
        # A long method is reported when the change adds any line inside it, not only its
        # declaration: methods grow long a few lines at a time.
        span = METHOD_LENGTH_SPAN.search(line)
        lines = range(start, start + int(span.group("length"))) if span else (start,)
        if added is not None and not any(number in added for number in lines):
            continue
        if not main_source and line.endswith((METHOD_VISIBILITY_TAG, FEATURE_ENVY_TAG)):
            continue
        reports.append(line)
    return reports


def public_single_caller_violations(root, path):
    """Returns the public methods this change adds that main code calls from one place or none."""
    if MAIN_SOURCE_SEGMENT not in os.path.abspath(path):
        return []
    try:
        with open(path, encoding="utf-8") as handle:
            source = handle.read().splitlines()
    except OSError:
        return []
    added = added_lines(path)
    candidates = []
    for number, line in enumerate(source, start=1):
        if added is not None and number not in added:
            continue
        match = PUBLIC_METHOD.match(line)
        if match is None or match.group("name") == "main" or " class " in line:
            continue
        previous = number - 2
        while previous >= 0 and (
            not source[previous].strip() or source[previous].strip().startswith(("*", "/"))
        ):
            previous -= 1
        if previous >= 0 and ANNOTATION_LINE.match(source[previous]):
            continue
        candidates.append((number, match.group("name")))
    if not candidates:
        return []
    main_trees = [
        os.path.join(directory, "src", "main", "java")
        for directory in [root] + [os.path.join(root, entry) for entry in sorted(os.listdir(root))]
        if os.path.isdir(os.path.join(directory, "src", "main", "java"))
    ]
    reports = []
    for number, name in candidates:
        try:
            found = subprocess.run(
                ["grep", "-rHE", "--include=*.java", CALL_OF_TEMPLATE.format(name), *main_trees],
                capture_output=True,
                text=True,
                timeout=CHECKSTYLE_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        # grep exits 1 for no match and 2 for an error; an error must not read as "no callers".
        if found.returncode > 1:
            continue
        declaration = re.compile(DECLARATION_OF_TEMPLATE.format(re.escape(name)))
        call = re.compile(CALL_OF_TEMPLATE.format(re.escape(name)))
        # A public method another class calls is an API, whatever its caller count; the case
        # reported is a helper only its own file uses, made public for a test or for nothing.
        own_file = os.path.realpath(path)
        own_calls = 0
        other_calls = 0
        for hit in found.stdout.splitlines():
            source_file, _, text = hit.partition(":")
            if declaration.match(text):
                continue
            count = len(call.findall(text))
            if os.path.realpath(source_file) == own_file:
                own_calls += count
            else:
                other_calls += count
        if other_calls == 0 and own_calls <= MOST_CALLERS_FLAGGED:
            where = f"{own_calls} call site(s), in its own file" if own_calls else "no call site"
            reports.append(
                f"{os.path.basename(path)}:{number}: public '{name}()' has {where}, in main "
                f"sources (tests do not count): inline it at its caller, or delete it; a test is "
                f"no reason to make a helper public. [PublicSingleCaller]"
            )
    return reports


def duplicate_helper_violations(path):
    """Returns the "did you mean" reports for main-source methods this change adds, and the
    DuplicateBlock reports for blocks it adds to a main or test source."""
    added = added_lines(path)
    blocks = added_block_reports(path, added)
    if MAIN_SOURCE_SEGMENT not in os.path.abspath(path):
        return blocks
    return added_method_reports(path, added) + blocks


def comment_violations(path):
    """Returns the // comments this change adds, named by whether they sit in a method body."""
    try:
        with open(path, encoding="utf-8") as handle:
            source = handle.read().splitlines()
    except OSError:
        return []
    added = added_lines(path)
    name = os.path.basename(path)
    type_bodies = []
    pending = ""
    in_block_comment = False
    reports = []
    for number, raw in enumerate(source, start=1):
        line = CHARACTER_OR_STRING_LITERAL.sub('""', raw)
        comment_at = None
        index = 0
        while index < len(line):
            if in_block_comment:
                end = line.find("*/", index)
                if end < 0:
                    break
                in_block_comment = False
                index = end + 2
                continue
            if line.startswith("/*", index):
                in_block_comment = True
                index += 2
                continue
            if line.startswith("//", index):
                comment_at = index
                break
            character = line[index]
            if character == "{":
                type_bodies.append(bool(TYPE_KEYWORD.search(pending)))
                pending = ""
            elif character == "}":
                if type_bodies:
                    type_bodies.pop()
                pending = ""
            elif character == ";":
                pending = ""
            else:
                pending += character
            index += 1
        if comment_at is None or (added is not None and number not in added):
            continue
        if not type_bodies or type_bodies[-1]:
            reports.append(f"{name}:{number}: {COMMENT_OUTSIDE_METHOD_ADVICE} [CommentOutsideMethod]")
        else:
            reports.append(f"{name}:{number}: {LINE_COMMENT_ADVICE} [LineComment]")
    return reports


def violation_lines(output, path):
    """Extracts the reported violations, shortening the repeated absolute path.

    Checkstyle prints the path with the platform's separators, which need not match the event's;
    an unshortened Windows path would also break VIOLATION_POSITION on its drive-letter colon.
    """
    name = os.path.basename(path)
    spellings = {path, os.path.normpath(path), os.path.abspath(path)}
    lines = []
    for raw in output.splitlines():
        match = VIOLATION_LINE.match(raw.strip())
        if match:
            body = match.group("body")
            for spelling in spellings:
                body = body.replace(spelling + ":", name + ":")
            lines.append(body)
    return lines


def already_warned(event):
    """Remembers, once per session, that the classpath could not be assembled."""
    session = str(event.get("session_id") or "unknown")
    marker = os.path.join(CACHE_DIR, f"classpath-unavailable-{session}")
    if os.path.exists(marker):
        return True
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(marker, "w", encoding="utf-8") as handle:
        handle.write("")
    return False


def main():
    """Reads the Edit or Write event and reports checkstyle violations in the edited file."""
    event = read_event()
    path = edited_file(event)
    if not path or not path.endswith(".java") or not os.path.isfile(path):
        return 0
    root, pom_text = find_ixdar_root(path)
    if root is None:
        return 0
    try:
        classpath = resolve_classpath(pom_text)
        violations = violation_lines(run_checkstyle(classpath, path), path)
        methods = (
            new_method_violations(classpath, path)
            + public_single_caller_violations(root, path)
            + comment_violations(path)
            + duplicate_helper_violations(path)
        )
    except ClasspathUnavailable as error:
        if already_warned(event):
            return 0
        block(f"{UNAVAILABLE_ADVICE}\n\n({error})")
        return 0
    sections = []
    if violations:
        reported = "\n".join(f"  {line}" for line in violations)
        sections.append(
            f"checkstyle on {os.path.basename(path)} (ai-workspace hook, same configuration as the "
            f"Ixdar build):\n{reported}\nFix these now; the build fails on them."
        )
    if methods:
        reported = "\n".join(f"  {line}" for line in methods)
        sections.append(
            f"new code in {os.path.basename(path)} (edit-time only; the build does not check "
            f"these, but fix them now):\n{reported}"
        )
    if sections:
        block("\n\n".join(sections))
    return 0


if __name__ == "__main__":
    sys.exit(main())
