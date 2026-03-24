#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HR_DIR="$REPO_ROOT/hotelReservation"

echo "=== Installing wrk2 build dependencies ==="
sudo apt update
sudo apt-get install -y libssl-dev
sudo apt install -y zlib1g zlib1g-dev
sudo apt-get install -y luarocks

echo "=== Compiling LuaJIT (wrk2) ==="
make -C "$REPO_ROOT/wrk2"

echo "=== Installing Go ==="
sudo apt install -y golang-go

echo "=== Building hotelReservation server binaries ==="
mkdir -p "$HR_DIR/bin"
SERVICES=(frontend search geo rate profile recommendation user reservation review attractions)
for svc in "${SERVICES[@]}"; do
    echo "  Building $svc..."
    (cd "$HR_DIR" && go build -o "bin/$svc" "./cmd/$svc")
done

echo "=== Installing project dependencies ==="

# Consul
echo "  Installing consul..."
wget -O - https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(grep -oP '(?<=UBUNTU_CODENAME=).*' /etc/os-release || lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
sudo apt update
sudo apt install -y consul

# MongoDB
echo "  Installing mongodb..."
sudo apt-get install -y gnupg curl
curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc | \
    sudo gpg -o /usr/share/keyrings/mongodb-server-8.0.gpg --dearmor
echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg ] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/8.0 multiverse" | sudo tee /etc/apt/sources.list.d/mongodb-org-8.0.list
sudo apt-get update
sudo apt-get install -y mongodb-org
sudo systemctl start mongod

# Memcached
echo "  Installing memcached..."
sudo apt install -y memcached libmemcached-tools
sudo systemctl start memcached
sudo systemctl enable memcached

# Jaeger (all-in-one)
echo "  Installing jaeger-all-in-one..."
wget https://github.com/jaegertracing/jaeger/releases/download/v2.16.0/jaeger-2.16.0-linux-amd64.tar.gz
tar -xzf jaeger-2.16.0-linux-amd64.tar.gz
sudo cp jaeger-2.16.0-linux-amd64/jaeger-all-in-one /usr/local/bin/
rm -rf jaeger-2.16.0-linux-amd64 jaeger-2.16.0-linux-amd64.tar.gz

echo "=== Install complete ==="
