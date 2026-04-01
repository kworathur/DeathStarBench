#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
from pathlib import Path

import matplotlib.pyplot as plt

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from parse_wrk_metrics import parse_wrk_log


def read_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def parse_float(row: dict[str, str], key: str) -> float | None:
    value = row.get(key, "").strip()
    if not value or value == "NA":
        return None
    return float(value)


def ensure_metrics(row: dict[str, str]) -> dict[str, float | None]:
    metrics = {
        "arrival_rate_rps": parse_float(row, "arrival_rate_rps"),
        "requests_sec": parse_float(row, "requests_sec"),
        "latency_avg_ms": parse_float(row, "latency_avg_ms"),
        "p50_ms": parse_float(row, "p50_ms"),
        "p90_ms": parse_float(row, "p90_ms"),
        "p95_ms": parse_float(row, "p95_ms"),
        "p99_ms": parse_float(row, "p99_ms"),
    }

    wrk_output = Path(row["wrk_output"])
    if any(value is None for key, value in metrics.items() if key != "arrival_rate_rps"):
        parsed = parse_wrk_log(wrk_output)
        for key in ("requests_sec", "latency_avg_ms", "p50_ms", "p90_ms", "p95_ms", "p99_ms"):
            if metrics[key] is None:
                metrics[key] = parsed[key]
    return metrics


def write_client_log(path: Path, metrics: dict[str, float | None]) -> None:
    lines = [
        f"Observed duration: unknown s, Actual QPS: {metrics['requests_sec']:.6f}",
        f"Avg: {metrics['latency_avg_ms']:.6f} ms",
        f"P50: {metrics['p50_ms']:.6f} ms",
        f"P90: {metrics['p90_ms']:.6f} ms",
        f"P95: {metrics['p95_ms']:.6f} ms",
        f"P99.000: {metrics['p99_ms']:.6f} ms",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def plot_combined_latency(out_path: Path, rows: list[dict[str, float]]) -> None:
    rows = sorted(rows, key=lambda row: row["arrival_rate_rps"])
    plt.figure(figsize=(9, 5.5))
    for key, label in (
        ("p50_ms", "P50"),
        ("p90_ms", "P90"),
        ("p95_ms", "P95"),
        ("p99_ms", "P99"),
    ):
        plt.plot(
            [row["arrival_rate_rps"] for row in rows],
            [row[key] for row in rows],
            marker="o",
            linewidth=2,
            label=label,
        )
    plt.xlabel("Average Load (QPS)")
    plt.ylabel("Latency (ms)")
    plt.title("Average Load vs Latency")
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=200)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert hotelReservation sweep results into the layout expected by plot_qps_metrics.py.",
    )
    parser.add_argument("--input-dir", required=True, help="Sweep output directory containing results.csv")
    parser.add_argument("--output-dir", help="Reference-style run dir. Default: <input-dir>/reference_run")
    parser.add_argument("--reference-script", help="Optional path to plot_qps_metrics.py")
    parser.add_argument("--plots-dir", help="Optional output dir for generated PNGs. Default: <output-dir>")
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    csv_path = input_dir / "results.csv"
    if not csv_path.is_file():
        raise FileNotFoundError(f"results.csv not found under {input_dir}")

    output_dir = Path(args.output_dir).resolve() if args.output_dir else input_dir / "reference_run"
    plots_dir = Path(args.plots_dir).resolve() if args.plots_dir else output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    converted_rows: list[dict[str, float]] = []
    for row in read_rows(csv_path):
        metrics = ensure_metrics(row)
        if metrics["arrival_rate_rps"] is None:
            continue
        for key in ("requests_sec", "latency_avg_ms", "p50_ms", "p90_ms", "p95_ms", "p99_ms"):
            if metrics[key] is None:
                raise ValueError(f"Missing required metric '{key}' for rate {row.get('arrival_rate_rps')}")

        qps_label = row["arrival_rate_rps"].strip()
        qps_dir = output_dir / f"qps_{qps_label}"
        client_dir = qps_dir / "client"
        server_dir = qps_dir / "server_1"
        client_dir.mkdir(parents=True, exist_ok=True)
        server_dir.mkdir(parents=True, exist_ok=True)

        write_client_log(client_dir / "client.log", metrics)
        shutil.copy2(Path(row["wrk_output"]), client_dir / "wrk.log")

        power_key = "powerstat_output" if "powerstat_output" in row else None
        if power_key and row.get(power_key):
            shutil.copy2(Path(row[power_key]), server_dir / f"powerstat_1_qps_{qps_label}.log")

        converted_rows.append({key: float(metrics[key]) for key in metrics})

    if not converted_rows:
        raise ValueError(f"No rows converted from {csv_path}")

    plot_combined_latency(plots_dir / "qps_vs_latency.png", converted_rows)

    if args.reference_script:
        reference_script = Path(args.reference_script).resolve()
        subprocess.run(
            [sys.executable, str(reference_script), "--run-dir", str(output_dir), "--out-dir", str(plots_dir)],
            check=True,
        )

        throughput_src = plots_dir / "avgload_vs_throughput.png"
        if throughput_src.exists():
            shutil.copy2(throughput_src, plots_dir / "qps_vs_actual_qps.png")

        power_src = plots_dir / "avgload_vs_power.png"
        if power_src.exists():
            shutil.copy2(power_src, plots_dir / "qps_vs_power.png")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
