#!/usr/bin/env python3
import os
from pathlib import Path

# Remote nodes available for distributed power sweep runs.
# Leave empty to require --hosts/--hosts-file, or populate locally for reuse.
NODES = []

# Default workload assignment and governor order.
DEFAULT_TARGETS = ["hotels", "recommendations", "reservation", "user"]
DEFAULT_GOVERNORS = ["performance", "schedutil"]

# SSH configuration for connecting to experiment nodes.
SSH_USER = os.environ.get("HOTEL_REMOTE_SSH_USER", "")
SSH_KEY_PATH = os.path.expanduser(os.environ.get("HOTEL_REMOTE_SSH_KEY", ""))

# Optional deploy key copied to each node so it can clone/pull this repository.
PRIVATE_KEY_PATH = os.path.expanduser(os.environ.get("HOTEL_REMOTE_GIT_KEY", ""))
REMOTE_KEY_PATH = os.environ.get("HOTEL_REMOTE_GIT_KEY_DEST", "~/.ssh/deathstarbench_deploy_key")

# Repository and artifact layout on the remote hosts.
REPO_ROOT = Path(__file__).resolve().parents[2]
REMOTE_REPO_ROOT = os.environ.get("HOTEL_REMOTE_REPO_ROOT", str(REPO_ROOT))
REMOTE_SCRIPT = "hotelReservation/scripts/run_power_sweep.sh"
CLONE_REPO_URL = os.environ.get(
    "HOTEL_REMOTE_CLONE_REPO_URL",
    os.popen(f"git -C {REPO_ROOT.parent} config --get remote.origin.url 2>/dev/null").read().strip(),
)

# Experiment defaults.
HOST_URL_TEMPLATE = os.environ.get("HOTEL_REMOTE_HOST_URL_TEMPLATE", "http://%h:5000")
THREADS = 2
CONNECTIONS = 2
DURATION_SECONDS = 30
RATES_SPEC = "1000:7000:1000"
POWERSTAT_INTERVAL = 0.5
POWERSTAT_SOURCE = "auto"
SETTLE_SECONDS = 5

# Result locations.
RESULTS_ROOT = REPO_ROOT / "results" / "distributed_power_sweeps"
LOCAL_OUTPUT_DIR = str(RESULTS_ROOT)
REMOTE_OUTPUT_BASE = os.environ.get("HOTEL_REMOTE_OUTPUT_BASE", "")
