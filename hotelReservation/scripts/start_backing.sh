#!/bin/bash
set -euo pipefail

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
MONGO_CPU=1
MEMCACHED_CPUS=0,2-31
MEMCACHED_PORT=11214
MONGO_DBPATH=/tmp/mongo-hotel
mkdir -p "$MONGO_DBPATH"
taskset -c "$MONGO_CPU" mongod \
  --dbpath "$MONGO_DBPATH" \
  --bind_ip 127.0.0.1 \
  --wiredTigerCacheSizeGB 0.5 \
  --setParameter wiredTigerConcurrentReadTransactions=5 \
  --setParameter wiredTigerConcurrentWriteTransactions=5 \
  --logpath /tmp/mongod.log \
  --fork
MONGOD_PID=$(pgrep -xo mongod)
taskset -a -pc "$MONGO_CPU" "$MONGOD_PID" >/dev/null
echo "$MONGOD_PID" > /tmp/hotel-mongod.pid
echo "MongoDB started on port 27017 (PID: $MONGOD_PID, CPU: $MONGO_CPU)"

# Start only the reservation memcached instance on CPUs not used by MongoDB.
echo "Starting reservation Memcached instance..."
taskset -c "$MEMCACHED_CPUS" memcached \
  -t 1 \
  -m 128 \
  -p "$MEMCACHED_PORT" \
  -u nobody \
  -d \
  -P "/tmp/hotel-memc-${MEMCACHED_PORT}.pid"
echo "Memcached started on port $MEMCACHED_PORT (CPUs: $MEMCACHED_CPUS)"

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
echo "  Memcached:  localhost:$MEMCACHED_PORT"
echo ""
echo "Logs:"
echo "  Consul:     $LOG_DIR/consul.log"
echo "  MongoDB:    $LOG_DIR/mongod.log"
echo "  Jaeger:     $LOG_DIR/jaeger.log"
