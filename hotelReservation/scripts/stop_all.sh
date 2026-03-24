#!/bin/bash
# Gracefully stop all hotel reservation services and backing infrastructure.

echo "Stopping Go services..."
for svc in frontend search attractions review reservation user recommendation rate profile geo; do
    if [ -f "/tmp/hotel-$svc.pid" ]; then
        PID=$(cat "/tmp/hotel-$svc.pid")
        if kill "$PID" 2>/dev/null; then
            echo "  Stopped $svc (PID: $PID)"
        else
            echo "  $svc (PID: $PID) already stopped"
        fi
        rm -f "/tmp/hotel-$svc.pid"
    fi
done

# Wait for services to deregister from Consul
sleep 2

echo "Stopping backing services..."

# Stop MongoDB
if mongod --dbpath /tmp/hotel-mongo --shutdown 2>/dev/null; then
    echo "  Stopped MongoDB"
fi

# Stop Memcached
for pidfile in /tmp/hotel-memc-*.pid; do
    if [ -f "$pidfile" ]; then
        PID=$(cat "$pidfile")
        kill "$PID" 2>/dev/null && echo "  Stopped memcached (PID: $PID)"
        rm -f "$pidfile"
    fi
done

# Stop Jaeger
if [ -f /tmp/hotel-jaeger.pid ]; then
    PID=$(cat /tmp/hotel-jaeger.pid)
    kill "$PID" 2>/dev/null && echo "  Stopped Jaeger (PID: $PID)"
    rm -f /tmp/hotel-jaeger.pid
fi

# Stop Consul
if [ -f /tmp/hotel-consul.pid ]; then
    PID=$(cat /tmp/hotel-consul.pid)
    kill "$PID" 2>/dev/null && echo "  Stopped Consul (PID: $PID)"
    rm -f /tmp/hotel-consul.pid
fi

echo "All services stopped."
