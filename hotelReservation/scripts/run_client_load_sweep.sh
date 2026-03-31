#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
HOTEL_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
REPO_ROOT=$(cd -- "$HOTEL_ROOT/.." && pwd)
WRK_BIN="$REPO_ROOT/wrk2/wrk"
LUA_SCRIPT="$HOTEL_ROOT/wrk2/scripts/hotel-reservation/single-endpoint.lua"

TARGET="hotels"
HOST="http://localhost:5000"
THREADS=4
CONNECTIONS=128
DURATION_SECONDS=60
RATES_SPEC="1000:20000:1000"
SETTLE_SECONDS=15
OUTPUT_DIR=""

usage() {
  cat <<'EOF'
Usage: run_client_load_sweep.sh [options]

Run Poisson-distributed wrk2 load from the client against one frontend endpoint,
save per-rate wrk logs, and write a CSV summary with latency statistics.

Options:
  --target <hotels|recommendations|reservation|user>
  --host <url>                   Frontend base URL. Default: http://localhost:5000
  --threads <n>                  wrk2 thread count. Default: 4
  --connections <n>              wrk2 connection count. Default: 128
  --duration <seconds>           Run length per point. Default: 60
  --rates <csv|start:end:step>   Example: 2000,4000,6000 or 2000:20000:2000
  --settle-seconds <seconds>     Pause between runs. Default: 15
  --output-dir <path>            Default: hotelReservation/results/client_load_sweeps/<timestamp>
  --help
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

expand_rates() {
  local spec=$1
  if [[ "$spec" == *:*:* ]]; then
    IFS=: read -r start end step <<<"$spec"
    python3 - "$start" "$end" "$step" <<'PY'
import sys
start, end, step = map(int, sys.argv[1:])
if step <= 0:
    raise SystemExit("rate step must be > 0")
if end < start:
    raise SystemExit("rate end must be >= start")
print(",".join(str(v) for v in range(start, end + 1, step)))
PY
  else
    echo "$spec"
  fi
}

extract_metric() {
  local pattern=$1
  local file=$2
  awk -v pattern="$pattern" '$0 ~ pattern {print $2; exit}' "$file"
}

extract_requests_per_sec() {
  local file=$1
  awk '/Requests\/sec:/ {print $2; exit}' "$file"
}

extract_socket_errors() {
  local file=$1
  awk '/Socket errors:/ {print substr($0, index($0, ":") + 2); exit}' "$file"
}

extract_non2xx() {
  local file=$1
  awk '/Non-2xx or 3xx responses:/ {print $5; exit}' "$file"
}

extract_summary_line() {
  local prefix=$1
  local file=$2
  awk -v prefix="$prefix" '$1 == prefix {print $2; exit}' "$file"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET=$2
      shift 2
      ;;
    --host)
      HOST=$2
      shift 2
      ;;
    --threads)
      THREADS=$2
      shift 2
      ;;
    --connections)
      CONNECTIONS=$2
      shift 2
      ;;
    --duration)
      DURATION_SECONDS=$2
      shift 2
      ;;
    --rates)
      RATES_SPEC=$2
      shift 2
      ;;
    --settle-seconds)
      SETTLE_SECONDS=$2
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR=$2
      shift 2
      ;;
    --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

case "$TARGET" in
  hotels|recommendations|reservation|user) ;;
  *)
    echo "Unsupported target: $TARGET" >&2
    exit 1
    ;;
esac

require_cmd python3

if [[ ! -x "$WRK_BIN" ]]; then
  echo "wrk2 binary not found or not executable: $WRK_BIN" >&2
  exit 1
fi

if [[ ! -f "$LUA_SCRIPT" ]]; then
  echo "Lua workload script not found: $LUA_SCRIPT" >&2
  exit 1
fi

if [[ -z "$OUTPUT_DIR" ]]; then
  OUTPUT_DIR="$HOTEL_ROOT/results/client_load_sweeps/$(date -u +%Y%m%dT%H%M%SZ)_${TARGET}"
fi

mkdir -p "$OUTPUT_DIR/logs"
RESULTS_CSV="$OUTPUT_DIR/results.csv"
printf "target,arrival_rate_rps,requests_sec,latency_avg,latency_stdev,latency_max,p50,p90,p99,socket_errors,non_2xx_3xx,wrk_output\n" >"$RESULTS_CSV"

IFS=, read -r -a rate_list <<<"$(expand_rates "$RATES_SPEC")"

for rate in "${rate_list[@]}"; do
  wrk_output="$OUTPUT_DIR/logs/wrk_${TARGET}_${rate}.log"
  echo "Running target=$TARGET rate=${rate}rps host=$HOST"

  HOTEL_RESERVATION_TARGET="$TARGET" \
    "$WRK_BIN" -D exp -t "$THREADS" -c "$CONNECTIONS" -d "${DURATION_SECONDS}s" -L \
    -s "$LUA_SCRIPT" "$HOST" -R "$rate" | tee "$wrk_output"

  requests_sec=$(extract_requests_per_sec "$wrk_output")
  latency_avg=$(extract_summary_line "Latency" "$wrk_output")
  latency_stdev=$(awk '$1 == "Latency" {print $3; exit}' "$wrk_output")
  latency_max=$(awk '$1 == "Latency" {print $4; exit}' "$wrk_output")
  p50=$(extract_metric "50.000%" "$wrk_output")
  p90=$(extract_metric "90.000%" "$wrk_output")
  p99=$(extract_metric "99.000%" "$wrk_output")
  socket_errors=$(extract_socket_errors "$wrk_output")
  non_2xx=$(extract_non2xx "$wrk_output")

  requests_sec=${requests_sec:-NA}
  latency_avg=${latency_avg:-NA}
  latency_stdev=${latency_stdev:-NA}
  latency_max=${latency_max:-NA}
  p50=${p50:-NA}
  p90=${p90:-NA}
  p99=${p99:-NA}
  socket_errors=${socket_errors:-none}
  non_2xx=${non_2xx:-0}

  printf "%s,%s,%s,%s,%s,%s,%s,%s,%s,\"%s\",%s,%s\n" \
    "$TARGET" "$rate" "$requests_sec" "$latency_avg" "$latency_stdev" "$latency_max" \
    "$p50" "$p90" "$p99" "$socket_errors" "$non_2xx" "$wrk_output" >>"$RESULTS_CSV"

  sleep "$SETTLE_SECONDS"
done

echo "Results CSV: $RESULTS_CSV"
