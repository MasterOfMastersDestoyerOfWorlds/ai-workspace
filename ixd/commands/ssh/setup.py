"""Key-based ssh onto a Windows peer, which Tailscale SSH cannot provide.

Tailscale SSH serves Linux and CLI-macOS peers only, and its browser console cannot be scripted, so
every command this workspace runs on a Windows box goes through OpenSSH. Nothing here can reach that
box before the first key is in place, which makes this the one setup that cannot run itself: it
hands ``ixd/scripts/ssh-setup.ps1`` over by Taildrop and leaves one command to run there.
``--encoded`` collapses even that into a single paste when Taildrop is off.
"""

import hashlib
import subprocess
from pathlib import Path
from typing import Annotated

from ... import windows
from ...registry import CliOption, cli_command

DEFAULT_KEY = Path.home() / ".ssh" / "id_ed25519"

CACHE = Path.home() / ".cache" / "ai-workspace"

SCRIPT = "ssh-setup.ps1"


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


@cli_command
def setup(
    host: Annotated[str, CliOption(positional=True)] = "blixt",
    user: str = "",
    key: str = "",
    out: str = "",
    encoded: bool = False,
    force: bool = False,
) -> int:
    """Send the Windows-side OpenSSH setup script to a peer, keyed to this machine, and test it.

    Tries the connection first: when it already works there is nothing to send. Otherwise this
    machine's public key is read (a missing ed25519 pair is created), ssh-setup.ps1 is written out
    with a call that passes it that key, and Taildrop carries it over. The script installs the
    server, authorises the key in whichever file that account's sshd actually reads, and narrows
    port 22 to the tailnet. Only running it stays manual, since nothing can reach the box until it
    has.

    :param host: the peer's tailnet name
    :param user: ssh user, when it differs from this machine's
    :param key: private key to authorise, when it is not the default ed25519 one
    :param out: where to write the script, instead of the cache directory
    :param encoded: print a one-line paste that carries the script instead of sending a file
    :param force: send it even when the connection already works
    """
    target = f"{user}@{host}" if user else host
    works, said = windows.reachable(target)
    if works:
        print(f"  ssh {target}: works, remote account {' '.join(said)}")
        if not force:
            return 0
    else:
        print(f"  ssh {target}: no route yet ({' '.join(said)})")
    body = windows.payload(SCRIPT, {"Key": public_key(Path(key) if key else DEFAULT_KEY)})
    if encoded:
        print(f"\nPaste this into an elevated PowerShell on {host}:\n")
        print(f"powershell -NoProfile -EncodedCommand {windows.encoded(body)}")
        return 0 if works else 1
    # The name carries a digest of the script. A fixed name is the trap here: Windows keeps the
    # file that is already in Downloads and saves the new one as "… (1)", so the name this prints
    # would run the oldest copy, and every later fix would land in a file nobody runs. A changed
    # script now arrives under a name nothing else holds, and an unchanged one reuses its own.
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:8]
    path = Path(out) if out else CACHE / f"ssh-setup-{host}-{digest}.ps1"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    stale = [old for old in path.parent.glob(f"ssh-setup-{host}-*.ps1") if old != path]
    for old in stale:
        old.unlink()
    print(f"  wrote {path}" + (f" (dropped {len(stale)} older)" if stale else ""))
    landed, detail = windows.taildrop(path, host)
    print(f"  taildrop: {'sent' if landed else 'refused, copy it over yourself (' + detail + ')'}")
    where = "the file Taildrop saved" if landed else f"your copy of {path.name}"
    print(f"\nOn {host}, accept {where}, then run it from an elevated PowerShell:\n")
    print(f"  powershell -ExecutionPolicy Bypass -File $env:USERPROFILE\\Downloads\\{path.name}")
    print(f"\nThat name is this script's digest: if Windows saved it as '{path.stem} (1).ps1' you")
    print("already have this exact script, and the older ssh-setup files are safe to delete.")
    print(f"\nThen prove it from here: ixd ssh setup {host}")
    return 0 if works else 1
