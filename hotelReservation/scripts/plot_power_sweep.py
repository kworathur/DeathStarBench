#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import os
import re
import tempfile
from collections import defaultdict
from pathlib import Path


NUMBER_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(us|ms|s)?\s*$", re.IGNORECASE)


def parse_numeric(value: str | None) -> float | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw or raw.upper() == "NA":
        return None
    match = NUMBER_RE.match(raw)
    if not match:
        try:
            return float(raw.replace(",", ""))
        except ValueError:
            return None
    magnitude = float(match.group(1))
    unit = (match.group(2) or "").lower()
    if unit == "us":
        return magnitude / 1000.0
    if unit == "s":
        return magnitude * 1000.0
    return magnitude


def load_rows(path: Path) -> list[dict[str, str | float]]:
    rows: list[dict[str, str | float]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            normalized: dict[str, str | float] = dict(row)
            for key, value in list(row.items()):
                parsed = parse_numeric(value)
                if parsed is not None:
                    normalized[key] = parsed
            rows.append(normalized)
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot one numeric metric from a sweep CSV.")
    parser.add_argument("--input", required=True, help="CSV produced by a sweep or merge script.")
    parser.add_argument("--output", required=True, help="Output PNG path.")
    parser.add_argument("--title", default=None, help="Optional plot title.")
    parser.add_argument("--x-column", default="requests_sec", help="Numeric CSV column for the x axis.")
    parser.add_argument("--y-column", default="avg_power_watts", help="Numeric CSV column for the y axis.")
    parser.add_argument("--group-column", default="governor", help="Column used for line grouping.")
    return parser.parse_args()


def main() -> None:
    if "MPLCONFIGDIR" not in os.environ:
        os.environ["MPLCONFIGDIR"] = tempfile.mkdtemp(prefix="matplotlib-")
    args = parse_args()
    rows = load_rows(Path(args.input))

    import matplotlib.pyplot as plt

    grouped: dict[str, list[dict[str, str | float]]] = defaultdict(list)
    for row in rows:
        x_value = row.get(args.x_column)
        y_value = row.get(args.y_column)
        if not isinstance(x_value, (float, int)) or not isinstance(y_value, (float, int)):
            continue
        group = str(row.get(args.group_column, "default") or "default")
        grouped[group].append(row)

    if not grouped:
        raise SystemExit(f"no plottable rows found for x={args.x_column} y={args.y_column}")

    plt.figure(figsize=(9, 5.5))
    for group_name, group_rows in sorted(grouped.items()):
        ordered = sorted(group_rows, key=lambda row: float(row[args.x_column]))
        x_values = [float(row[args.x_column]) for row in ordered]
        y_values = [float(row[args.y_column]) for row in ordered]
        plt.plot(x_values, y_values, marker="o", linewidth=2, label=group_name)

    plt.xlabel(args.x_column)
    plt.ylabel(args.y_column)
    plt.title(args.title or f"{args.y_column} vs {args.x_column}")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(args.output, dpi=200)


if __name__ == "__main__":
    main()
