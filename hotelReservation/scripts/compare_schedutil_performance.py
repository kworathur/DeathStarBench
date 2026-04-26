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
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

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


def _powerstat_min_count(source: str) -> int:
    """Mirror run_power_sweep.sh powerstat_min_count."""
    return 120 if source == "rapl" else 600


def _detect_powerstat_source(source_arg: str) -> str:
    """Mirror run_power_sweep.sh detect_powerstat_source for the local machine."""
    if source_arg in ("rapl", "battery"):
        return source_arg
    # auto: prefer RAPL if available
    return "rapl" if Path("/sys/class/powercap/intel-rapl").is_dir() else "battery"


def compute_effective_duration(
    powerstat_interval: float,
    powerstat_source_arg: str,
) -> int:
    """Return the measurement window that run_power_sweep.sh will use.

    Duration is derived entirely from the powerstat parameters: the minimum
    sample count for the chosen source divided by the sampling interval.
    There is no separate --duration knob; this is the single source of truth.
    """
    import math

    source = _detect_powerstat_source(powerstat_source_arg)
    count = _powerstat_min_count(source)
    effective = count * powerstat_interval
    return int(math.ceil(effective))


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
    duration: int,
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
        "--duration", str(duration),
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


def fetch_remote_logs(
    host: str,
    ssh_user: str,
    ssh_key: str | None,
    remote_log_dir: str,
    local_dest: Path,
) -> None:
    """Copy all files from a remote logs/ directory into local_dest via SFTP."""
    _, resolved_host = split_node(host, ssh_user)
    conn = connect(resolved_host, ssh_user, ssh_key)
    try:
        sftp = conn.open_sftp()
        try:
            try:
                entries = sftp.listdir(remote_log_dir)
            except FileNotFoundError:
                return
            local_dest.mkdir(parents=True, exist_ok=True)
            for name in entries:
                remote_file = f"{remote_log_dir}/{name}"
                local_file = local_dest / name
                with sftp.open(remote_file, "rb") as rfh:
                    local_file.write_bytes(rfh.read())
        finally:
            sftp.close()
    finally:
        conn.close()


def copy_local_logs(src_log_dir: Path, local_dest: Path) -> None:
    """Copy all files from src_log_dir into local_dest."""
    if not src_log_dir.is_dir():
        return
    local_dest.mkdir(parents=True, exist_ok=True)
    for entry in src_log_dir.iterdir():
        if entry.is_file():
            shutil.copy2(entry, local_dest / entry.name)


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


def _parse_float(row: dict, key: str) -> float | None:
    val = row.get(key, "NA")
    if val in ("NA", "", None):
        return None
    try:
        return float(val)
    except ValueError:
        return None


def plot_throughput_comparison(path: Path, rows: list[dict]) -> None:
    """Plot target arrival rate vs actual throughput, one line per governor.

    A dashed identity line (actual == target) is included as a reference,
    matching the style of avgload_vs_throughput.png from plot_qps_metrics.py.
    """
    import matplotlib.pyplot as plt

    by_governor: dict[str, list[dict]] = {}
    for row in rows:
        if _parse_float(row, "arrival_rate_rps") is None:
            continue
        if _parse_float(row, "requests_sec") is None:
            continue
        by_governor.setdefault(row["governor"], []).append(row)

    if not by_governor:
        return

    colours = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    gov_colour = {gov: colours[i % len(colours)] for i, gov in enumerate(sorted(by_governor))}

    fig, ax = plt.subplots(figsize=(9, 5.5))

    all_targets: list[float] = []
    for gov, gov_rows in sorted(by_governor.items()):
        gov_rows = sorted(gov_rows, key=lambda r: float(r["arrival_rate_rps"]))
        x = [float(r["arrival_rate_rps"]) for r in gov_rows]
        y = [float(r["requests_sec"]) for r in gov_rows]
        all_targets.extend(x)
        ax.plot(x, y, marker="o", linewidth=2, color=gov_colour[gov], label=gov)

    # Identity reference line: actual == target
    if all_targets:
        lo, hi = min(all_targets), max(all_targets)
        ax.plot([lo, hi], [lo, hi], linestyle="--", color="grey", linewidth=1.5, label="target (ideal)")

    ax.set_xlabel("Target Arrival Rate (RPS)")
    ax.set_ylabel("Actual Throughput (RPS)")
    ax.set_title("Target vs Actual Throughput by Governor")
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def plot_latency_comparison(path: Path, rows: list[dict]) -> None:
    """Plot arrival rate vs P50 and P99 latency in separate subplots.

    Each subplot shows one line per governor for that percentile.
    Data is filtered to exclude points where P99 exceeds 20× the minimum P50.
    """
    import matplotlib.pyplot as plt

    # Group rows by governor, keeping only rows with P50 and P99 data.
    _LATENCY_COLS = ("p50_ms", "p99_ms")
    by_governor: dict[str, list[dict]] = {}
    for row in rows:
        if _parse_float(row, "arrival_rate_rps") is None:
            continue
        if any(_parse_float(row, c) is None for c in _LATENCY_COLS):
            continue
        gov = row["governor"]
        by_governor.setdefault(gov, []).append(row)

    if not by_governor:
        return

    # Find the minimum P50 across all governors and rates.
    all_p50 = [
        float(r["p50_ms"])
        for gov_rows in by_governor.values()
        for r in gov_rows
    ]
    if not all_p50:
        return
    min_p50 = min(all_p50)
    cutoff_p99 = 20 * min_p50

    # Filter rows: keep only those where P99 <= cutoff.
    filtered_by_governor: dict[str, list[dict]] = {}
    for gov, gov_rows in by_governor.items():
        filtered = [r for r in gov_rows if float(r["p99_ms"]) <= cutoff_p99]
        if filtered:
            filtered_by_governor[gov] = filtered

    if not filtered_by_governor:
        return

    # Assign a colour per governor.
    colours = plt.rcParams["axes.prop_cycle"].by_key()["color"]
    gov_colour = {gov: colours[i % len(colours)] for i, gov in enumerate(sorted(filtered_by_governor))}

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 5.5))

    # P50 subplot
    for gov, gov_rows in sorted(filtered_by_governor.items()):
        gov_rows = sorted(gov_rows, key=lambda r: float(r["arrival_rate_rps"]))
        x = [float(r["arrival_rate_rps"]) for r in gov_rows]
        y = [float(r["p50_ms"]) for r in gov_rows]
        ax1.plot(x, y, marker="o", linewidth=2, color=gov_colour[gov], label=gov)

    ax1.set_xlabel("Arrival Rate (RPS)")
    ax1.set_ylabel("P50 Latency (ms)")
    ax1.set_title("Arrival Rate vs P50 Latency by Governor")
    ax1.grid(True, linestyle="--", alpha=0.5)
    ax1.legend()

    # P99 subplot
    for gov, gov_rows in sorted(filtered_by_governor.items()):
        gov_rows = sorted(gov_rows, key=lambda r: float(r["arrival_rate_rps"]))
        x = [float(r["arrival_rate_rps"]) for r in gov_rows]
        y = [float(r["p99_ms"]) for r in gov_rows]
        ax2.plot(x, y, marker="o", linewidth=2, color=gov_colour[gov], label=gov)

    ax2.set_xlabel("Arrival Rate (RPS)")
    ax2.set_ylabel("P99 Latency (ms)")
    ax2.set_title(f"Arrival Rate vs P99 Latency by Governor (cutoff: {cutoff_p99:.1f}ms)")
    ax2.grid(True, linestyle="--", alpha=0.5)
    ax2.legend()

    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main() -> int:
    args = parse_args()
    server_host = args.server_host
    target = args.target
    remote = not is_localhost(server_host)

    rates = expand_rates(args.rates)

    # Duration is derived entirely from the powerstat parameters so that the
    # wrk2 load window always matches the power measurement window exactly.
    # wrk2's -d flag includes calibration/warmup time (~8-10s), so the actual
    # load generation is shorter than the specified duration. We add a +10s
    # buffer to ensure wrk2's load generation covers the full powerstat window.
    effective_duration = compute_effective_duration(
        args.powerstat_interval, args.powerstat_source
    )
    client_duration = effective_duration + 10
    print(f"Measurement duration: {effective_duration}s "
          f"({_powerstat_min_count(_detect_powerstat_source(args.powerstat_source))} samples "
          f"× {args.powerstat_interval}s)")
    print(f"Client load duration: {client_duration}s (server + 10s buffer for wrk2 warmup)")

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
        f"effective_duration={effective_duration}",
        f"client_duration={client_duration}",
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

    for rate in rates:
        rate_dir = local_output_dir / f"rate_{rate}"
        write_text(rate_dir / "rate.txt", f"rate={rate}\n")
        print(f"\n=== Rate {rate} rps ===")

        for governor in cfg.DEFAULT_GOVERNORS:
            print(f"  Governor: {governor}")
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
                duration=effective_duration,
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
                duration=client_duration,
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

            if not status_ok:
                failures += 1
                print(
                    f"    FAILED: server_exit={server_exit} client_exit={client_exit}",
                    file=sys.stderr,
                )
                if server_stderr.strip():
                    print(f"    server stderr: {server_stderr.strip()}", file=sys.stderr)
                if client_stderr.strip():
                    print(f"    client stderr: {client_stderr.strip()}", file=sys.stderr)
                continue

            # Collect server CSV rows
            server_csv_path = f"{server_remote_output}/results.csv"
            if remote:
                server_csv_text = fetch_remote_csv(
                    host=server_host,
                    ssh_user=args.ssh_user,
                    ssh_key=args.ssh_key or None,
                    remote_path=server_csv_path,
                )
                # Fetch powerstat logs from the remote server for debugging
                fetch_remote_logs(
                    host=server_host,
                    ssh_user=args.ssh_user,
                    ssh_key=args.ssh_key or None,
                    remote_log_dir=f"{server_remote_output}/logs",
                    local_dest=server_log_dir / "logs",
                )
            else:
                server_csv_text = Path(server_csv_path).read_text(encoding="utf-8")
                # Copy powerstat logs from the local server output for debugging
                copy_local_logs(
                    Path(server_remote_output) / "logs",
                    server_log_dir / "logs",
                )
            all_server_rows.extend(parse_csv_rows(server_csv_text))

            # Collect client CSV rows (always local).
            # run_power_sweep.sh sets governor="client" in client mode, so
            # override it with the actual governor so the merge key matches.
            client_csv_path = Path(client_remote_output) / "results.csv"
            client_rows = parse_csv_rows(client_csv_path.read_text(encoding="utf-8"))
            for row in client_rows:
                row["governor"] = governor
            all_client_rows.extend(client_rows)
            # Copy wrk2 logs from the local client output for debugging
            copy_local_logs(
                Path(client_remote_output) / "logs",
                client_log_dir / "logs",
            )

    # Merge and write the combined CSV
    merged = merge_rows(all_server_rows, all_client_rows)
    merged_csv_path = local_output_dir / "results.csv"
    write_merged_csv(merged_csv_path, merged)
    print(f"\nMerged results CSV: {merged_csv_path}")

    # Generate plots from the merged results.
    # plot_power_sweep.py requires numeric values in all rows, so filter to
    # rows where both power and latency data are present.
    _NUMERIC_PLOT_COLS = {"requests_sec", "avg_power_watts"}
    plottable = [
        r for r in merged
        if all(r.get(c, "NA") not in ("NA", "", None) for c in _NUMERIC_PLOT_COLS)
    ]
    if plottable:
        plot_csv_path = local_output_dir / "results_plottable.csv"
        write_merged_csv(plot_csv_path, plottable)
        plot_path = local_output_dir / "arrival_rate_vs_power.png"
        plot_script = SCRIPT_DIR / "plot_power_sweep.py"
        plot_result = subprocess.run(
            [sys.executable, str(plot_script), "--input", str(plot_csv_path), "--output", str(plot_path)],
            text=True,
            capture_output=True,
            check=False,
        )
        if plot_result.returncode == 0:
            print(f"Plot saved: {plot_path}")
        else:
            print(f"Warning: plot_power_sweep.py failed:\n{plot_result.stderr.strip()}", file=sys.stderr)
    else:
        print("No fully-merged rows available for plotting (missing power or latency data).", file=sys.stderr)

    # Arrival rate vs latency comparison plot (one series per governor per percentile).
    latency_plot_path = local_output_dir / "arrival_rate_vs_latency.png"
    try:
        plot_latency_comparison(latency_plot_path, merged)
        print(f"Plot saved: {latency_plot_path}")
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: latency plot failed: {exc}", file=sys.stderr)

    # Target vs actual throughput plot (one series per governor).
    throughput_plot_path = local_output_dir / "arrival_rate_vs_throughput.png"
    try:
        plot_throughput_comparison(throughput_plot_path, merged)
        print(f"Plot saved: {throughput_plot_path}")
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: throughput plot failed: {exc}", file=sys.stderr)

    if failures:
        print(f"\nWarning: {failures} job(s) failed. See status.log files under {local_output_dir}.")

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
