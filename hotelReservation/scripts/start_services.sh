#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BIN_DIR="$PROJECT_DIR/bin"
LOG_DIR="/tmp/hotel-logs/services"
STARTUP_WAIT_SECS="${HOTEL_STARTUP_WAIT_SECS:-1}"

usage() {
    echo "Usage: start_services.sh [--config <path>] [--consul <addr>] [--jaeger <addr>]"
    echo "Defaults to config.local.json when available, otherwise config.json."
}

CONFIG_PATH=""
CONSUL_ADDR=""
JAEGER_ADDR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)
            CONFIG_PATH="$2"
            shift 2
            ;;
        --consul)
            CONSUL_ADDR="$2"
            shift 2
            ;;
        --jaeger)
            JAEGER_ADDR="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

if [ -z "$CONFIG_PATH" ] && [ -n "$HOTEL_RESERVATION_CONFIG" ]; then
    CONFIG_PATH="$HOTEL_RESERVATION_CONFIG"
fi
if [ -z "$CONFIG_PATH" ] && [ -f "$PROJECT_DIR/config.local.json" ]; then
    CONFIG_PATH="$PROJECT_DIR/config.local.json"
fi
if [ -z "$CONFIG_PATH" ]; then
    CONFIG_PATH="$PROJECT_DIR/config.json"
fi
if [ ! -f "$CONFIG_PATH" ]; then
    echo "ERROR: Config file not found: $CONFIG_PATH"
    exit 1
fi

mkdir -p "$LOG_DIR"

cd "$PROJECT_DIR"

COMMON_ARGS=(-config "$CONFIG_PATH")
if [ -n "$CONSUL_ADDR" ]; then
    COMMON_ARGS+=(-consuladdr "$CONSUL_ADDR")
fi
if [ -n "$JAEGER_ADDR" ]; then
    COMMON_ARGS+=(-jaegeraddr "$JAEGER_ADDR")
fi

echo "Using config: $CONFIG_PATH"
if [ -n "$CONSUL_ADDR" ]; then
    echo "Overriding Consul address: $CONSUL_ADDR"
fi
if [ -n "$JAEGER_ADDR" ]; then
    echo "Overriding Jaeger address: $JAEGER_ADDR"
fi
echo "Service logs: $LOG_DIR"

STARTED_SERVICES=()

cleanup_started_services() {
    if [ "${#STARTED_SERVICES[@]}" -eq 0 ]; then
        return
    fi

    echo "Stopping services started before the failure..."
    for (( idx=${#STARTED_SERVICES[@]}-1; idx>=0; idx-- )); do
        svc="${STARTED_SERVICES[$idx]}"
        pidfile="/tmp/hotel-$svc.pid"
        if [ -f "$pidfile" ]; then
            pid="$(cat "$pidfile")"
            kill "$pid" 2>/dev/null || true
            rm -f "$pidfile"
            echo "  Stopped $svc (PID: $pid)"
        fi
    done
}

start_service() {
    svc="$1"
    binary="$BIN_DIR/$svc"
    logfile="$LOG_DIR/$svc.log"

    if [ ! -x "$binary" ]; then
        echo "ERROR: Binary not found or not executable: $binary"
        cleanup_started_services
        exit 1
    fi

    : > "$logfile"
    "$binary" "${COMMON_ARGS[@]}" > "$logfile" 2>&1 &
    pid=$!
    echo "$pid" > "/tmp/hotel-$svc.pid"

    sleep "$STARTUP_WAIT_SECS"

    if ! kill -0 "$pid" 2>/dev/null; then
        wait "$pid" || true
        rm -f "/tmp/hotel-$svc.pid"
        echo "ERROR: $svc exited during startup. Log: $logfile"
        tail -n 20 "$logfile" || true
        cleanup_started_services
        exit 1
    fi

    STARTED_SERVICES+=("$svc")
    echo "  Started $svc (PID: $pid, log: $logfile)"
}

# Start data-layer services first (they seed MongoDB on first run)
echo "Starting data-layer services..."
for svc in geo profile rate recommendation reservation user review attractions; do
    start_service "$svc"
done

# Brief pause to let data-layer services register with Consul
sleep 1

# Start stateless services
echo "Starting stateless services..."
for svc in search frontend; do
    start_service "$svc"
done

echo ""
echo "All services started. Frontend at http://localhost:5000"
echo "Consul services: curl http://localhost:8500/v1/catalog/services"
