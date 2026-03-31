#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
HOTEL_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
REPO_ROOT=$(cd -- "$HOTEL_ROOT/.." && pwd)
WRK_BIN="$REPO_ROOT/wrk2/wrk"
LUA_SCRIPT="$REPO_ROOT/hotelReservation/wrk2/scripts/hotel-reservation/single-endpoint.lua"
PLOT_SCRIPT="$REPO_ROOT/hotelReservation/scripts/plot_power_sweep.py"

TARGET="hotels"
HOST="http://localhost:5000"
THREADS=2
CONNECTIONS=2
DURATION_SECONDS=30
RATES_SPEC="1000:7000:1000"
GOVERNOR=""
POWERSTAT_INTERVAL=0.5
SETTLE_SECONDS=5
OUTPUT_DIR=""
POWERSTAT_SOURCE="auto"

usage() {
  cat <<'EOF'
Usage: run_power_sweep.sh [options]

Sweeps wrk2 Poisson arrival rates against one hotelReservation frontend endpoint,
records average power via powerstat, and generates a per-governor plot.

Options:
  --target <hotels|recommendations|reservation|user>
  --governor <schedutil|performance>   Required. Run once per governor.
  --host <url>                         Frontend base URL. Default: http://localhost:5000
  --threads <n>                       wrk2 thread count. Default: 2
  --connections <n>                   wrk2 connection count. Default: 2
  --duration <seconds>                Run length per point. Default: 30
  --rates <csv|start:end:step>        Example: 1000,3000,5000 or 1000:7000:1000
  --powerstat-interval <seconds>      Sampling interval. Default: 0.5
  --powerstat-source <auto|rapl|battery>
  --settle-seconds <seconds>          Pause after governor switch. Default: 5
  --output-dir <path>                 Default: hotelReservation/results/power_sweeps/<timestamp>
  --help

Example:
  ./hotelReservation/scripts/run_power_sweep.sh \
    --target hotels \
    --governor schedutil \
    --rates 1000:7000:1000 \
    --threads 4 \
    --connections 32
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_python_module() {
  local module=$1
  python3 - "$module" <<'PY' >/dev/null 2>&1
import importlib
import sys
importlib.import_module(sys.argv[1])
PY
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

detect_powerstat_source() {
  case "$POWERSTAT_SOURCE" in
    auto)
      if [[ -d /sys/class/powercap/intel-rapl ]]; then
        echo "rapl"
      else
        echo "battery"
      fi
      ;;
    rapl|battery)
      echo "$POWERSTAT_SOURCE"
      ;;
    *)
      echo "Unsupported powerstat source: $POWERSTAT_SOURCE" >&2
      exit 1
      ;;
  esac
}

calc_powerstat_count() {
  local duration=$1
  local interval=$2
  python3 - "$duration" "$interval" <<'PY'
import math
import sys
duration = float(sys.argv[1])
interval = float(sys.argv[2])
print(int(math.ceil(duration / interval)))
PY
}

powerstat_min_count() {
  local source=$1
  local min_count=600
  if [[ "$source" == "rapl" ]]; then
    min_count=120
  fi
  printf "%s\n" "$min_count"
}

duration_for_count() {
  local count=$1
  local interval=$2
  python3 - "$count" "$interval" <<'PY'
import sys
count = int(sys.argv[1])
interval = float(sys.argv[2])
duration = count * interval
if duration.is_integer():
    print(int(duration))
else:
    print(duration)
PY
}

print_frequency_state() {
  local output=$1
  {
    echo "== scaling_min_freq =="
    for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_min_freq; do
      [[ -e "$f" ]] || continue
      echo "$f: $(cat "$f")"
    done
    echo "== scaling_max_freq =="
    for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq; do
      [[ -e "$f" ]] || continue
      echo "$f: $(cat "$f")"
    done
    echo "== scaling_cur_freq =="
    for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq; do
      [[ -e "$f" ]] || continue
      echo "$f: $(cat "$f")"
    done
    echo "== scaling_governor =="
    for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
      [[ -e "$f" ]] || continue
      echo "$f: $(cat "$f")"
    done
  } | tee "$output"
}

capture_cpu_state() {
  local output=$1
  sudo bash -c "$(declare -f print_frequency_state); print_frequency_state '$output'" >/dev/null
}

capture_restore_state() {
  local output=$1
  sudo bash -c '
set -euo pipefail
: > "'"$output"'"
for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
  [[ -e "$f" ]] || continue
  printf "governor|%s|%s\n" "$f" "$(cat "$f")" >> "'"$output"'"
done
for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_min_freq; do
  [[ -e "$f" ]] || continue
  printf "min|%s|%s\n" "$f" "$(cat "$f")" >> "'"$output"'"
done
for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq; do
  [[ -e "$f" ]] || continue
  printf "max|%s|%s\n" "$f" "$(cat "$f")" >> "'"$output"'"
done
'
}

ensure_cpupower() {
  if command -v cpupower >/dev/null 2>&1; then
    return
  fi
  echo "cpupower not found; installing linux-tools-common and linux-tools-$(uname -r)"
  sudo apt-get update
  sudo apt-get install -y linux-tools-common "linux-tools-$(uname -r)"
}

configure_frequency() {
  local governor=$1
  echo "Setting CPU frequency policy for '$governor'"
  ensure_cpupower
  sudo modprobe acpi_cpufreq || true
  if [[ "$governor" == "performance" ]]; then
    sudo cpupower frequency-set -g performance
    sudo cpupower frequency-set -u 3.2GHz -d 3.2GHz
  else
    sudo cpupower frequency-set -g schedutil
    sudo cpupower frequency-set -d 1.2GHz -u 3.2GHz
  fi
}

restore_cpu_state() {
  local state_file=$1
  [[ -f "$state_file" ]] || return
  sudo bash -c '
set -euo pipefail
while IFS="|" read -r kind path value; do
  [[ -e "$path" ]] || continue
  case "$kind" in
    min|max)
      echo "$value" > "$path"
      ;;
  esac
done < "'"$state_file"'"
while IFS="|" read -r kind path value; do
  [[ -e "$path" ]] || continue
  case "$kind" in
    governor)
      echo "$value" > "$path"
      ;;
  esac
done < "'"$state_file"'"
'
}

extract_avg_power() {
  local powerstat_output=$1
  local value
  value=$(awk '/^CPU:/ {print $2}' "$powerstat_output" | tail -n 1)
  if [[ -z "$value" ]]; then
    echo "Failed to parse average power from $powerstat_output" >&2
    exit 1
  fi
  printf "%s\n" "${value//,/}"
}

extract_requests_per_sec() {
  local wrk_output=$1
  local value
  value=$(awk '/Requests\/sec:/ {print $2}' "$wrk_output" | tail -n 1)
  if [[ -z "$value" ]]; then
    echo "Failed to parse Requests/sec from $wrk_output" >&2
    exit 1
  fi
  printf "%s\n" "$value"
}

run_single_point() {
  local governor=$1
  local rate=$2
  local source=$3
  local count=$4

  local wrk_output="$OUTPUT_DIR/logs/wrk_${TARGET}_${governor}_${rate}.log"
  local power_output="$OUTPUT_DIR/logs/powerstat_${TARGET}_${governor}_${rate}.log"
  local powerstat_pid=""

  local -a powerstat_cmd=(sudo powerstat -n)
  if [[ "$source" == "rapl" ]]; then
    powerstat_cmd+=( -R )
  fi
  powerstat_cmd+=( "$POWERSTAT_INTERVAL" "$count" )

  echo "Running target=$TARGET governor=$governor rate=${rate}rps"
  "${powerstat_cmd[@]}" >"$power_output" 2>&1 &
  powerstat_pid=$!
  sleep 0.2

  HOTEL_RESERVATION_TARGET="$TARGET" \
    "$WRK_BIN" -D exp -t "$THREADS" -c "$CONNECTIONS" -d "${EFFECTIVE_DURATION_SECONDS}s" -L \
    -s "$LUA_SCRIPT" "$HOST" -R "$rate" >"$wrk_output" 2>&1 || {
      kill "$powerstat_pid" >/dev/null 2>&1 || true
      wait "$powerstat_pid" >/dev/null 2>&1 || true
      echo "wrk2 failed for governor=$governor rate=$rate. See $wrk_output" >&2
      exit 1
    }

  wait "$powerstat_pid"

  local avg_power
  local req_per_sec
  avg_power=$(extract_avg_power "$power_output")
  req_per_sec=$(extract_requests_per_sec "$wrk_output")

  printf "%s,%s,%s,%s,%s,%s,%s\n" \
    "$TARGET" "$governor" "$rate" "$req_per_sec" "$avg_power" "$wrk_output" "$power_output" >>"$RESULTS_CSV"
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
    --governor)
      GOVERNOR=$2
      shift 2
      ;;
    --powerstat-interval)
      POWERSTAT_INTERVAL=$2
      shift 2
      ;;
    --powerstat-source)
      POWERSTAT_SOURCE=$2
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

case "$GOVERNOR" in
  schedutil|performance) ;;
  "")
    echo "--governor is required" >&2
    usage >&2
    exit 1
    ;;
  *)
    echo "Unsupported governor: $GOVERNOR" >&2
    exit 1
    ;;
esac

require_cmd python3
require_cmd sudo
require_cmd powerstat

if [[ ! -x "$WRK_BIN" ]]; then
  echo "wrk2 binary not found or not executable: $WRK_BIN" >&2
  exit 1
fi

if [[ ! -f "$LUA_SCRIPT" ]]; then
  echo "Lua workload script not found: $LUA_SCRIPT" >&2
  exit 1
fi

if [[ ! -f "$PLOT_SCRIPT" ]]; then
  echo "Plot script not found: $PLOT_SCRIPT" >&2
  exit 1
fi

if ! compgen -G "/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor" >/dev/null; then
  echo "No CPU governor controls found under /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor" >&2
  exit 1
fi

if ! require_python_module matplotlib; then
  echo "Missing required Python module: matplotlib" >&2
  echo "Install it before running the sweep, for example: python3 -m pip install matplotlib" >&2
  exit 1
fi

sudo -v

if [[ -z "$OUTPUT_DIR" ]]; then
  OUTPUT_DIR="$HOTEL_ROOT/results/power_sweeps/$(date -u +%Y%m%dT%H%M%SZ)_${TARGET}"
fi

mkdir -p "$OUTPUT_DIR/logs"
mkdir -p "$OUTPUT_DIR/.matplotlib"
CPU_STATE_DIR="$OUTPUT_DIR/cpu_state"
mkdir -p "$CPU_STATE_DIR"
RESULTS_CSV="$OUTPUT_DIR/results.csv"
PLOT_PATH="$OUTPUT_DIR/arrival_rate_vs_power.png"
RESTORE_STATE_FILE="$CPU_STATE_DIR/original_state.txt"

printf "target,governor,arrival_rate_rps,requests_sec,avg_power_watts,wrk_output,powerstat_output\n" >"$RESULTS_CSV"

RATES=$(expand_rates "$RATES_SPEC")
SOURCE=$(detect_powerstat_source)
COUNT=$(calc_powerstat_count "$DURATION_SECONDS" "$POWERSTAT_INTERVAL")
MIN_COUNT=$(powerstat_min_count "$SOURCE")
if (( COUNT < MIN_COUNT )); then
  COUNT=$MIN_COUNT
fi
EFFECTIVE_DURATION_SECONDS=$(duration_for_count "$COUNT" "$POWERSTAT_INTERVAL")
if [[ "$EFFECTIVE_DURATION_SECONDS" != "$DURATION_SECONDS" ]]; then
  echo "Extending run duration from ${DURATION_SECONDS}s to ${EFFECTIVE_DURATION_SECONDS}s to satisfy powerstat sample requirements."
fi

capture_restore_state "$RESTORE_STATE_FILE"
trap 'restore_cpu_state "$RESTORE_STATE_FILE"' EXIT

IFS=, read -r -a rate_list <<<"$RATES"

capture_cpu_state "$CPU_STATE_DIR/before_${GOVERNOR}.log"
configure_frequency "$GOVERNOR"
capture_cpu_state "$CPU_STATE_DIR/after_${GOVERNOR}.log"
sleep "$SETTLE_SECONDS"
for rate in "${rate_list[@]}"; do
  run_single_point "$GOVERNOR" "$rate" "$SOURCE" "$COUNT"
done

MPLCONFIGDIR="$OUTPUT_DIR/.matplotlib" python3 "$PLOT_SCRIPT" --input "$RESULTS_CSV" --output "$PLOT_PATH"

echo "Results CSV: $RESULTS_CSV"
echo "Plot: $PLOT_PATH"
