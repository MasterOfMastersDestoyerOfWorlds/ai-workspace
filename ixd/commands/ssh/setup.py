"""Key-based ssh onto a Windows peer, which Tailscale SSH cannot provide.

Tailscale SSH serves Linux and CLI-macOS peers only, and its browser console cannot be scripted, so
every command this workspace runs on a Windows box goes through OpenSSH. Nothing here can reach that
box before the first key is in place, so this generates the PowerShell that does the whole remote
side, hands it over by Taildrop, and leaves one command to run there. ``--encoded`` collapses even
that into a single paste when Taildrop is off.
"""

import base64
import subprocess
from pathlib import Path
from typing import Annotated

from ...registry import CliOption, cli_command

DEFAULT_KEY = Path.home() / ".ssh" / "id_ed25519"

CACHE = Path.home() / ".cache" / "ai-workspace"

TAILNET = "100.64.0.0/10"

SSH_OPTIONS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new"]


def reachable(target):
    """Whether key-based ssh onto the target works, and what the attempt said.

    :param target: the ssh destination, user@host or host
    """
    probe = subprocess.run(["ssh", *SSH_OPTIONS, target, "whoami"], capture_output=True, text=True)
    return probe.returncode == 0, (probe.stdout or probe.stderr).strip().splitlines()[-1:]


def public_key(key):
    """The public half of the key as one authorized_keys line, creating the pair when missing.

    :param key: the private key's path
    """
    public = Path(str(key) + ".pub")
    if not public.exists():
        if key.exists():
            raise SystemExit(f"{key} has no {public.name}; recover it with ssh-keygen -y -f {key}")
        key.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        print(f"  no key at {key}, creating one")
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-q", "-f", str(key)], check=True)
    return public.read_text(encoding="utf-8").strip()


def script(key_line):
    """The PowerShell that sets up the remote side, rerunnable without doubling anything up.

    It decides for itself where the key belongs: sshd ignores an administrator's own
    authorized_keys and reads administrators_authorized_keys instead, so the account's group
    membership picks the file, and the ACL that file demands is applied only in that case.

    :param key_line: this machine's public key, as one authorized_keys line
    """
    return f"""$ErrorActionPreference = 'Stop'
$key = '{key_line}'

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {{
  throw 'run this from an elevated PowerShell'
}}

if ((Get-WindowsCapability -Online -Name 'OpenSSH.Server*').State -ne 'Installed') {{
  Write-Host 'installing the OpenSSH server'
  Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null
}} else {{ Write-Host 'OpenSSH server already installed' }}

Set-Service -Name sshd -StartupType Automatic
if ((Get-Service sshd).Status -ne 'Running') {{ Start-Service sshd }}
Write-Host ('sshd is ' + (Get-Service sshd).Status)

$account = $env:USERNAME
$isAdmin = [bool](Get-LocalGroupMember -Group Administrators -ErrorAction SilentlyContinue |
  Where-Object {{ $_.Name -like "*\\$account" }})
if ($isAdmin) {{
  $authorized = Join-Path $env:ProgramData 'ssh\\administrators_authorized_keys'
}} else {{
  $authorized = Join-Path $env:USERPROFILE '.ssh\\authorized_keys'
  New-Item -ItemType Directory -Force (Split-Path $authorized) | Out-Null
}}

if ((Test-Path $authorized) -and (Select-String -Path $authorized -SimpleMatch $key -Quiet)) {{
  Write-Host "key already in $authorized"
}} else {{
  # -Encoding ascii because Windows PowerShell writes a BOM that sshd rejects without a word.
  Add-Content -Encoding ascii -Path $authorized -Value $key
  Write-Host "key added to $authorized"
}}
if ($isAdmin) {{
  icacls $authorized /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null
}}

$rule = Get-NetFirewallRule -Name OpenSSH-Server-In-TCP -ErrorAction SilentlyContinue
if ($rule) {{
  Set-NetFirewallRule -Name OpenSSH-Server-In-TCP -RemoteAddress {TAILNET}
}} else {{
  New-NetFirewallRule -Name OpenSSH-Server-In-TCP -DisplayName 'OpenSSH Server (tailnet)' `
    -Direction Inbound -Protocol TCP -LocalPort 22 -RemoteAddress {TAILNET} -Action Allow | Out-Null
}}
Write-Host 'port 22 is open to the tailnet only'
Write-Host "done: ssh in as $account"
"""


def deliver(path, host):
    """Push the script to the peer with Taildrop, saying whether it landed.

    :param path: the generated script
    :param host: the peer's tailnet name
    """
    sent = subprocess.run(["tailscale", "file", "cp", str(path), f"{host}:"], capture_output=True, text=True)
    return sent.returncode == 0, (sent.stderr or sent.stdout).strip()


@cli_command
def setup(
    host: Annotated[str, CliOption(positional=True)] = "blixt",
    user: str = "",
    key: str = "",
    out: str = "",
    encoded: bool = False,
    force: bool = False,
) -> int:
    """Generate the Windows-side OpenSSH setup as a script, send it to the peer, and test the result.

    Tries the connection first: when it already works there is nothing to generate. Otherwise this
    machine's public key is read (a missing ed25519 pair is created), a rerunnable PowerShell script
    is written with that key in it, and Taildrop carries it over. The script installs the server,
    authorises the key in whichever file that account's sshd actually reads, and narrows port 22 to
    the tailnet. Only running it stays manual, since nothing can reach the box until it has.

    :param host: the peer's tailnet name
    :param user: ssh user, when it differs from this machine's
    :param key: private key to authorise, when it is not the default ed25519 one
    :param out: where to write the script, instead of the cache directory
    :param encoded: print a one-line paste that carries the script instead of sending a file
    :param force: generate it even when the connection already works
    """
    target = f"{user}@{host}" if user else host
    works, said = reachable(target)
    if works:
        print(f"  ssh {target}: works, remote account {' '.join(said)}")
        if not force:
            return 0
    else:
        print(f"  ssh {target}: no route yet ({' '.join(said)})")
    body = script(public_key(Path(key) if key else DEFAULT_KEY))
    if encoded:
        paste = base64.b64encode(body.encode("utf-16-le")).decode()
        print(f"\nPaste this into an elevated PowerShell on {host}:\n")
        print(f"powershell -NoProfile -EncodedCommand {paste}")
        return 0 if works else 1
    path = Path(out) if out else CACHE / f"ssh-setup-{host}.ps1"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    print(f"  wrote {path}")
    landed, detail = deliver(path, host)
    print(f"  taildrop: {'sent' if landed else 'refused, copy it over yourself (' + detail + ')'}")
    where = "the file Taildrop saved" if landed else f"your copy of {path.name}"
    print(f"\nOn {host}, accept {where}, then run it from an elevated PowerShell:\n")
    print(f"  powershell -ExecutionPolicy Bypass -File $env:USERPROFILE\\Downloads\\{path.name}")
    print(f"\nThen prove it from here: ixd ssh setup {host}")
    return 0 if works else 1
