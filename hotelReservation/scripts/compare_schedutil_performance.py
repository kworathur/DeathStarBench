#!/usr/bin/env python3
"""Compare schedutil vs performance governor power and latency across QPS rates.

For each rate in the sweep and each governor, this script runs run_power_sweep.sh
in 'server-power' mode on the server host and 'client' mode on localhost in
parallel. If the server is remote, results are copied back via SCP and merged
with the client results into a single CSV compatible with plot_power_sweep.py.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from tqdm import tqdm

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import compare_schedutil_performance_config as cfg
from compare_schedutil_performance_util import (
    connect,
    expand_remote_path,
    expand_template,
    run_local_command,
    run_remote_command,
    split_node,
    write_text,
)

# CSV columns produced by run_power_sweep.sh
_CSV_COLS = [
    "target",
    "governor",
    "arrival_rate_rps",
    "requests_sec",
    "avg_power_watts",
    "latency_avg_ms",
    "latency_stdev_ms",
    "latency_max_ms",
    "p50_ms",
    "p90_ms",
    "p95_ms",
    "p99_ms",
    "wrk_output",
    "powerstat_output",
]

# Columns contributed by each mode
_POWER_COLS = {"avg_power_watts", "powerstat_output"}
_CLIENT_COLS = {
    "requests_sec",
    "latency_avg_ms",
    "latency_stdev_ms",
    "latency_max_ms",
    "p50_ms",
    "p90_ms",
    "p95_ms",
    "p99_ms",
    "wrk_output",
}


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def is_localhost(host: str) -> bool:
    return host in ("localhost", "127.0.0.1", "::1")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare schedutil and performance governor power utilization and "
            "latency at different QPS rates for a specific hotelReservation endpoint."
        ),
    )
    parser.add_argument(
        "--ssh-user",
        default=cfg.SSH_USER,
        help="SSH username for remote commands.",
    )
    parser.add_argument(
        "--ssh-key",
        default=cfg.SSH_KEY_PATH,
        help="SSH private key path for node access.",
    )
    parser.add_argument(
        "--server-host",
        default="localhost",
        help="Host running the hotel reservation service. Default: localhost.",
    )
    parser.add_argument(
        "--target",
        default="hotels",
        choices=cfg.DEFAULT_TARGETS,
        help="Endpoint target to benchmark.",
    )
    parser.add_argument(
        "--remote-repo-root",
        default=cfg.REMOTE_REPO_ROOT,
        help="Path to the repo root on the remote host.",
    )
    parser.add_argument(
        "--remote-output-base",
        default=cfg.REMOTE_OUTPUT_BASE,
        help="Base directory for results on the remote host.",
    )
    parser.add_argument(
        "--local-output-dir",
        default=None,
        help="Local directory for results. Default: results/distributed_power_sweeps/<timestamp>.",
    )
    parser.add_argument("--threads", type=int, default=cfg.THREADS)
    parser.add_argument("--connections", type=int, default=cfg.CONNECTIONS)
    parser.add_argument("--duration", type=int, default=cfg.DURATION_SECONDS)
    parser.add_argument(
        "--rates",
        default=cfg.RATES_SPEC,
        help="Rate sweep as start:end:step (inclusive end). Example: 1000:5000:1000.",
    )
    parser.add_argument(
        "--powerstat-interval",
        type=float,
        default=cfg.POWERSTAT_INTERVAL,
    )
    parser.add_argument(
        "--powerstat-source",
        default=cfg.POWERSTAT_SOURCE,
        choices=["auto", "rapl", "battery"],
    )
    return parser.parse_args()


def expand_rates(spec: str) -> list[int]:
    """Parse start:end:step (inclusive end) into a list of integer rates."""
    parts = spec.split(":")
    if len(parts) != 3:
        raise ValueError(f"--rates must be start:end:step, got: {spec!r}")
    start, end, step = int(parts[0]), int(parts[1]), int(parts[2])
    if step <= 0:
        raise ValueError("rate step must be > 0")
    return list(range(start, end + 1, step))


def build_sweep_cmd(
    repo_root: str,
    mode: str,
    governor: str,
    target: str,
    host_url: str,
    rate: int,
    output_dir: str,
    args: argparse.Namespace,
) -> list[str]:
    """Build the argument list for run_power_sweep.sh."""
    script = f"{expand_remote_path(repo_root)}/{cfg.REMOTE_SCRIPT}"
    cmd = [
        "bash", script,
        "--mode", mode,
        "--target", target,
        "--governor", governor,
        "--host", host_url,
        "--threads", str(args.threads),
        "--connections", str(args.connections),
        "--duration", str(args.duration),
        "--rates", str(rate),
        "--powerstat-interval", str(args.powerstat_interval),
        "--powerstat-source", args.powerstat_source,
        "--settle-seconds", str(cfg.SETTLE_SECONDS),
        "--output-dir", output_dir,
    ]
    return cmd


def run_remote_job(
    host: str,
    ssh_user: str,
    ssh_key: str | None,
    cmd: list[str],
    local_log_dir: Path,
) -> tuple[int, str, str]:
    """Run a command on a remote host via SSH."""
    _, resolved_host = split_node(host, ssh_user)
    conn = connect(resolved_host, ssh_user, ssh_key)
    try:
        exit_code, stdout, stderr = run_remote_command(
            conn, shlex.join(cmd), must_succeed=False
        )
    finally:
        conn.close()
    write_text(local_log_dir / "stdout.log", stdout)
    write_text(local_log_dir / "stderr.log", stderr)
    return exit_code, stdout, stderr


def run_local_job(
    cmd: list[str],
    local_log_dir: Path,
) -> tuple[int, str, str]:
    """Run a command on localhost via subprocess."""
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    write_text(local_log_dir / "stdout.log", result.stdout)
    write_text(local_log_dir / "stderr.log", result.stderr)
    return result.returncode, result.stdout, result.stderr


def fetch_remote_csv(
    host: str,
    ssh_user: str,
    ssh_key: str | None,
    remote_path: str,
) -> str:
    """Return the contents of a remote CSV file as a string."""
    _, resolved_host = split_node(host, ssh_user)
    conn = connect(resolved_host, ssh_user, ssh_key)
    try:
        sftp = conn.open_sftp()
        try:
            with sftp.open(remote_path, "r") as fh:
                return fh.read().decode("utf-8", "ignore")
        finally:
            sftp.close()
    finally:
        conn.close()


def parse_csv_rows(text: str) -> list[dict]:
    """Parse CSV text (with header) into a list of dicts."""
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)


def merge_rows(
    server_rows: list[dict],
    client_rows: list[dict],
) -> list[dict]:
    """Merge server-power rows and client rows by (governor, arrival_rate_rps).

    The server contributes power columns; the client contributes latency/rps
    columns. Rows present in only one side are included with NA for missing
    columns.
    """
    # Index client rows by (governor, rate)
    client_index: dict[tuple[str, str], dict] = {}
    for row in client_rows:
        key = (row["governor"], row["arrival_rate_rps"])
        client_index[key] = row

    merged: list[dict] = []
    for srow in server_rows:
        key = (srow["governor"], srow["arrival_rate_rps"])
        crow = client_index.pop(key, {})
        out = dict(srow)  # start from server row (has power + identity cols)
        for col in _CLIENT_COLS:
            out[col] = crow.get(col, "NA")
        merged.append(out)

    # Any client rows with no matching server row
    for crow in client_index.values():
        out = dict(crow)
        for col in _POWER_COLS:
            out[col] = "NA"
        merged.append(out)

    # Sort by governor then rate for readability
    merged.sort(key=lambda r: (r["governor"], float(r["arrival_rate_rps"])))
    return merged


def write_merged_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_COLS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    server_host = args.server_host
    target = args.target
    remote = not is_localhost(server_host)

    rates = expand_rates(args.rates)

    run_id = timestamp()
    local_output_dir = Path(
        args.local_output_dir if args.local_output_dir else cfg.LOCAL_OUTPUT_DIR
    ) / run_id
    local_output_dir.mkdir(parents=True, exist_ok=True)

    # Remote output base for this run
    remote_output_base = (
        args.remote_output_base.rstrip("/")
        if args.remote_output_base
        else f"/tmp/hotelReservation-power-sweeps/{run_id}"
    )

    # Resolve the frontend URL from the config template
    host_url = expand_template(cfg.HOST_URL, server_host, target, 0)

    # Log run parameters
    run_env_lines = [
        f"run_id={run_id}",
        f"server_host={server_host}",
        f"remote={remote}",
        f"target={target}",
        f"host_url={host_url}",
        f"remote_output_base={remote_output_base}",
        f"threads={args.threads}",
        f"connections={args.connections}",
        f"duration={args.duration}",
        f"rates={args.rates}",
        f"powerstat_interval={args.powerstat_interval}",
        f"powerstat_source={args.powerstat_source}",
        f"governors={','.join(cfg.DEFAULT_GOVERNORS)}",
    ]
    write_text(local_output_dir / "run.env", "\n".join(run_env_lines) + "\n")
    print(f"Run ID: {run_id}")
    print(f"Local output: {local_output_dir}")

    failures = 0
    all_server_rows: list[dict] = []
    all_client_rows: list[dict] = []

    total_trials = len(rates) * len(cfg.DEFAULT_GOVERNORS)
    trial_bar = tqdm(
        total=total_trials,
        desc="Trials",
        unit="trial",
        dynamic_ncols=True,
    )

    rate_bar = tqdm(
        rates,
        desc="Rates",
        unit="rate",
        dynamic_ncols=True,
        leave=True,
    )

    for rate in rate_bar:
        rate_bar.set_description(f"Rate {rate} rps")
        rate_dir = local_output_dir / f"rate_{rate}"
        write_text(rate_dir / "rate.txt", f"rate={rate}\n")

        gov_bar = tqdm(
            cfg.DEFAULT_GOVERNORS,
            desc="Governors",
            unit="gov",
            dynamic_ncols=True,
            leave=False,
        )

        for governor in gov_bar:
            gov_bar.set_description(f"{governor} @ {rate} rps")
            trial_bar.set_description(f"Running {governor} @ {rate} rps")

            job_dir = rate_dir / governor
            server_log_dir = job_dir / "server"
            client_log_dir = job_dir / "client"

            server_remote_output = f"{remote_output_base}/{rate}/{governor}/server"
            client_remote_output = f"{remote_output_base}/{rate}/{governor}/client"

            server_cmd = build_sweep_cmd(
                repo_root=args.remote_repo_root,
                mode="server-power",
                governor=governor,
                target=target,
                host_url=host_url,
                rate=rate,
                output_dir=server_remote_output,
                args=args,
            )
            client_cmd = build_sweep_cmd(
                repo_root=str(cfg.REPO_ROOT),
                mode="client",
                governor=governor,
                target=target,
                host_url=host_url,
                rate=rate,
                output_dir=client_remote_output,
                args=args,
            )

            # Run server and client in parallel
            with ThreadPoolExecutor(max_workers=2) as executor:
                if remote:
                    server_future = executor.submit(
                        run_remote_job,
                        host=server_host,
                        ssh_user=args.ssh_user,
                        ssh_key=args.ssh_key or None,
                        cmd=server_cmd,
                        local_log_dir=server_log_dir,
                    )
                else:
                    server_future = executor.submit(
                        run_local_job,
                        cmd=server_cmd,
                        local_log_dir=server_log_dir,
                    )
                client_future = executor.submit(
                    run_local_job,
                    cmd=client_cmd,
                    local_log_dir=client_log_dir,
                )
                server_exit, _, server_stderr = server_future.result()
                client_exit, _, client_stderr = client_future.result()

            status_ok = server_exit == 0 and client_exit == 0
            write_text(
                job_dir / "status.log",
                f"status={'ok' if status_ok else 'failed'}\n"
                f"server_exit={server_exit}\nclient_exit={client_exit}\n",
            )

            trial_bar.update(1)

            if not status_ok:
                failures += 1
                trial_bar.set_description(
                    f"FAILED {governor} @ {rate} rps "
                    f"(server={server_exit}, client={client_exit})"
                )
                tqdm.write(
                    f"FAILED {governor} @ {rate} rps: "
                    f"server_exit={server_exit} client_exit={client_exit}",
                    file=sys.stderr,
                )
                if server_stderr.strip():
                    tqdm.write(f"  server stderr: {server_stderr.strip()}", file=sys.stderr)
                if client_stderr.strip():
                    tqdm.write(f"  client stderr: {client_stderr.strip()}", file=sys.stderr)
                continue

            trial_bar.set_description(f"OK {governor} @ {rate} rps")

            # Collect server CSV rows
            server_csv_path = f"{server_remote_output}/results.csv"
            if remote:
                server_csv_text = fetch_remote_csv(
                    host=server_host,
                    ssh_user=args.ssh_user,
                    ssh_key=args.ssh_key or None,
                    remote_path=server_csv_path,
                )
            else:
                server_csv_text = Path(server_csv_path).read_text(encoding="utf-8")
            all_server_rows.extend(parse_csv_rows(server_csv_text))

            # Collect client CSV rows (always local)
            client_csv_path = Path(client_remote_output) / "results.csv"
            all_client_rows.extend(
                parse_csv_rows(client_csv_path.read_text(encoding="utf-8"))
            )

        gov_bar.close()

    rate_bar.close()
    trial_bar.close()

    # Merge and write the combined CSV
    merged = merge_rows(all_server_rows, all_client_rows)
    merged_csv_path = local_output_dir / "results.csv"
    write_merged_csv(merged_csv_path, merged)
    print(f"\nMerged results CSV: {merged_csv_path}")

    if failures:
        print(f"\nWarning: {failures} job(s) failed. See status.log files under {local_output_dir}.")

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
