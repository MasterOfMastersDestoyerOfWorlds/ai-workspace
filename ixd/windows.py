"""Running this repo's PowerShell on a Windows peer over the tailnet.

The scripts themselves are the files in ``ixd/scripts``, edited and read as PowerShell rather than
quoted inside Python. Everything here only carries one of them to the other box: wrapped in a call
that supplies its ``param`` block, either as a file Taildrop delivers or as one ``-EncodedCommand``
line ssh runs. The bytes that run there are the same either way, so a script has one implementation
and one place to fix.
"""

import base64
import gzip
import shlex
import subprocess
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent / "scripts"

TAILNET = "100.64.0.0/10"

DISTRO = "Ubuntu"

SSH_OPTIONS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new"]


def quote(value):
    """One value as a PowerShell single-quoted literal, where only the quote itself escapes.

    :param value: the value to quote
    """
    return "'" + str(value).replace("'", "''") + "'"


def payload(name, arguments):
    """One script wrapped so that running the text calls it with these arguments.

    The script keeps its ``param`` block, which a bare body could not: a call operator on a script
    block takes named arguments the same way the file would from a command line.

    :param name: the script's file name in ixd/scripts
    :param arguments: the parameters to pass, name to value
    """
    body = (SCRIPTS / name).read_text(encoding="utf-8")
    passed = " ".join(f"-{parameter} {quote(value)}" for parameter, value in arguments.items())
    return f"& {{\n{body}\n}} {passed}\n"


def encoded(text):
    """PowerShell's -EncodedCommand form of a payload, which survives any shell it passes through.

    The payload travels gzipped, behind a stub that unpacks and runs it. Plain encoding is what
    the length limits bite: UTF-16 doubles the script and base64 adds a third again, which passes
    8191 characters -- the most cmd.exe will carry, and about what a console will accept as one
    pasted line -- while the scripts here are still small. Compressed, the same script goes over at
    roughly a third of its own size.

    :param text: the payload to encode
    """
    packed = base64.b64encode(gzip.compress(text.encode("utf-8"))).decode()
    stub = (
        f"$bytes=[Convert]::FromBase64String('{packed}');"
        "$stream=New-Object IO.Compression.GzipStream("
        "(New-Object IO.MemoryStream(,$bytes)),[IO.Compression.CompressionMode]::Decompress);"
        "Invoke-Expression (New-Object IO.StreamReader($stream)).ReadToEnd()"
    )
    return base64.b64encode(stub.encode("utf-16-le")).decode()


def run(target, name, arguments):
    """Run one PowerShell script on the peer over ssh, as a completed process.

    :param target: the ssh destination, user@host or host
    :param name: the script's file name in ixd/scripts
    :param arguments: the parameters to pass, name to value
    """
    command = ["powershell", "-NoProfile", "-EncodedCommand", encoded(payload(name, arguments))]
    return subprocess.run(["ssh", *SSH_OPTIONS, target, *command], capture_output=True, text=True)


def wsl(target, name, environment=None, distro=DISTRO):
    """Run one shell script inside the peer's WSL distro over ssh, as a completed process.

    The script arrives on stdin rather than as arguments. A command for WSL otherwise crosses this
    machine's shell, ssh, cmd.exe and wsl.exe before bash sees it, and each one takes its own bite
    out of the quoting; stdin crosses all of them untouched. Values ride above it as exports.

    :param target: the ssh destination, user@host or host
    :param name: the script's file name in ixd/scripts
    :param environment: variables to set for the script, name to value
    :param distro: the WSL distro holding the build
    """
    exports = "".join(f"export {n}={shlex.quote(str(v))}\n" for n, v in (environment or {}).items())
    body = exports + (SCRIPTS / name).read_text(encoding="utf-8")
    command = ["ssh", *SSH_OPTIONS, target, "wsl", "-d", distro, "-e", "bash", "-s"]
    return subprocess.run(command, input=body, capture_output=True, text=True)


def reachable(target):
    """Whether key-based ssh onto the target works, and what the attempt said.

    :param target: the ssh destination, user@host or host
    """
    probe = subprocess.run(["ssh", *SSH_OPTIONS, target, "whoami"], capture_output=True, text=True)
    return probe.returncode == 0, (probe.stdout or probe.stderr).strip().splitlines()[-1:]


def taildrop(path, host):
    """Push a file to the peer with Taildrop, saying whether it landed.

    :param path: the file to send
    :param host: the peer's tailnet name
    """
    sent = subprocess.run(["tailscale", "file", "cp", str(path), f"{host}:"], capture_output=True, text=True)
    return sent.returncode == 0, (sent.stderr or sent.stdout).strip()
