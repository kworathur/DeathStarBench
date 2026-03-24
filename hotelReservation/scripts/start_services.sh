#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BIN_DIR="$PROJECT_DIR/bin"

# Use config.local.json as config.json
if [ ! -f "$PROJECT_DIR/config.json" ] || [ "$1" = "--reset-config" ]; then
    cp "$PROJECT_DIR/config.local.json" "$PROJECT_DIR/config.json"
    echo "Copied config.local.json -> config.json"
fi

cd "$PROJECT_DIR"

# Start data-layer services first (they seed MongoDB on first run)
echo "Starting data-layer services..."
for svc in geo profile rate recommendation reservation user review attractions; do
    "$BIN_DIR/$svc" &
    echo $! > "/tmp/hotel-$svc.pid"
    echo "  Started $svc (PID: $(cat /tmp/hotel-$svc.pid))"
    sleep 0.5
done

# Brief pause to let data-layer services register with Consul
sleep 1

# Start stateless services
echo "Starting stateless services..."
for svc in search frontend; do
    "$BIN_DIR/$svc" &
    echo $! > "/tmp/hotel-$svc.pid"
    echo "  Started $svc (PID: $(cat /tmp/hotel-$svc.pid))"
    sleep 0.5
done

echo ""
echo "All services started. Frontend at http://localhost:5000"
echo "Consul services: curl http://localhost:8500/v1/catalog/services"
