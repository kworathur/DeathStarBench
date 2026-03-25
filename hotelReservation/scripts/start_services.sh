#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BIN_DIR="$PROJECT_DIR/bin"

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

# Start data-layer services first (they seed MongoDB on first run)
echo "Starting data-layer services..."
for svc in geo profile rate recommendation reservation user review attractions; do
    "$BIN_DIR/$svc" "${COMMON_ARGS[@]}" &
    echo $! > "/tmp/hotel-$svc.pid"
    echo "  Started $svc (PID: $(cat /tmp/hotel-$svc.pid))"
    sleep 0.5
done

# Brief pause to let data-layer services register with Consul
sleep 1

# Start stateless services
echo "Starting stateless services..."
for svc in search frontend; do
    "$BIN_DIR/$svc" "${COMMON_ARGS[@]}" &
    echo $! > "/tmp/hotel-$svc.pid"
    echo "  Started $svc (PID: $(cat /tmp/hotel-$svc.pid))"
    sleep 0.5
done

echo ""
echo "All services started. Frontend at http://localhost:5000"
echo "Consul services: curl http://localhost:8500/v1/catalog/services"
