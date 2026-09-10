"""The steps `ixd setup` runs to prepare a machine.

  1. repositories  clone each entry of repos.json into REPO_HOME, skipping what is present
  2. commands      uv tool install --editable . for `ixd`, and uv sync for the hook environment
  3. REPO_HOME     .claude/settings.local.json for Claude sessions and hooks, and the shell profile
                   (bash, zsh, fish) or the user environment on Windows
  4. autofix       mvn install of the checkstyle artifact Ixdar's build and the edit hook need

Every step is idempotent, so rerunning after a partial failure is safe. Works on Linux, macOS and
Windows.
"""

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

from .paths import MANIFEST, REPO_HOME_VARIABLE, WORKSPACE_ROOT, repo_home

LOCAL_SETTINGS = WORKSPACE_ROOT / ".claude" / "settings.local.json"

AUTOFIX_ARTIFACT = Path.home() / ".m2" / "repository" / "IXDAR" / "autofix-tool"

SHELL_PROFILES = {"zsh": ".zshenv", "bash": ".bashrc", "sh": ".profile"}


def load_manifest(path=MANIFEST):
    """The repositories to clone: name -> {url, branch}."""
    with open(path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    for name, entry in manifest.items():
        if not isinstance(entry, dict) or not entry.get("url"):
            raise SystemExit(f"{path}: entry {name!r} needs a url")
        entry.setdefault("branch", "main")
    return manifest


def run(command, cwd=None, dry_run=False):
    """Runs one command, echoing it first; a failure ends setup with the command's output."""
    print("  $ " + " ".join(str(part) for part in command))
    if dry_run:
        return
    result = subprocess.run([str(part) for part in command], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"failed ({result.returncode}):\n{(result.stderr or result.stdout).strip()[-3000:]}")


def remote_url(checkout):
    """The origin url of a checkout, read from its config so no git command is needed."""
    config = checkout / ".git" / "config"
    if not config.is_file():
        return ""
    url = ""
    in_origin = False
    for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_origin = stripped == '[remote "origin"]'
        elif in_origin and stripped.startswith("url"):
            url = stripped.split("=", 1)[1].strip()
    return url


def same_repository(left, right):
    """Two remote urls name the same repository when they agree ignoring scheme and .git."""

    def key(url):
        rest = url.lower().rstrip("/").removesuffix(".git").split("://", 1)[-1]
        return rest.split("@", 1)[-1].replace(":", "/", 1)

    return bool(left) and key(left) == key(right)


def clone_repositories(home, manifest, dry_run):
    """Clones every manifest entry that has no checkout under home."""
    print(f"== repositories under {home}")
    for name, entry in manifest.items():
        target = home / name
        if (target / ".git").exists():
            print(f"  {name}: present")
            continue
        elsewhere = Path.home() / name
        if elsewhere != target and same_repository(remote_url(elsewhere), entry["url"]):
            print(
                f"  {name}: already cloned at {elsewhere}; move or symlink it to {target} (not cloning twice)"
            )
            continue
        run(["git", "clone", "--branch", entry["branch"], entry["url"], target], dry_run=dry_run)


def install_tools(dry_run):
    """Install `ixd` on PATH and create the environment the hooks run in.

    :param dry_run: print the commands without running them
    """
    print("== tools")
    if shutil.which("uv") is None:
        print("  uv is not installed; get it from https://docs.astral.sh/uv/ and rerun")
        return
    run(["uv", "tool", "install", "--editable", "--reinstall", WORKSPACE_ROOT], dry_run=dry_run)
    run(["uv", "sync", "--project", WORKSPACE_ROOT], dry_run=dry_run)


def write_local_settings(home, dry_run, path=LOCAL_SETTINGS):
    """Records REPO_HOME in .claude/settings.local.json, keeping whatever else is there."""
    settings = {}
    if path.is_file():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            raise SystemExit(f"{path} is not valid JSON; fix or remove it") from None
    env = settings.setdefault("env", {})
    if env.get(REPO_HOME_VARIABLE) == str(home):
        print(f"  {path.name}: {REPO_HOME_VARIABLE} already {home}")
        return
    env[REPO_HOME_VARIABLE] = str(home)
    print(f"  {path.name}: env.{REPO_HOME_VARIABLE} = {home}")
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def profile_line(home):
    return f'export {REPO_HOME_VARIABLE}="{home}"'


def update_profile(path, home, dry_run):
    """Adds or replaces the export line in a POSIX shell profile, leaving other lines alone."""
    wanted = profile_line(home)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    kept = [line for line in lines if not line.startswith(f"export {REPO_HOME_VARIABLE}=")]
    if wanted in lines and len(kept) == len(lines) - 1:
        print(f"  {path}: already exports {REPO_HOME_VARIABLE}")
        return
    print(f"  {path}: {wanted}")
    if not dry_run:
        path.write_text("\n".join(kept + [wanted]) + "\n", encoding="utf-8")


def configure_shell(home, dry_run):
    """Makes REPO_HOME visible to new terminals, so wt and land see the same value as Claude."""
    if platform.system() == "Windows":
        run(["setx", REPO_HOME_VARIABLE, str(home)], dry_run=dry_run)
        return
    shell = os.path.basename(os.environ.get("SHELL", "bash"))
    if shell == "fish":
        run(["fish", "-c", f"set -Ux {REPO_HOME_VARIABLE} '{home}'"], dry_run=dry_run)
        return
    update_profile(Path.home() / SHELL_PROFILES.get(shell, ".profile"), home, dry_run)


def install_autofix(home, dry_run):
    """Builds the checkstyle artifact into ~/.m2 once, so Ixdar compiles and the edit hook runs."""
    print("== autofix artifact")
    autofix = home / "autofix"
    if not (autofix / "pom.xml").is_file():
        print("  no autofix checkout; skipped")
        return
    if AUTOFIX_ARTIFACT.is_dir():
        print(f"  installed in {AUTOFIX_ARTIFACT}")
        return
    if shutil.which("mvn") is None:
        print("  mvn is not on PATH; run `mvn -q install -DskipTests` in autofix once it is")
        return
    run(["mvn", "-q", "install", "-DskipTests"], cwd=autofix, dry_run=dry_run)


def prepare(given_home="", dry_run=False, no_shell=False, no_tools=False, no_maven=False):
    """Prepare this machine, running the steps in the module docstring.

    :param given_home: where the repositories should live, or empty for the default
    :param dry_run: print every step without running it
    :param no_shell: leave the shell profile and the user environment alone
    :param no_tools: skip installing the commands and syncing the environment
    :param no_maven: skip installing the autofix artifact
    :return: the exit code, always zero when nothing raised
    """
    home = Path(os.path.expanduser(given_home)).resolve() if given_home else repo_home()
    print(f"{REPO_HOME_VARIABLE} = {home}" + (" (dry run)" if dry_run else ""))
    if not dry_run:
        home.mkdir(parents=True, exist_ok=True)
    clone_repositories(home, load_manifest(), dry_run)
    if not no_tools:
        install_tools(dry_run)
    print(f"== {REPO_HOME_VARIABLE}")
    write_local_settings(home, dry_run)
    if not no_shell:
        configure_shell(home, dry_run)
    if not no_maven:
        install_autofix(home, dry_run)
    print("done; open a new terminal so the shell picks up " + REPO_HOME_VARIABLE)
    return 0
