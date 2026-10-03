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
violations: SingleCallerHelperCheck (a private method with one caller should be inlined there)
and MethodVisibilityCheck (a method is public or private, never protected or package-private,
which is how a helper used to dodge the single-caller check). Here the pass is incremental: only a
method declared on a line the file's uncommitted diff adds is reported, so new code is caught when
it is written and old code stays quiet. There is no opt-out comment. The visibility rule applies
only under src/main/java, matching the build, which does not check test sources.
"""

import os
import re
import subprocess
import sys

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, HOOKS_DIR)
sys.path.insert(1, os.path.dirname(HOOKS_DIR))

from hook_common import block, read_event  # noqa: E402
from ixd.paths import repo_path  # noqa: E402

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

INCREMENTAL_CONFIGURATION_TEXT = """<?xml version="1.0"?>
<!DOCTYPE module PUBLIC "-//Checkstyle//DTD Checkstyle Configuration 1.3//EN"
    "https://checkstyle.org/dtds/configuration_1_3.dtd">
<module name="Checker">
  <module name="TreeWalker">
    <module name="ixdar.autofix.checkstyle.SingleCallerHelperCheck"/>
    <module name="ixdar.autofix.checkstyle.MethodVisibilityCheck"/>
  </module>
</module>
"""

VIOLATION_POSITION = re.compile(r"^[^:]+:(?P<line>\d+):")

METHOD_VISIBILITY_TAG = "[MethodVisibility]"

MAIN_SOURCE_SEGMENT = os.path.join("src", "main", "java") + os.sep

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
    "are not being checked at edit time. Build Ixdar once (mvn -q compile -pl "
    "annotations,ixdar-app) to populate ~/.m2, then edits will be checked again. Until then the "
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
    """Asks maven for a pom's runtime classpath, returning True when it wrote the file."""
    command = [
        "mvn",
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
    return finished.stdout + finished.stderr


def added_lines(path):
    """Returns the line numbers the file's uncommitted diff adds, or None when all of it is new.

    In an Ixdar worktree HEAD is the master tip, so this is exactly the proposed change.
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
            return None
        diff = subprocess.run(
            ["git", "-C", directory, "diff", "-U0", "HEAD", "--", path],
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    lines = set()
    for raw in diff.stdout.splitlines():
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
        if added is not None and int(position.group("line")) not in added:
            continue
        if not main_source and line.endswith(METHOD_VISIBILITY_TAG):
            continue
        reports.append(line)
    return reports


def violation_lines(output, path):
    """Extracts the reported violations, shortening the repeated absolute path."""
    lines = []
    for raw in output.splitlines():
        match = VIOLATION_LINE.match(raw.strip())
        if match:
            lines.append(match.group("body").replace(path + ":", os.path.basename(path) + ":"))
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
        methods = new_method_violations(classpath, path)
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
            f"new methods in {os.path.basename(path)} (edit-time only; the build does not check "
            f"these, but fix them now):\n{reported}"
        )
    if sections:
        block("\n\n".join(sections))
    return 0


if __name__ == "__main__":
    sys.exit(main())
