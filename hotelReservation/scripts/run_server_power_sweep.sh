#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
HOTEL_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)

TARGET="hotels"
GOVERNOR=""
RATE=""
DURATION_SECONDS=60
POWERSTAT_INTERVAL=0.5
POWERSTAT_SOURCE="auto"
SETTLE_SECONDS=5
OUTPUT_DIR=""

usage() {
  cat <<'EOF'
Usage: run_server_power_sweep.sh [options]

Measure only server-side power for one arrival rate.

Options:
  --target <hotels|recommendations|reservation|user>
  --governor <schedutil|performance>   Required.
  --rate <rps>                         Required single arrival rate.
  --duration <seconds>                 Default: 60
  --powerstat-interval <seconds>       Default: 0.5
  --powerstat-source <auto|rapl|battery>
  --settle-seconds <seconds>           Pause after governor switch. Default: 5
  --output-dir <path>                  Default: hotelReservation/results/server_power_sweeps/<timestamp>
  --help
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
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
  if [[ "$source" == "rapl" ]]; then
    echo "120"
  else
    echo "600"
  fi
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

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET=$2
      shift 2
      ;;
    --governor)
      GOVERNOR=$2
      shift 2
      ;;
    --rate)
      RATE=$2
      shift 2
      ;;
    --duration)
      DURATION_SECONDS=$2
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

if [[ -z "$RATE" ]]; then
  echo "--rate is required" >&2
  usage >&2
  exit 1
fi

require_cmd python3
require_cmd sudo
require_cmd powerstat

if ! compgen -G "/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor" >/dev/null; then
  echo "No CPU governor controls found under /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor" >&2
  exit 1
fi

sudo -v

if [[ -z "$OUTPUT_DIR" ]]; then
  OUTPUT_DIR="$HOTEL_ROOT/results/server_power_sweeps/$(date -u +%Y%m%dT%H%M%SZ)_${TARGET}_${GOVERNOR}_${RATE}"
fi

mkdir -p "$OUTPUT_DIR/logs"
CPU_STATE_DIR="$OUTPUT_DIR/cpu_state"
mkdir -p "$CPU_STATE_DIR"
RESULTS_CSV="$OUTPUT_DIR/results.csv"
POWER_OUTPUT="$OUTPUT_DIR/logs/powerstat_${TARGET}_${GOVERNOR}_${RATE}.log"
RESTORE_STATE_FILE="$CPU_STATE_DIR/original_state.txt"

printf "target,governor,arrival_rate_rps,avg_power_watts,powerstat_output\n" >"$RESULTS_CSV"

SOURCE=$(detect_powerstat_source)
COUNT=$(calc_powerstat_count "$DURATION_SECONDS" "$POWERSTAT_INTERVAL")
MIN_COUNT=$(powerstat_min_count "$SOURCE")
if (( COUNT < MIN_COUNT )); then
  COUNT=$MIN_COUNT
fi
EFFECTIVE_DURATION_SECONDS=$(duration_for_count "$COUNT" "$POWERSTAT_INTERVAL")
if [[ "$EFFECTIVE_DURATION_SECONDS" != "$DURATION_SECONDS" ]]; then
  echo "Extending measurement duration from ${DURATION_SECONDS}s to ${EFFECTIVE_DURATION_SECONDS}s to satisfy powerstat sample requirements."
fi

capture_restore_state "$RESTORE_STATE_FILE"
trap 'restore_cpu_state "$RESTORE_STATE_FILE"' EXIT

capture_cpu_state "$CPU_STATE_DIR/before_${GOVERNOR}.log"
configure_frequency "$GOVERNOR"
capture_cpu_state "$CPU_STATE_DIR/after_${GOVERNOR}.log"
sleep "$SETTLE_SECONDS"

powerstat_cmd=(sudo powerstat -n)
if [[ "$SOURCE" == "rapl" ]]; then
  powerstat_cmd+=(-R)
fi
powerstat_cmd+=("$POWERSTAT_INTERVAL" "$COUNT")

echo "Measuring target=$TARGET governor=$GOVERNOR rate=${RATE}rps"
"${powerstat_cmd[@]}" >"$POWER_OUTPUT" 2>&1

AVG_POWER=$(extract_avg_power "$POWER_OUTPUT")
printf "%s,%s,%s,%s,%s\n" "$TARGET" "$GOVERNOR" "$RATE" "$AVG_POWER" "$POWER_OUTPUT" >>"$RESULTS_CSV"

echo "Results CSV: $RESULTS_CSV"
