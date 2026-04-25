#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import power_sweep_remote_config as cfg
from power_sweep_remote_util import (
    connect,
    expand_remote_path,
    expand_template,
    git_host_from_url,
    run_local_command,
    run_remote_command,
    split_csv,
    split_node,
    trim,
    write_text,
)


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare schedutil and performance governor's power utilization and latency at different loads (QPS) for a specific endpoint.",
    )
    parser.add_argument("--ssh-user", default=cfg.SSH_USER, help="Optional SSH username for running remote commands.")
    parser.add_argument("--ssh-key", default=cfg.SSH_KEY_PATH, help="SSH private key for node access.")
    parser.add_argument("--server-host", help="IP address of the host running the hotel reservation service.")
    parser.add_argument("--target", default="hotels", help="Target from ['hotels', 'recommendations', 'reservation', 'user'].")
    parser.add_argument("--remote-repo-root", default=cfg.REMOTE_REPO_ROOT, help="Remote result root. Default: /tmp/hotelReservation-power-sweeps/<timestamp>.")
    parser.add_argument("--remote-output-base", default=cfg.REMOTE_OUTPUT_BASE, help="Remote result root. Default: /tmp/hotelReservation-power-sweeps/<timestamp>.")
    parser.add_argument("--local-output-dir", help="Local result root. Default: hotelReservation/results/distributed_power_sweeps/<timestamp>.")
    parser.add_argument("--threads", type=int, default=cfg.THREADS)
    parser.add_argument("--connections", type=int, default=cfg.CONNECTIONS)
    parser.add_argument("--duration", type=int, default=cfg.DURATION_SECONDS)
    parser.add_argument("--rates", help="rates given in start:end:step format" default=cfg.RATES_SPEC)
    parser.add_argument("--powerstat-interval", type=float, default=cfg.POWERSTAT_INTERVAL)
    parser.add_argument("--powerstat-source", default=cfg.POWERSTAT_SOURCE, choices=["auto", "rapl", "battery"])
    parser.add_argument("--settle-seconds", type=int, default=cfg.SETTLE_SECONDS)
    parser.add_argument("--paired-start-delay", type=float, default=1.0, help="Delay after starting server power collection before starting the client load.")
    return parser.parse_args()


def run_job(
    node: str,
    ssh_user: str,
    ssh_key: str | None,
    remote_repo_root: str,
    remote_script: str,
    mode: str,
    governor: str,
    target: str,
    frontend_url: str,
    remote_output_dir: str,
    local_job_dir: Path,
    args: argparse.Namespace,
) -> tuple[str, str, int, str, str]:
    default_user, host = split_node(node, ssh_user)
    conn = connect(host, default_user, ssh_key)
    try:
        remote_cmd = [
            "bash",
            f"{expand_remote_path(remote_repo_root)}/{remote_script}",
            "--mode",
            mode,
            "--target",
            target,
            "--governor",
            governor,
            "--host",
            frontend_url,
            "--threads",
            str(args.threads),
            "--connections",
            str(args.connections),
            "--duration",
            str(args.duration),
            "--rates",
            args.rates,
            "--powerstat-interval",
            str(args.powerstat_interval),
            "--powerstat-source",
            args.powerstat_source,
            "--settle-seconds",
            str(args.settle_seconds),
            "--output-dir",
            remote_output_dir,
        ]
        command = shlex.join(remote_cmd)
        exit_code, stdout, stderr = run_remote_command(conn, command, must_succeed=False)
        write_text(local_job_dir / "stdout.log", stdout)
        write_text(local_job_dir / "stderr.log", stderr)
        return host, target, exit_code, stdout, stderr
    finally:
        conn.close()


def main() -> int:
    args = parse_args()
    server_host = args.server_host
    target = args.target

    
    run_id = timestamp()
    local_output_dir = Path(Path(cfg.LOCAL_OUTPUT_DIR) / run_id)
    remote_output_base = f"/tmp/hotelReservation-power-sweeps/{run_id}"
    local_output_dir.mkdir(parents=True, exist_ok=True)

    run_env = "\n".join(
        [
            f"server_host={server_host}",
            f"target={target}",
            f"remote_output_base={remote_output_base}",
            f"threads={args.threads}",
            f"connections={args.connections}",
            f"duration={args.duration}",
            f"rates={args.rates}",
            f"powerstat_interval={args.powerstat_interval}",
            f"powerstat_source={args.powerstat_source}",
            f"settle_seconds={args.settle_seconds}",
        ]
    )
    write_text(local_output_dir / "run.env", run_env + "\n")

    # main experiment loop
    start_rate, end_rate, step = args.rates.split(":")
    for rate in range(int(start_rate), int(end_rate), int(step)):
        # TODO: loop over rates 
        # TODO: log the current rate to the local results dir

            # TODO: loop over governors 
            for governor in cfg.DEFAULT_GOVERNORS:

                phase_dir = local_output_dir / governor
                phase_dir.mkdir(parents=True, exist_ok=True)
                frontend_url = expand_template(args.host_url_template, server_host, target, index)

                with ThreadPoolExecutor(max_workers=2) as pair_executor:
                    server_future = pair_executor.submit(
                        run_job,
                        node=server_node,
                        ssh_user=args.ssh_user,
                        ssh_key=args.ssh_key or None,
                        remote_repo_root=args.remote_repo_root,
                        remote_script=args.remote_script,
                        mode="server-power",
                        governor=governor,
                        target=target,
                        frontend_url=frontend_url,
                        remote_output_dir=server_remote_output,
                        local_job_dir=local_job_dir / "server",
                        args=args,
                    )
                    time.sleep(args.paired_start_delay)
                    client_future = pair_executor.submit(
                        run_job,
                        node=client_node,
                        ssh_user=args.ssh_user,
                        ssh_key=args.ssh_key or None,
                        remote_repo_root=args.remote_repo_root,
                        remote_script=args.remote_script,
                        mode="client",
                        governor="client",
                        target=target,
                        frontend_url=frontend_url,
                        remote_output_dir=client_remote_output,
                        local_job_dir=local_job_dir / "client",
                        args=args,
                    )
                    server_result = server_future.result()
                    client_result = client_future.result()

                if server_result[2] != 0 or client_result[2] != 0:
                    failures += 1
                    write_text(
                        local_job_dir / "status.log",
                        f"status=failed\nserver_exit={server_result[2]}\nclient_exit={client_result[2]}\n",
                    )
                    continue
                # TODO: stop all services and then restart them before the next experiment


    return 0


if __name__ == "__main__":
    raise SystemExit(main())
