#!/usr/bin/env python3

import argparse
import csv
from collections import defaultdict


def load_rows(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            row["arrival_rate_rps"] = float(row["arrival_rate_rps"])
            row["requests_sec"] = float(row["requests_sec"])
            row["avg_power_watts"] = float(row["avg_power_watts"])
            rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(
        description="Plot arrival rate vs. average power for hotelReservation sweeps."
    )
    parser.add_argument("--input", required=True, help="CSV file produced by run_power_sweep.sh")
    parser.add_argument("--output", required=True, help="Output PNG path")
    parser.add_argument("--title", default=None, help="Optional plot title")
    args = parser.parse_args()

    import matplotlib.pyplot as plt

    rows = load_rows(args.input)
    grouped = defaultdict(list)
    target = None
    for row in rows:
        grouped[row["governor"]].append(row)
        target = row["target"]

    plt.figure(figsize=(9, 5.5))
    all_x_values = []
    all_y_values = []
    for governor, governor_rows in sorted(grouped.items()):
        governor_rows.sort(key=lambda row: row["requests_sec"])
        x_values = [row["requests_sec"] for row in governor_rows]
        y_values = [row["avg_power_watts"] for row in governor_rows]
        all_x_values.extend(x_values)
        all_y_values.extend(y_values)
        plt.plot(x_values, y_values, marker="o", linewidth=2, label=governor)

    if len(all_x_values) >= 2:
        paired = sorted(zip(all_x_values, all_y_values), key=lambda pair: pair[0])
        x_ref = [paired[0][0], paired[-1][0]]
        y_ref = [paired[0][1], paired[-1][1]]
        plt.plot(x_ref, y_ref, linestyle="--", color="grey", linewidth=1.5, label="linear ref")

    governor_names = ", ".join(sorted(grouped.keys()))
    title = args.title or f"Arrival Rate vs Power Consumption ({target}, {governor_names})"
    plt.title(title)
    plt.xlabel("Average Load (QPS)")
    plt.ylabel("Average power (watts)")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(args.output, dpi=200)


if __name__ == "__main__":
    main()
