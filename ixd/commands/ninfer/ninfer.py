"""Bring the ninfer server on the Windows box up over the tailnet and point pi at it.

ninfer holds exactly one model resident: it loads at process start, and the runtime has no lazy
load, no idle unload and no model swapping. The GPU stays occupied for as long as the server runs,
so nothing on the Windows box starts at boot. This command is the trigger instead: it starts the
server when a model is wanted, waits for the weights to materialise, and ``--stop`` hands the card
back. ``--install`` does the one-time Windows setup over ssh, once `ixd ssh setup` has opened that
door; it expects ninfer-serve.exe and a model file to be on the box already.
"""

import base64
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from ...registry import cli_command
from ..ssh.setup import SSH_OPTIONS, TAILNET

MODELS_FILE = Path.home() / ".pi" / "agent" / "models.json"

PROVIDER = "ninfer"

DEFAULT_FLAGS = "--max-context 32768 --kv-capacity auto --max-concurrency 2"


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


def task_command(target, verb, task):
    """Run one schtasks verb against the remote task over ssh.

    :param target: the ssh destination, user@host or host
    :param verb: the schtasks switch, /run or /end
    :param task: the scheduled task's name
    """
    return subprocess.run(
        ["ssh", *SSH_OPTIONS, target, "schtasks", verb, "/tn", task],
        capture_output=True,
        text=True,
    )


def install_script(task, port, model, flags):
    """The PowerShell that sets the Windows box up, rerunnable without doubling anything up.

    The launcher is a batch file the box owns, so the model path and the flags that suit that card
    stay there rather than in this repo. The task exists because a process started straight from an
    ssh command dies with the session; a scheduled task outlives it.

    :param task: the scheduled task's name to create
    :param port: the port the server should listen on
    :param model: the model file's path on the Windows box
    :param flags: the ninfer-serve flags that suit that card
    """
    return f"""$ErrorActionPreference = 'Stop'
$root = Join-Path $env:USERPROFILE 'ninfer'
$exe = Join-Path $root 'ninfer-serve.exe'
$model = '{model}'
if (-not (Test-Path $exe)) {{ throw "no ninfer-serve.exe at $exe" }}
if (-not (Test-Path $model)) {{ throw "no model at $model" }}

$launcher = Join-Path $root 'start-ninfer.bat'
# --host past loopback, or nothing off this box can reach it.
$lines = @('@echo off', '"' + $exe + '" "' + $model + '" --host 0.0.0.0 --port {port} {flags}')
Set-Content -Encoding ascii -Path $launcher -Value $lines
Write-Host "launcher: $launcher"

# Register-ScheduledTask rather than schtasks.exe: passing a quoted path through /tr loses its
# quotes to PowerShell's native-argument handling, and %USERPROFILE% may hold a space.
# Interactive, so it runs in the logged-on session where the GPU is uncontested. No trigger:
# nothing at boot, because ninfer holds its model resident and would hold the card with it.
$action = New-ScheduledTaskAction -Execute $launcher
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\\$env:USERNAME" -LogonType Interactive
Register-ScheduledTask -TaskName '{task}' -Action $action -Principal $principal -Force | Out-Null
Write-Host 'task: {task}'

$rule = Get-NetFirewallRule -DisplayName 'ninfer (tailnet)' -ErrorAction SilentlyContinue
if (-not $rule) {{
  New-NetFirewallRule -DisplayName 'ninfer (tailnet)' -Direction Inbound -Protocol TCP `
    -LocalPort {port} -RemoteAddress {TAILNET} -Action Allow | Out-Null
}} else {{
  Set-NetFirewallRule -DisplayName 'ninfer (tailnet)' -LocalPort {port} -RemoteAddress {TAILNET}
}}
Write-Host 'port {port} is open to the tailnet only'
"""


def install(target, task, port, model, flags):
    """Run the setup script on the Windows box over ssh.

    :param target: the ssh destination, user@host or host
    :param task: the scheduled task's name to create
    :param port: the port the server should listen on
    :param model: the model file's path on the Windows box
    :param flags: the ninfer-serve flags that suit that card
    """
    paste = base64.b64encode(install_script(task, port, model, flags).encode("utf-16-le")).decode()
    return subprocess.run(
        ["ssh", *SSH_OPTIONS, target, "powershell", "-NoProfile", "-EncodedCommand", paste],
        capture_output=True,
        text=True,
    )


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
        # ninfer is not OpenAI: it has no developer role and no reasoning_effort knob.
        "compat": {"supportsDeveloperRole": False, "supportsReasoningEffort": False},
        "models": [{"id": model_id} for model_id in model_ids],
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
    task: str = "ninfer",
    wait: int = 240,
    stop: bool = False,
    check: bool = False,
    setup: bool = False,
    model: str = "",
    flags: str = DEFAULT_FLAGS,
) -> int:
    """Start ninfer on the Windows box over the tailnet and make sure pi's models.json points at it.

    Checks the tailnet, starts the remote scheduled task when the server is not already answering,
    waits for the model to load, then writes the provider into pi's models.json if it is missing or
    stale. Safe to rerun: a server that is already up is left alone. ``--setup --model <path>`` does
    the one-time remote half first, over the ssh `ixd ssh setup` opened.

    :param host: the Windows box's tailnet name
    :param port: the port ninfer-serve listens on
    :param user: ssh user, when it differs from this machine's
    :param task: the scheduled task's name on the Windows box
    :param wait: seconds to wait for the weights to load before giving up
    :param stop: end the remote task instead, giving the GPU back
    :param check: report the state without starting anything
    :param setup: write the launcher, register the task and open the port on the Windows box first
    :param model: the model file's path on the Windows box, which --setup needs
    :param flags: the ninfer-serve flags --setup writes into the launcher
    """
    base_url = f"http://{host}:{port}/v1"
    target = f"{user}@{host}" if user else host
    tailnet_ready(host)
    if setup:
        if not model:
            raise SystemExit("--setup needs --model, the model file's path on the Windows box")
        written = install(target, task, port, model, flags)
        print((written.stdout or "").strip())
        if written.returncode != 0:
            raise SystemExit("the remote setup failed:\n" + (written.stderr or written.stdout).strip())
    if stop:
        ended = task_command(target, "/end", task)
        if ended.returncode != 0:
            raise SystemExit("could not end the task:\n" + (ended.stderr or ended.stdout).strip())
        print(f"  stopped: {task} on {host}, the card is free")
        return 0
    ids = advertised(base_url)
    if ids is None and check:
        print(f"  ninfer: down at {base_url}")
        return 1
    if ids is None:
        print(f"  ninfer: down at {base_url}, running the {task} task on {host}")
        started = task_command(target, "/run", task)
        if started.returncode != 0:
            raise SystemExit(
                "could not start the task:\n"
                + (started.stderr or started.stdout).strip()
                + f"\n\nthe box may not be set up yet: ixd ssh setup {host}, then"
                + f" ixd ninfer --setup --model <path on {host}>"
            )
        ids = wait_for(base_url, wait)
        if ids is None:
            raise SystemExit(f"the task started but nothing answered {base_url} within {wait}s")
    print(f"  ninfer: up at {base_url}, serving {', '.join(ids)}")
    if check:
        linked = (
            MODELS_FILE.exists()
            and json.loads(MODELS_FILE.read_text(encoding="utf-8") or "{}")
            .get("providers", {})
            .get(PROVIDER, {})
            .get("baseUrl")
            == base_url
        )
        print(f"  pi: {'linked' if linked else 'not linked'} ({MODELS_FILE})")
        return 0
    if link(base_url, ids):
        print(f"  pi: wrote the {PROVIDER} provider to {MODELS_FILE}")
    else:
        print(f"  pi: already linked in {MODELS_FILE}")
    print(f"  pick it in pi with /model, or start with --model {PROVIDER}/{ids[0]}")
    return 0
