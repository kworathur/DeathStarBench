#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
HOTEL_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)

CLIENT_HOST="10.10.3.1"
SERVER_HOST="10.10.3.2"
TARGET="hotels"
GOVERNOR="performance"
THREADS=4
CONNECTIONS=128
DURATION=60
RATES="2000:12000:2000"
POWERSTAT_INTERVAL=0.5
SETTLE_SECONDS=5
REFERENCE_CLIENT_CSV="/tmp/real_hotels_performance_20260401T192823Z/performance/0_c220g1-030822.wisc.cloudlab.us_c220g1-030823.wisc.cloudlab.us_hotels/client/results/results.csv"
REFERENCE_SERVER_CSV="/tmp/real_hotels_performance_20260401T192823Z/corrected/server/results.csv"
OUTPUT_DIR=""
SSH_KEY="${HOTEL_REMOTE_SSH_KEY:-$HOME/.ssh/id_rsa}"
GIT_KEY="${HOTEL_REMOTE_GIT_KEY:-$HOME/.ssh/cloudlab_git}"
CLONE_REPO_URL="${HOTEL_REMOTE_CLONE_REPO_URL:-}"

usage() {
  cat <<'EOF'
Usage: run_reproduction_remote_check.sh [options]

Prepare the bare-process hotel stack on the remote server using the current repo
HEAD, run the distributed sweep, merge the distributed results, merge the
reference results, and emit a CSV comparison.

Options:
  --client-host <host>           Default: 10.10.3.1
  --server-host <host>           Default: 10.10.3.2
  --target <name>                Default: hotels
  --governor <name>              Default: performance
  --threads <n>                  Default: 4
  --connections <n>              Default: 128
  --duration <seconds>           Default: 60
  --rates <spec>                 Default: 2000:12000:2000
  --powerstat-interval <sec>     Default: 0.5
  --settle-seconds <sec>         Default: 5
  --reference-client-csv <path>
  --reference-server-csv <path>
  --output-dir <path>            Default: hotelReservation/results/reproduction_remote_check/<timestamp>
  --ssh-key <path>
  --private-key <path>
  --clone-repo-url <url>
  --help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --client-host)
      CLIENT_HOST=$2
      shift 2
      ;;
    --server-host)
      SERVER_HOST=$2
      shift 2
      ;;
    --target)
      TARGET=$2
      shift 2
      ;;
    --governor)
      GOVERNOR=$2
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
      DURATION=$2
      shift 2
      ;;
    --rates)
      RATES=$2
      shift 2
      ;;
    --powerstat-interval)
      POWERSTAT_INTERVAL=$2
      shift 2
      ;;
    --settle-seconds)
      SETTLE_SECONDS=$2
      shift 2
      ;;
    --reference-client-csv)
      REFERENCE_CLIENT_CSV=$2
      shift 2
      ;;
    --reference-server-csv)
      REFERENCE_SERVER_CSV=$2
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR=$2
      shift 2
      ;;
    --ssh-key)
      SSH_KEY=$2
      shift 2
      ;;
    --private-key)
      GIT_KEY=$2
      shift 2
      ;;
    --clone-repo-url)
      CLONE_REPO_URL=$2
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

if [[ -z "$OUTPUT_DIR" ]]; then
  OUTPUT_DIR="$HOTEL_ROOT/results/reproduction_remote_check/$(date -u +%Y%m%dT%H%M%SZ)"
fi

mkdir -p "$OUTPUT_DIR"

if [[ -z "$CLONE_REPO_URL" ]]; then
  CLONE_REPO_URL=$(git -C "$HOTEL_ROOT/.." config --get remote.origin.url)
fi

RUN_CMD=(
  python3 "$SCRIPT_DIR/run_distributed_power_sweeps.py"
  --client-hosts "$CLIENT_HOST"
  --server-hosts "$SERVER_HOST"
  --targets "$TARGET"
  --governors "$GOVERNOR"
  --ssh-key "$SSH_KEY"
  --private-key "$GIT_KEY"
  --clone-repo-url "$CLONE_REPO_URL"
  --prepare-server-stack
  --replace-server-stack
  --refresh-repo
  --threads "$THREADS"
  --connections "$CONNECTIONS"
  --duration "$DURATION"
  --rates "$RATES"
  --powerstat-interval "$POWERSTAT_INTERVAL"
  --settle-seconds "$SETTLE_SECONDS"
  --local-output-dir "$OUTPUT_DIR/run"
)

printf 'Running command:\n%s\n' "${RUN_CMD[*]}"
"${RUN_CMD[@]}"

CURRENT_RESULTS=$(find "$OUTPUT_DIR/run" -name results.csv | grep "/${GOVERNOR}/" | head -n 1)
if [[ -z "$CURRENT_RESULTS" ]]; then
  echo "Failed to locate current merged results.csv under $OUTPUT_DIR/run" >&2
  exit 1
fi

REFERENCE_MERGED="$OUTPUT_DIR/reference_results.csv"
python3 "$SCRIPT_DIR/merge_distributed_power_results.py" \
  --client "$REFERENCE_CLIENT_CSV" \
  --server "$REFERENCE_SERVER_CSV" \
  --output "$REFERENCE_MERGED"

COMPARISON_CSV="$OUTPUT_DIR/comparison.csv"
python3 "$SCRIPT_DIR/compare_power_sweep_results.py" \
  --current "$CURRENT_RESULTS" \
  --reference "$REFERENCE_MERGED" \
  --output "$COMPARISON_CSV"

echo "Current merged results: $CURRENT_RESULTS"
echo "Reference merged results: $REFERENCE_MERGED"
echo "Comparison CSV: $COMPARISON_CSV"
