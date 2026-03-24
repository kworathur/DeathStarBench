#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
HR_DIR="$REPO_ROOT/hotelReservation"

echo "=== Compiling LuaJIT (wrk2) ==="
make -C "$REPO_ROOT/wrk2"

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
sudo apt-get update
sudo apt-get install -y consul

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
sudo apt-get install -y memcached libmemcached-tools
sudo systemctl start memcached
sudo systemctl enable memcached

echo "=== Install complete ==="
