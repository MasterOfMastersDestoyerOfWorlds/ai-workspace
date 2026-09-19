# Stops ninfer-serve inside WSL, which is the only way the card comes back: the runtime holds its
# model resident for as long as the process lives. `ixd ninfer --stop` pipes this in over ssh.

set -u

port=${NINFER_PORT:-8080}

if ! pgrep -f ninfer-serve >/dev/null; then
  echo "no server was running"
  exit 0
fi

pkill -f ninfer-serve || true
for _ in $(seq 1 40); do
  pgrep -f ninfer-serve >/dev/null || break
  sleep 1
done
if pgrep -f ninfer-serve >/dev/null; then
  echo "the server is still running after 40s"
  exit 1
fi
echo "stopped the server that was on $port"
