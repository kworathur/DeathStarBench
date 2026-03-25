#!/bin/bash
# Start a single microservice process.
# Usage: start_service.sh <service_name> [--config <path>] [--consul <addr>] [--jaeger <addr>]
#
# This is the interface for the placement algorithm to start a service
# on a target server. The service registers itself with Consul automatically.

set -e

SERVICE="$1"
shift || { echo "Usage: start_service.sh <service_name> [--consul <addr>] [--jaeger <addr>]"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BIN_DIR="$PROJECT_DIR/bin"

CONFIG_PATH=""
CONSUL_ADDR=""
JAEGER_ADDR=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --config) CONFIG_PATH="$2"; shift 2 ;;
        --consul) CONSUL_ADDR="$2"; shift 2 ;;
        --jaeger) JAEGER_ADDR="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [ ! -f "$BIN_DIR/$SERVICE" ]; then
    echo "ERROR: Binary not found: $BIN_DIR/$SERVICE"
    exit 1
fi

cd "$PROJECT_DIR"

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

ARGS=(-config "$CONFIG_PATH")
if [ -n "$CONSUL_ADDR" ]; then
    ARGS+=(-consuladdr "$CONSUL_ADDR")
fi
if [ -n "$JAEGER_ADDR" ]; then
    ARGS+=(-jaegeraddr "$JAEGER_ADDR")
fi

echo "Using config: $CONFIG_PATH"
"$BIN_DIR/$SERVICE" "${ARGS[@]}" &
PID=$!
echo "$PID" > "/tmp/hotel-$SERVICE.pid"
echo "Started $SERVICE (PID: $PID)"
