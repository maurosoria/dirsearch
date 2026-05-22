#!/usr/bin/env bash
set -euo pipefail

DOCTL="${DOCTL:-doctl}"
DO_TOKEN="${DO_TOKEN:-${DIGITALOCEAN_ACCESS_TOKEN:-}}"
REGION="${REGION:-nyc3}"
IMAGE="${IMAGE:-ubuntu-24-04-x64}"
SIZE="${SIZE:-}"
NAME="${NAME:-dirsearch-phase5-$(date +%s)}"
TARGETS="${TARGETS:-all}"
LIMIT="${LIMIT:-500}"
CONCURRENCY="${CONCURRENCY:-12}"
TIMEOUT="${TIMEOUT:-8}"
KEEP_DROPLET="${KEEP_DROPLET:-0}"
REMOTE_TIMEOUT="${REMOTE_TIMEOUT:-1800}"
NO_PREFLIGHT="${NO_PREFLIGHT:-0}"
BENCHMARK_MODE="${BENCHMARK_MODE:-vulnweb}"
LOCAL_REQUESTS="${LOCAL_REQUESTS:-5000}"
LOCAL_CONTENTION_REQUESTS="${LOCAL_CONTENTION_REQUESTS:-1000}"
LOCAL_CONCURRENCIES="${LOCAL_CONCURRENCIES:-12,25,50}"
LOCAL_PROCESS_COUNTS="${LOCAL_PROCESS_COUNTS:-1,2,4,8}"
LOCAL_THREADS_PER_PROCESS="${LOCAL_THREADS_PER_PROCESS:-12}"
LOCAL_REPEATS="${LOCAL_REPEATS:-3}"
LOCAL_HIT_EVERY="${LOCAL_HIT_EVERY:-20}"
LOCAL_BASE_URL="${LOCAL_BASE_URL:-http://127.0.0.1/}"

if [[ -z "$DO_TOKEN" ]]; then
  echo "Set DO_TOKEN or DIGITALOCEAN_ACCESS_TOKEN" >&2
  exit 1
fi

if ! command -v "$DOCTL" >/dev/null 2>&1; then
  echo "doctl not found. Set DOCTL=/path/to/doctl" >&2
  exit 1
fi

export DIGITALOCEAN_ACCESS_TOKEN="$DO_TOKEN"

tmpdir="$(mktemp -d)"
droplet_id=""
ssh_key_id=""
result_file="${RESULT_FILE:-phase5-do-result.json}"

cleanup() {
  set +e
  if [[ -n "$droplet_id" && "$KEEP_DROPLET" != "1" ]]; then
    "$DOCTL" compute droplet delete "$droplet_id" --force >/dev/null 2>&1
  fi
  if [[ -n "$ssh_key_id" ]]; then
    "$DOCTL" compute ssh-key delete "$ssh_key_id" --force >/dev/null 2>&1
  fi
  rm -rf "$tmpdir"
}
trap cleanup EXIT

ssh-keygen -q -t ed25519 -N "" -f "$tmpdir/id_ed25519"
ssh_key_name="$NAME-key"
ssh_key_id="$("$DOCTL" compute ssh-key import "$ssh_key_name" \
  --public-key-file "$tmpdir/id_ed25519.pub" \
  --format ID \
  --no-header)"

if [[ -z "$SIZE" ]]; then
  SIZE="$("$DOCTL" compute size list -o json | REGION="$REGION" python3 -c '
import json, sys
import os
sizes = json.load(sys.stdin)
region = os.environ["REGION"]
def val(size, *names):
    for name in names:
        if name in size:
            return size[name]
    return None
candidates = []
for size in sizes:
    slug = val(size, "slug", "Slug")
    memory = int(val(size, "memory", "Memory") or 0)
    vcpus = int(val(size, "vcpus", "VCPUs") or 0)
    regions = val(size, "regions", "Regions") or []
    if slug and region in regions and vcpus >= 4 and memory >= 4096:
        candidates.append((memory, vcpus, slug))
if not candidates:
    raise SystemExit("no >=4 vCPU, >=4GB size found")
print(sorted(candidates)[0][2])
')"
fi

echo "Creating droplet $NAME size=$SIZE region=$REGION image=$IMAGE"
create_output="$("$DOCTL" compute droplet create "$NAME" \
  --region "$REGION" \
  --image "$IMAGE" \
  --size "$SIZE" \
  --ssh-keys "$ssh_key_id" \
  --tag-name dirsearch-phase5-benchmark \
  --wait \
  --format ID,PublicIPv4 \
  --no-header)"
droplet_id="$(awk '{print $1}' <<<"$create_output")"
droplet_ip="$(awk '{print $2}' <<<"$create_output")"
if [[ -z "$droplet_ip" ]]; then
  for _ in $(seq 1 60); do
    droplet_ip="$("$DOCTL" compute droplet get "$droplet_id" --format PublicIPv4 --no-header | awk 'NF {print $1; exit}')"
    if [[ -n "$droplet_ip" ]]; then
      break
    fi
    sleep 5
  done
fi
if [[ -z "$droplet_ip" ]]; then
  echo "Droplet $droplet_id did not receive a public IPv4 address" >&2
  exit 1
fi
echo "Droplet id=$droplet_id ip=$droplet_ip"

ssh_opts=(
  -i "$tmpdir/id_ed25519"
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile="$tmpdir/known_hosts"
  -o ConnectTimeout=10
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=4
)

ssh_ready=0
for _ in $(seq 1 60); do
  if ssh "${ssh_opts[@]}" root@"$droplet_ip" "true" >/dev/null 2>&1; then
    ssh_ready=1
    break
  fi
  sleep 5
done
if [[ "$ssh_ready" != "1" ]]; then
  echo "Droplet $droplet_id did not become reachable over SSH" >&2
  exit 1
fi

tarball="$tmpdir/dirsearch-phase5.tar.gz"
tar \
  --exclude .git \
  --exclude .cache \
  --exclude .venv \
  --exclude build \
  --exclude dist \
  --exclude sessions \
  --exclude native/target \
  --exclude __pycache__ \
  -czf "$tarball" .

scp "${ssh_opts[@]}" "$tarball" root@"$droplet_ip":/root/dirsearch-phase5.tar.gz

remote_log="$tmpdir/remote.log"
timeout --preserve-status "$REMOTE_TIMEOUT" ssh "${ssh_opts[@]}" root@"$droplet_ip" bash -s -- \
  "$BENCHMARK_MODE" \
  "$TARGETS" \
  "$LIMIT" \
  "$CONCURRENCY" \
  "$TIMEOUT" \
  "$NO_PREFLIGHT" \
  "$LOCAL_REQUESTS" \
  "$LOCAL_CONTENTION_REQUESTS" \
  "$LOCAL_CONCURRENCIES" \
  "$LOCAL_PROCESS_COUNTS" \
  "$LOCAL_THREADS_PER_PROCESS" \
  "$LOCAL_REPEATS" \
  "$LOCAL_HIT_EVERY" \
  "$LOCAL_BASE_URL" <<'REMOTE' | tee "$remote_log"
set -euo pipefail
benchmark_mode="$1"
targets="$2"
limit="$3"
concurrency="$4"
timeout="$5"
no_preflight="$6"
local_requests="$7"
local_contention_requests="$8"
local_concurrencies="$9"
local_process_counts="${10}"
local_threads_per_process="${11}"
local_repeats="${12}"
local_hit_every="${13}"
local_base_url="${14}"

export DEBIAN_FRONTEND=noninteractive
apt-get update
packages=(python3-venv python3-pip build-essential curl pkg-config libssl-dev)
if [[ "$benchmark_mode" == "local-contention" && "$local_base_url" == "http://127.0.0.1/" ]]; then
  packages+=(nginx)
fi
apt-get install -y "${packages[@]}"
if [[ "$benchmark_mode" == "local-contention" && "$local_base_url" == "http://127.0.0.1/" ]]; then
  systemctl stop nginx >/dev/null 2>&1 || true
  cat >/etc/nginx/sites-available/default <<'NGINX'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    location /hit- {
        default_type text/plain;
        return 200 "ok\n";
    }

    location / {
        default_type text/plain;
        return 404 "not found\n";
    }
}
NGINX
  nginx -t
  nginx
fi

tar -xzf /root/dirsearch-phase5.tar.gz -C /root
cd /root

curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
export PATH=/root/.cargo/bin:$PATH

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install maturin
.venv/bin/python -m pip install -r requirements.txt
PATH=/root/.cargo/bin:$PATH .venv/bin/python -m maturin develop --manifest-path native/Cargo.toml

.venv/bin/python -m unittest \
  tests.core.test_wordlist_backend \
  tests.core.test_dictionary_templates \
  tests.core.test_request_backend \
  tests.connection.test_native_response \
  tests.core.test_native_fuzzer
benchmark_args=(
  --targets "$targets" \
  --limit "$limit" \
  --concurrency "$concurrency" \
  --timeout "$timeout"
)
if [[ "$no_preflight" == "1" ]]; then
  benchmark_args+=(--no-preflight)
fi
if [[ "$benchmark_mode" == "local-contention" ]]; then
  .venv/bin/python scripts/benchmark_local_contention.py \
    --base-url "$local_base_url" \
    --requests "$local_requests" \
    --contention-requests "$local_contention_requests" \
    --concurrencies "$local_concurrencies" \
    --process-counts "$local_process_counts" \
    --threads-per-process "$local_threads_per_process" \
    --repeats "$local_repeats" \
    --timeout "$timeout" \
    --hit-every "$local_hit_every" > /root/phase5-do-result.json
else
  .venv/bin/python scripts/benchmark_vulnweb_phase5.py "${benchmark_args[@]}" > /root/phase5-do-result.json
fi
echo "__PHASE5_RESULT_BEGIN__"
cat /root/phase5-do-result.json
echo "__PHASE5_RESULT_END__"
REMOTE

awk '
  /__PHASE5_RESULT_BEGIN__/ {capture=1; next}
  /__PHASE5_RESULT_END__/ {capture=0}
  capture {print}
' "$remote_log" > "$result_file"
if [[ ! -s "$result_file" ]]; then
  echo "Remote benchmark did not produce a result JSON" >&2
  exit 1
fi
echo "Benchmark result written to $result_file"
