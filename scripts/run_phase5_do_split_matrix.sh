#!/usr/bin/env bash
set -euo pipefail

DOCTL="${DOCTL:-doctl}"
DO_TOKEN="${DO_TOKEN:-${DIGITALOCEAN_ACCESS_TOKEN:-}}"
REGION="${REGION:-nyc3}"
IMAGE="${IMAGE:-ubuntu-24-04-x64}"
NAME="${NAME:-dirsearch-phase5-split-$(date +%s)}"
TARGET_SIZE="${TARGET_SIZE:-s-4vcpu-8gb}"
SCANNER_SIZES="${SCANNER_SIZES:-s-2vcpu-4gb,s-4vcpu-8gb,s-8vcpu-16gb}"
RESULT_FILE="${RESULT_FILE:-phase5-do-split-matrix-result.json}"
RESULT_DIR="${RESULT_DIR:-phase5-do-split-results-$(date +%s)}"
KEEP_TARGET_DROPLET="${KEEP_TARGET_DROPLET:-0}"
TARGET_REMOTE_TIMEOUT="${TARGET_REMOTE_TIMEOUT:-600}"
SCANNER_REMOTE_TIMEOUT="${SCANNER_REMOTE_TIMEOUT:-3600}"
LOCAL_REQUESTS="${LOCAL_REQUESTS:-5000}"
LOCAL_CONTENTION_REQUESTS="${LOCAL_CONTENTION_REQUESTS:-1000}"
LOCAL_CONCURRENCIES="${LOCAL_CONCURRENCIES:-12,25,50}"
LOCAL_PROCESS_COUNTS="${LOCAL_PROCESS_COUNTS:-8}"
LOCAL_THREADS_PER_PROCESS="${LOCAL_THREADS_PER_PROCESS:-12}"
LOCAL_REPEATS="${LOCAL_REPEATS:-3}"
LOCAL_HIT_EVERY="${LOCAL_HIT_EVERY:-20}"
TIMEOUT="${TIMEOUT:-5}"

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
target_id=""
target_ssh_key_id=""

cleanup() {
  set +e
  if [[ -n "$target_id" && "$KEEP_TARGET_DROPLET" != "1" ]]; then
    "$DOCTL" compute droplet delete "$target_id" --force >/dev/null 2>&1
  fi
  if [[ -n "$target_ssh_key_id" ]]; then
    "$DOCTL" compute ssh-key delete "$target_ssh_key_id" --force >/dev/null 2>&1
  fi
  rm -rf "$tmpdir"
}
trap cleanup EXIT

mkdir -p "$RESULT_DIR"

ssh-keygen -q -t ed25519 -N "" -f "$tmpdir/id_ed25519"
target_ssh_key_name="$NAME-target-key"
target_ssh_key_id="$("$DOCTL" compute ssh-key import "$target_ssh_key_name" \
  --public-key-file "$tmpdir/id_ed25519.pub" \
  --format ID \
  --no-header)"

echo "Creating target droplet $NAME-target size=$TARGET_SIZE region=$REGION image=$IMAGE"
create_target_output="$("$DOCTL" compute droplet create "$NAME-target" \
  --region "$REGION" \
  --image "$IMAGE" \
  --size "$TARGET_SIZE" \
  --ssh-keys "$target_ssh_key_id" \
  --tag-name dirsearch-phase5-benchmark \
  --wait \
  --format ID,PublicIPv4 \
  --no-header)"
target_id="$(awk '{print $1}' <<<"$create_target_output")"
target_ip="$(awk '{print $2}' <<<"$create_target_output")"

if [[ -z "$target_ip" ]]; then
  for _ in $(seq 1 60); do
    target_ip="$("$DOCTL" compute droplet get "$target_id" --format PublicIPv4 --no-header | awk 'NF {print $1; exit}')"
    if [[ -n "$target_ip" ]]; then
      break
    fi
    sleep 5
  done
fi

if [[ -z "$target_ip" ]]; then
  echo "Target droplet $target_id did not receive a public IPv4 address" >&2
  exit 1
fi
echo "Target droplet id=$target_id ip=$target_ip"

ssh_opts=(
  -i "$tmpdir/id_ed25519"
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile="$tmpdir/known_hosts"
  -o ConnectTimeout=10
  -o ServerAliveInterval=15
  -o ServerAliveCountMax=4
)

target_ssh_ready=0
for _ in $(seq 1 60); do
  if ssh "${ssh_opts[@]}" root@"$target_ip" "true" >/dev/null 2>&1; then
    target_ssh_ready=1
    break
  fi
  sleep 5
done
if [[ "$target_ssh_ready" != "1" ]]; then
  echo "Target droplet $target_id did not become reachable over SSH" >&2
  exit 1
fi

timeout --preserve-status "$TARGET_REMOTE_TIMEOUT" ssh "${ssh_opts[@]}" root@"$target_ip" bash -s <<'REMOTE'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y nginx curl
systemctl stop nginx >/dev/null 2>&1 || true
cat >/etc/nginx/sites-available/default <<'NGINX'
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;

    access_log off;

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
REMOTE

for _ in $(seq 1 30); do
  hit_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "http://$target_ip/hit-probe" || true)"
  miss_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "http://$target_ip/miss-probe" || true)"
  if [[ "$hit_code" == "200" && "$miss_code" == "404" ]]; then
    break
  fi
  sleep 2
done
if [[ "$hit_code" != "200" || "$miss_code" != "404" ]]; then
  echo "Target did not pass HTTP probe: hit=$hit_code miss=$miss_code" >&2
  exit 1
fi

IFS=',' read -r -a scanner_sizes <<<"$SCANNER_SIZES"
for scanner_size in "${scanner_sizes[@]}"; do
  scanner_size="$(xargs <<<"$scanner_size")"
  [[ -n "$scanner_size" ]] || continue
  scanner_label="${scanner_size//[^[:alnum:]]/-}"
  scanner_result="$RESULT_DIR/$scanner_label.json"
  echo "Running scanner size=$scanner_size against http://$target_ip/"
  DO_TOKEN="$DO_TOKEN" \
  REGION="$REGION" \
  IMAGE="$IMAGE" \
  SIZE="$scanner_size" \
  NAME="$NAME-scanner-$scanner_label-$(date +%s)" \
  BENCHMARK_MODE=local-contention \
  LOCAL_BASE_URL="http://$target_ip/" \
  RESULT_FILE="$scanner_result" \
  REMOTE_TIMEOUT="$SCANNER_REMOTE_TIMEOUT" \
  TIMEOUT="$TIMEOUT" \
  LOCAL_REQUESTS="$LOCAL_REQUESTS" \
  LOCAL_CONTENTION_REQUESTS="$LOCAL_CONTENTION_REQUESTS" \
  LOCAL_CONCURRENCIES="$LOCAL_CONCURRENCIES" \
  LOCAL_PROCESS_COUNTS="$LOCAL_PROCESS_COUNTS" \
  LOCAL_THREADS_PER_PROCESS="$LOCAL_THREADS_PER_PROCESS" \
  LOCAL_REPEATS="$LOCAL_REPEATS" \
  LOCAL_HIT_EVERY="$LOCAL_HIT_EVERY" \
  scripts/run_phase5_do_benchmark.sh
done

python3 - "$RESULT_FILE" "$RESULT_DIR" "$TARGET_SIZE" "$target_ip" "$SCANNER_SIZES" "$LOCAL_REQUESTS" "$LOCAL_CONTENTION_REQUESTS" "$LOCAL_CONCURRENCIES" "$LOCAL_PROCESS_COUNTS" "$LOCAL_THREADS_PER_PROCESS" "$LOCAL_REPEATS" "$LOCAL_HIT_EVERY" <<'PY'
import json
import re
import sys
from pathlib import Path

(
    result_file,
    result_dir,
    target_size,
    target_ip,
    scanner_sizes,
    local_requests,
    local_contention_requests,
    local_concurrencies,
    local_process_counts,
    local_threads_per_process,
    local_repeats,
    local_hit_every,
) = sys.argv[1:]


def label(slug: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", slug)


def vcpus(slug: str) -> int | None:
    if match := re.match(r"s-(\d+)vcpu", slug):
        return int(match.group(1))
    if match := re.match(r"c-(\d+)", slug):
        return int(match.group(1))
    if match := re.match(r"g-(\d+)vcpu", slug):
        return int(match.group(1))
    return None


results = {}
for slug in [item.strip() for item in scanner_sizes.split(",") if item.strip()]:
    path = Path(result_dir) / f"{label(slug)}.json"
    results[slug] = {
        "scanner_vcpus": vcpus(slug),
        "result_file": str(path),
        "result": json.loads(path.read_text(encoding="utf-8")),
    }

payload = {
    "target": {
        "size": target_size,
        "public_ip": target_ip,
        "url": f"http://{target_ip}/",
    },
    "settings": {
        "local_requests": int(local_requests),
        "local_contention_requests": int(local_contention_requests),
        "local_concurrencies": local_concurrencies,
        "local_process_counts": local_process_counts,
        "local_threads_per_process": int(local_threads_per_process),
        "local_repeats": int(local_repeats),
        "local_hit_every": int(local_hit_every),
    },
    "scanner_results": results,
}
Path(result_file).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
print(f"Split benchmark result written to {result_file}")
PY
