# Starts ninfer-serve inside the WSL distro that holds the build, and reports the address Windows
# has to forward to. `ixd ninfer` pipes this in over ssh and sets NINFER_* above it.
#
# Idempotent: a server already listening on the port is left alone, model and all.

set -u

root=${NINFER_ROOT:-$HOME/projects/ninfer-4090}
model=${NINFER_MODEL:-models/qwen3_8_27b.ninfer}
port=${NINFER_PORT:-8080}
# The flags this box was already serving with: an int8 KV cache and speculative drafting inside the
# 24 GB the card has, with CUDA graphs off.
flags=${NINFER_FLAGS:---max-context 114688 --kv-capacity 114688 --max-concurrency 1 --max-pending-requests 16 --pending-timeout-ms 600000 --prefill-chunk 512 --kv-dtype int8 --spec mtp --draft-tokens 3 --lm-head-draft --no-cuda-graph}
log=${NINFER_LOG:-/tmp/ninfer.log}

echo "wsl-address $(hostname -I | awk '{print $1}')"

if curl -sf -m 3 "http://127.0.0.1:$port/v1/models" >/dev/null 2>&1; then
  echo "already serving on $port"
  exit 0
fi

cd "$root" || { echo "no ninfer checkout at $root"; exit 1; }
[ -x ./build/apps/ninfer-serve ] || { echo "no build at $root/build/apps/ninfer-serve"; exit 1; }
[ -f "$model" ] || { echo "no model at $root/$model"; exit 1; }

# --host 0.0.0.0, not the loopback it defaults to: WSL's own loopback is not reachable from
# Windows, let alone from the tailnet. setsid so the server outlives the ssh session that starts it.
# shellcheck disable=SC2086
setsid nohup ./build/apps/ninfer-serve "$model" --host 0.0.0.0 --port "$port" $flags \
  >"$log" 2>&1 </dev/null &
pid=$!

# Waiting here is not politeness, it is the difference between a server and no server: a WSL session
# that ends the instant after the fork takes the new process down with it, setsid or no setsid.
# Holding the session until the port answers puts the weights in VRAM before anything can race it.
ready=${NINFER_READY_SECONDS:-300}
while [ "$ready" -gt 0 ]; do
  if curl -sf -m 3 "http://127.0.0.1:$port/v1/models" >/dev/null 2>&1; then
    echo "serving on $port, pid $pid, logging to $log"
    exit 0
  fi
  kill -0 "$pid" 2>/dev/null || { echo "the server died while loading:"; tail -5 "$log"; exit 1; }
  sleep 3
  ready=$((ready - 3))
done

echo "the server did not answer on $port in time:"
tail -5 "$log"
exit 1
