#!/bin/bash
set -e

LOG_DIR="/tmp/hotel-logs"
mkdir -p "$LOG_DIR"

echo "Starting backing services..."
echo "Logs directory: $LOG_DIR"

# Start Consul in dev mode
echo "Starting Consul..."
nohup consul agent -dev -client=0.0.0.0 > "$LOG_DIR/consul.log" 2>&1 < /dev/null &
CONSUL_PID=$!
echo "$CONSUL_PID" > /tmp/hotel-consul.pid
sleep 2

# Verify Consul is up
if ! curl -s http://localhost:8500/v1/status/leader > /dev/null; then
    echo "ERROR: Consul failed to start (see $LOG_DIR/consul.log)"
    exit 1
fi
echo "Consul started (PID: $CONSUL_PID)"

# Start MongoDB (single instance, all services use different databases)
echo "Starting MongoDB..."
mkdir -p /tmp/hotel-mongo
mongod --dbpath /tmp/hotel-mongo --port 27017 --bind_ip 0.0.0.0 --fork --logpath "$LOG_DIR/mongod.log"
echo "MongoDB started on port 27017"

# Start 4 Memcached instances (profile, review, rate, reserve)
echo "Starting Memcached instances..."
memcached -p 11211 -m 128 -t 2 -d -P /tmp/hotel-memc-11211.pid
memcached -p 11212 -m 128 -t 2 -d -P /tmp/hotel-memc-11212.pid
memcached -p 11213 -m 128 -t 2 -d -P /tmp/hotel-memc-11213.pid
memcached -p 11214 -m 128 -t 2 -d -P /tmp/hotel-memc-11214.pid
echo "Memcached started on ports 11211-11214"

# Start Jaeger
echo "Starting Jaeger..."
nohup jaeger > "$LOG_DIR/jaeger.log" 2>&1 < /dev/null &
JAEGER_PID=$!
echo "$JAEGER_PID" > /tmp/hotel-jaeger.pid
echo "Jaeger started (PID: $JAEGER_PID)"

echo ""
echo "All backing services started."
echo "  Consul UI:  http://localhost:8500"
echo "  Jaeger UI:  http://localhost:16686"
echo "  MongoDB:    localhost:27017"
echo "  Memcached:  localhost:11211-11214"
echo ""
echo "Logs:"
echo "  Consul:     $LOG_DIR/consul.log"
echo "  MongoDB:    $LOG_DIR/mongod.log"
echo "  Jaeger:     $LOG_DIR/jaeger.log"
