"""Bring the ninfer server on the Windows box up over the tailnet and point pi at it.

The server is a source build inside that box's WSL distro, not a Windows binary, so starting it
means reaching through ssh into WSL. Two things follow from that and both are done on every start:
it binds 0.0.0.0 rather than WSL's own loopback, and Windows forwards the port inward, because WSL2
is NAT'd there and the distro takes a new address each time it comes up.

ninfer holds exactly one model resident: it loads at process start, and the runtime has no lazy
load, no idle unload and no model swapping. The GPU stays occupied for as long as the server runs,
so nothing starts at boot. This command is the trigger instead, and ``--stop`` hands the card back.
"""

import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from ... import windows
from ...registry import cli_command

MODELS_FILE = Path.home() / ".pi" / "agent" / "models.json"

PROVIDER = "ninfer"

START = "ninfer-start.sh"

STOP = "ninfer-stop.sh"

FORWARD = "ninfer-forward.ps1"


def tailnet_ready(host):
    """Bring the tailnet up if it is down and confirm the host answers on it.

    :param host: the peer's tailnet name
    """
    status = subprocess.run(["tailscale", "status"], capture_output=True, text=True)
    if status.returncode != 0:
        print("  tailscale is down, bringing it up")
        started = subprocess.run(["tailscale", "up"], capture_output=True, text=True)
        if started.returncode != 0:
            raise SystemExit("tailscale up failed (try sudo):\n" + (started.stderr or started.stdout).strip())
    ping = subprocess.run(["tailscale", "ping", "-c", "1", host], capture_output=True, text=True)
    if ping.returncode != 0:
        raise SystemExit(f"{host} is not answering on the tailnet:\n" + (ping.stdout or ping.stderr).strip())
    print(f"  tailnet: {ping.stdout.strip().splitlines()[0]}")


def advertised(base_url, timeout=5):
    """The model ids the server advertises, or None when it is not answering.

    :param base_url: the server's OpenAI-compatible root, ending in /v1
    :param timeout: seconds to wait for the response
    """
    try:
        with urllib.request.urlopen(base_url + "/models", timeout=timeout) as response:
            payload = json.load(response)
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return [entry["id"] for entry in payload.get("data", []) if entry.get("id")]


def start(target, port, root, model, flags):
    """Start the server inside WSL, returning its output and the distro's address.

    :param target: the ssh destination, user@host or host
    :param port: the port the server should listen on
    :param root: the ninfer checkout inside WSL, or empty for the script's own
    :param model: the model file's path under that checkout, or empty for the script's own
    :param flags: the ninfer-serve flags, or empty for the script's own
    """
    environment = {"NINFER_PORT": port}
    for name, value in (("NINFER_ROOT", root), ("NINFER_MODEL", model), ("NINFER_FLAGS", flags)):
        if value:
            environment[name] = value
    started = windows.wsl(target, START, environment)
    if started.returncode != 0:
        raise SystemExit("could not start the server in WSL:\n" + (started.stderr or started.stdout).strip())
    lines = [line.strip() for line in started.stdout.splitlines() if line.strip()]
    address = next((line.split()[1] for line in lines if line.startswith("wsl-address ")), "")
    for line in lines:
        if not line.startswith("wsl-address "):
            print(f"  wsl: {line}")
    if not address:
        raise SystemExit("the WSL distro reported no address to forward to:\n" + started.stdout.strip())
    return address


def forward(target, port, address):
    """Point the Windows port proxy at the distro's current address and open the port.

    :param target: the ssh destination, user@host or host
    :param port: the port to forward
    :param address: the distro's address
    """
    done = windows.run(target, FORWARD, {"WslAddress": address, "Port": port})
    if done.returncode != 0:
        raise SystemExit("could not forward the port:\n" + (done.stderr or done.stdout).strip())
    for line in done.stdout.strip().splitlines():
        print(f"  windows: {line.strip()}")


def wait_for(base_url, seconds):
    """Poll the server until it advertises a model or the wait runs out.

    :param base_url: the server's OpenAI-compatible root
    :param seconds: how long to keep polling
    """
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        ids = advertised(base_url, timeout=3)
        if ids:
            return ids
        time.sleep(3)
    return None


def link(base_url, model_ids):
    """Point pi's models.json at the server, returning whether the file changed.

    :param base_url: the server's OpenAI-compatible root
    :param model_ids: the ids the server advertises
    """
    config = {}
    if MODELS_FILE.exists():
        config = json.loads(MODELS_FILE.read_text(encoding="utf-8") or "{}")
    wanted = {
        "baseUrl": base_url,
        "api": "openai-completions",
        "apiKey": PROVIDER,
        # ninfer is not OpenAI: it has no developer role and no reasoning_effort knob. It does think,
        # and answers with a reasoning_content of its own, which pi reads once the model says so.
        "compat": {"supportsDeveloperRole": False, "supportsReasoningEffort": False},
        "models": [{"id": model_id, "reasoning": True} for model_id in model_ids],
    }
    providers = config.setdefault("providers", {})
    if providers.get(PROVIDER) == wanted:
        return False
    providers[PROVIDER] = wanted
    MODELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    MODELS_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return True


@cli_command
def ninfer(
    host: str = "blixt",
    port: int = 8080,
    user: str = "",
    wait: int = 240,
    root: str = "",
    model: str = "",
    flags: str = "",
    stop: bool = False,
    check: bool = False,
) -> int:
    """Start ninfer in the Windows box's WSL distro and make sure pi's models.json points at it.

    Checks the tailnet, starts the server when it is not already answering, refreshes the Windows
    port proxy onto the distro's current address, waits for the weights to load, then writes the
    provider into pi's models.json if it is missing or stale. Safe to rerun: a server that is
    already up is left alone, and the proxy is repointed either way.

    :param host: the Windows box's tailnet name
    :param port: the port ninfer-serve listens on
    :param user: ssh user, when it differs from this machine's
    :param wait: seconds to wait for the weights to load before giving up
    :param root: the ninfer checkout inside WSL, instead of the one ninfer-start.sh holds
    :param model: the model file under that checkout, instead of the one ninfer-start.sh holds
    :param flags: ninfer-serve flags, instead of the ones ninfer-start.sh holds
    :param stop: stop the server instead, giving the GPU back
    :param check: report the state without starting anything
    """
    base_url = f"http://{host}:{port}/v1"
    target = f"{user}@{host}" if user else host
    tailnet_ready(host)
    if stop:
        stopped = windows.wsl(target, STOP, {"NINFER_PORT": port})
        if stopped.returncode != 0:
            raise SystemExit("could not stop the server:\n" + (stopped.stderr or stopped.stdout).strip())
        print(f"  {stopped.stdout.strip() or 'stopped'}, the card is free")
        return 0
    ids = advertised(base_url)
    if check:
        print(f"  ninfer: {'up at ' + base_url if ids else 'down at ' + base_url}")
        if ids:
            print(f"  serving {', '.join(ids)}")
        return 0 if ids else 1
    if ids is None:
        print(f"  ninfer: nothing answering {base_url}, starting it in WSL")
        forward(target, port, start(target, port, root, model, flags))
        ids = wait_for(base_url, wait)
        if ids is None:
            raise SystemExit(
                f"the server started but nothing answered {base_url} within {wait}s;"
                f" its log is /tmp/ninfer.log inside WSL on {host}"
            )
    print(f"  ninfer: up at {base_url}, serving {', '.join(ids)}")
    if link(base_url, ids):
        print(f"  pi: wrote the {PROVIDER} provider to {MODELS_FILE}")
    else:
        print(f"  pi: already linked in {MODELS_FILE}")
    print(f"  pick it in pi with /model, or start with --model {PROVIDER}/{ids[0]}")
    return 0
