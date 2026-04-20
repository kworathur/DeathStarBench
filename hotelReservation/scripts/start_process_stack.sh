#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT=""
SESSION="hotel-power-stack"
CONFIG_PATH=""
FRONTEND_URL="http://127.0.0.1:5000"
WAIT_SECONDS=10
REPLACE_EXISTING=0
BUILD_BINARIES=1

usage() {
  cat <<'EOF'
Usage: start_process_stack.sh [options]

Start the hotelReservation bare-process stack inside a tmux session so it stays
running after SSH disconnects.

Options:
  --repo-root <path>          Required checkout root that contains hotelReservation/.
  --session <name>            tmux session name. Default: hotel-power-stack
  --config <path>             Optional config file passed to start_services.sh
  --frontend-url <url>        Health check URL. Default: http://127.0.0.1:5000
  --wait-seconds <n>          Wait after launch before health check. Default: 10
  --replace-existing          Stop any existing session and hotel processes first
  --skip-build                Do not build Go binaries before launch
  --help
EOF
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

wait_for_frontend() {
  local url=$1
  local timeout=$2
  local start_ts
  start_ts=$(date +%s)
  while true; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    if (( $(date +%s) - start_ts >= timeout )); then
      return 1
    fi
    sleep 1
  done
}

kill_known_services() {
  local services=(frontend search attractions review reservation user recommendation rate profile geo)
  for svc in "${services[@]}"; do
    sudo pkill -x "$svc" >/dev/null 2>&1 || true
  done
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      REPO_ROOT=$2
      shift 2
      ;;
    --session)
      SESSION=$2
      shift 2
      ;;
    --config)
      CONFIG_PATH=$2
      shift 2
      ;;
    --frontend-url)
      FRONTEND_URL=$2
      shift 2
      ;;
    --wait-seconds)
      WAIT_SECONDS=$2
      shift 2
      ;;
    --replace-existing)
      REPLACE_EXISTING=1
      shift
      ;;
    --skip-build)
      BUILD_BINARIES=0
      shift
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

if [[ -z "$REPO_ROOT" ]]; then
  echo "--repo-root is required" >&2
  usage >&2
  exit 1
fi

REPO_ROOT=$(python3 -c 'import os,sys; print(os.path.abspath(os.path.expanduser(sys.argv[1])))' "$REPO_ROOT")
HOTEL_ROOT="$REPO_ROOT/hotelReservation"
BIN_DIR="$HOTEL_ROOT/bin"
START_BACKING="$HOTEL_ROOT/scripts/start_backing.sh"
START_SERVICES="$HOTEL_ROOT/scripts/start_services.sh"
STOP_ALL="$HOTEL_ROOT/scripts/stop_all.sh"
SESSION_LOG_DIR="/tmp/${SESSION}_logs"

require_cmd tmux
require_cmd curl
require_cmd python3
require_cmd sudo
require_cmd go

if [[ ! -d "$HOTEL_ROOT" ]]; then
  echo "hotelReservation checkout not found under: $REPO_ROOT" >&2
  exit 1
fi

if (( REPLACE_EXISTING )); then
  tmux has-session -t "$SESSION" 2>/dev/null && tmux kill-session -t "$SESSION"
  if [[ -x "$STOP_ALL" ]]; then
    bash "$STOP_ALL" || true
  fi
  kill_known_services
fi

if (( BUILD_BINARIES )); then
  mkdir -p "$BIN_DIR"
  (
    cd "$HOTEL_ROOT"
    GOBIN="$BIN_DIR" GO111MODULE=on go install -mod=vendor ./cmd/...
  )
fi

mkdir -p "$SESSION_LOG_DIR"

TMUX_CMD="cd $(printf '%q' "$HOTEL_ROOT") && "
TMUX_CMD+="mkdir -p $(printf '%q' "$SESSION_LOG_DIR") && "
TMUX_CMD+="bash $(printf '%q' "$START_BACKING") > $(printf '%q' "$SESSION_LOG_DIR/start_backing.log") 2>&1 && "
TMUX_CMD+="bash $(printf '%q' "$START_SERVICES")"
if [[ -n "$CONFIG_PATH" ]]; then
  TMUX_CMD+=" --config $(printf '%q' "$CONFIG_PATH")"
fi
TMUX_CMD+=" > $(printf '%q' "$SESSION_LOG_DIR/start_services.log") 2>&1 && "
TMUX_CMD+="tail -f /dev/null"

tmux new-session -d -s "$SESSION" "$TMUX_CMD"
sleep "$WAIT_SECONDS"

if ! wait_for_frontend "$FRONTEND_URL" "$WAIT_SECONDS"; then
  echo "Frontend did not become healthy at $FRONTEND_URL" >&2
  echo "tmux logs: $SESSION_LOG_DIR" >&2
  exit 1
fi

echo "Started bare-process stack in tmux session '$SESSION'"
echo "Checkout: $REPO_ROOT"
echo "Frontend: $FRONTEND_URL"
echo "Logs: $SESSION_LOG_DIR"
