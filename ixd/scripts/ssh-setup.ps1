param(
  [Parameter(Mandatory)][string]$Key,
  [string]$Tailnet = '100.64.0.0/10'
)

# Sets up key-based ssh onto this Windows box: the server, the key, and port 22 on the tailnet only.
# Rerunnable; every step checks before it acts. `ixd ssh setup` sends this over and reads it back.

$ErrorActionPreference = 'Stop'

# Microsoft's own Win32-OpenSSH build, for boxes whose Features-on-Demand servicing is wedged.
$wingetServer = 'Microsoft.OpenSSH.Preview'

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw 'run this from an elevated PowerShell'
}

# The key goes in both files rather than in whichever one this account needs, because working that
# out is the step that breaks: sshd's stock config ends in a `Match Group administrators` block
# that reads administrators_authorized_keys and ignores an admin's own authorized_keys, while
# Get-LocalGroupMember throws on any group member whose SID no longer resolves and hands back
# nothing, which reads exactly like a non-admin account. Both files together need no guess. This
# runs before the server is installed, so a failure further down still leaves the key authorised.
$account = $env:USERNAME
$shared = Join-Path $env:ProgramData 'ssh\administrators_authorized_keys'
$own = Join-Path $env:USERPROFILE '.ssh\authorized_keys'
foreach ($authorized in @($shared, $own)) {
  New-Item -ItemType Directory -Force (Split-Path $authorized) | Out-Null
  # Rewritten every time rather than appended to when the key looks absent. A file some other tool
  # wrote as UTF-16, or with a BOM on its first line, still holds the key as text that any search
  # finds, while sshd cannot read a line of it -- and "key already there" is then the one report
  # that stops this from fixing it. -Encoding ascii is the only spelling sshd reads back.
  $lines = @()
  if (Test-Path $authorized) {
    $lines = @(Get-Content -Path $authorized |
      ForEach-Object { $_.Trim([char]0xFEFF).Trim() } |
      Where-Object { $_ -and $_ -ne $Key })
  }
  Set-Content -Encoding ascii -Path $authorized -Value ($lines + $Key)
  Write-Host "key authorised in $authorized"
}

# sshd refuses administrators_authorized_keys outright unless SYSTEM or the Administrators group
# owns it: an admin account that creates the file owns it as itself, which is refused as surely as
# a bad ACL, and the refusal is only ever visible in sshd's log.
icacls $shared /setowner 'BUILTIN\Administrators' | Out-Null
icacls $shared /inheritance:r /grant 'BUILTIN\Administrators:F' /grant 'NT AUTHORITY\SYSTEM:F' | Out-Null
Write-Host ('owner of ' + $shared + ': ' + (Get-Acl $shared).Owner)

$capability = Get-WindowsCapability -Online -Name 'OpenSSH.Server*' |
  Sort-Object Name -Descending | Select-Object -First 1
if ($capability -and $capability.State -ne 'Installed') {
  Write-Host ('installing ' + $capability.Name)
  # The result carries RestartNeeded: swallowing it leaves a staged install looking like a done one.
  $added = Add-WindowsCapability -Online -Name $capability.Name
  if ($added.RestartNeeded) { Write-Host 'Windows wants a restart to finish that' }
} elseif ($capability) { Write-Host 'OpenSSH server already installed' }

# The capability can read Installed while its services are still unregistered; the server ships the
# installer that registers them, and without it Set-Service says only "service sshd was not found".
if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) {
  $installer = Join-Path $env:SystemRoot 'System32\OpenSSH\install-sshd.ps1'
  if (Test-Path $installer) {
    Write-Host 'registering the sshd service'
    & $installer
  }
}

# Wedged servicing parks the capability at InstallPending through any number of reboots, so fall
# back to the same server as Microsoft's standalone MSI, which installs without going through CBS.
if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) {
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw ('the OpenSSH.Server capability produced no sshd service and winget is not here to ' +
      'install the MSI instead; take it from https://github.com/PowerShell/Win32-OpenSSH/releases')
  }
  Write-Host 'the Windows capability produced no sshd service; installing the OpenSSH MSI instead'
  winget install --id $wingetServer --exact --source winget --accept-source-agreements `
    --accept-package-agreements --disable-interactivity
  $env:PATH = [Environment]::GetEnvironmentVariable('PATH', 'Machine')
}
if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) {
  $state = if ($capability) { $capability.State } else { 'absent' }
  throw ("still no sshd service (OpenSSH.Server capability: $state); install the server by hand " +
    'from https://github.com/PowerShell/Win32-OpenSSH/releases, then run this again')
}

Set-Service -Name sshd -StartupType Automatic
if ((Get-Service sshd).Status -ne 'Running') { Start-Service sshd }
Write-Host ('sshd is ' + (Get-Service sshd).Status)

$rule = Get-NetFirewallRule -Name OpenSSH-Server-In-TCP -ErrorAction SilentlyContinue
if ($rule) {
  Set-NetFirewallRule -Name OpenSSH-Server-In-TCP -RemoteAddress $Tailnet
} else {
  New-NetFirewallRule -Name OpenSSH-Server-In-TCP -DisplayName 'OpenSSH Server (tailnet)' `
    -Direction Inbound -Protocol TCP -LocalPort 22 -RemoteAddress $Tailnet -Action Allow | Out-Null
}
Write-Host 'port 22 is open to the tailnet only'

# The lines that decide which key file sshd reads, so a refusal after all this has evidence to read
# rather than a guess to make.
$config = Join-Path $env:ProgramData 'ssh\sshd_config'
if (Test-Path $config) {
  Write-Host 'sshd_config, the lines that pick the key file:'
  Select-String -Path $config -Pattern 'AuthorizedKeysFile|Match Group|PubkeyAuthentication' |
    ForEach-Object { Write-Host ('  ' + $_.Line.Trim()) }
}

# sshd says why it turned a key down, and says it nowhere else. Restarting first means the lines
# below are about the config and permissions this run just set.
Restart-Service sshd
$since = (Get-Date).AddMinutes(-30)
$events = Get-WinEvent -FilterHashtable @{ LogName = 'OpenSSH/Operational'; StartTime = $since } `
  -ErrorAction SilentlyContinue
if ($events) {
  Write-Host 'sshd log, the last half hour:'
  $events | Select-Object -First 15 |
    ForEach-Object { Write-Host ('  ' + ($_.Message -split "`r?`n")[0]) }
} else {
  Write-Host 'sshd log: nothing in OpenSSH/Operational yet; try the connection, then rerun this'
}
Write-Host "done: ssh in as $account"
