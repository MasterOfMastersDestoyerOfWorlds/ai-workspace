param(
  [Parameter(Mandatory)][string]$WslAddress,
  [int]$Port = 8080,
  [string]$Tailnet = '100.64.0.0/10'
)

# Forwards the port from Windows into the WSL distro serving ninfer, and opens it to the tailnet
# only. Rerun on every start: WSL2 is NAT'd here, and the distro takes a new address each time it
# comes up, which leaves yesterday's proxy pointing at nothing.

$ErrorActionPreference = 'Stop'

netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$Port | Out-Null
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=$Port `
  connectaddress=$WslAddress connectport=$Port | Out-Null
Write-Host "forwarding 0.0.0.0:$Port to ${WslAddress}:$Port"

$rule = Get-NetFirewallRule -DisplayName 'ninfer (tailnet)' -ErrorAction SilentlyContinue
if ($rule) {
  Set-NetFirewallRule -DisplayName 'ninfer (tailnet)' -LocalPort $Port -RemoteAddress $Tailnet
} else {
  New-NetFirewallRule -DisplayName 'ninfer (tailnet)' -Direction Inbound -Protocol TCP `
    -LocalPort $Port -RemoteAddress $Tailnet -Action Allow | Out-Null
}
Write-Host "port $Port is open to the tailnet only"
