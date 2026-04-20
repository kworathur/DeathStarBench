#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def as_float(row: dict[str, str], key: str) -> float | None:
    raw = row.get(key, "").strip()
    if not raw or raw.upper() == "NA":
        return None
    return float(raw)


def index_rows(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    return {(row.get("target", ""), row.get("arrival_rate_rps", "")): row for row in rows}


def fmt_delta(current: float | None, reference: float | None) -> str:
    if current is None or reference in (None, 0.0):
        return ""
    return f"{((current - reference) / reference) * 100.0:.1f}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare a reproduced sweep against a reference merged CSV.")
    parser.add_argument("--current", required=True, help="Merged CSV from the current run.")
    parser.add_argument("--reference", required=True, help="Merged CSV from the reference run.")
    parser.add_argument("--output", required=True, help="Output CSV path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    current_rows = index_rows(load_rows(Path(args.current)))
    reference_rows = index_rows(load_rows(Path(args.reference)))
    keys = sorted(set(current_rows) & set(reference_rows), key=lambda item: (item[0], float(item[1])))

    fieldnames = [
        "target",
        "arrival_rate_rps",
        "current_requests_sec",
        "reference_requests_sec",
        "requests_sec_delta_pct",
        "current_avg_power_watts",
        "reference_avg_power_watts",
        "avg_power_delta_pct",
        "current_p50_ms",
        "reference_p50_ms",
        "current_p99_ms",
        "reference_p99_ms",
    ]

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for key in keys:
            current = current_rows[key]
            reference = reference_rows[key]
            current_rps = as_float(current, "requests_sec")
            reference_rps = as_float(reference, "requests_sec")
            current_power = as_float(current, "avg_power_watts")
            reference_power = as_float(reference, "avg_power_watts")
            writer.writerow(
                {
                    "target": key[0],
                    "arrival_rate_rps": key[1],
                    "current_requests_sec": current.get("requests_sec", ""),
                    "reference_requests_sec": reference.get("requests_sec", ""),
                    "requests_sec_delta_pct": fmt_delta(current_rps, reference_rps),
                    "current_avg_power_watts": current.get("avg_power_watts", ""),
                    "reference_avg_power_watts": reference.get("avg_power_watts", ""),
                    "avg_power_delta_pct": fmt_delta(current_power, reference_power),
                    "current_p50_ms": current.get("p50_ms", ""),
                    "reference_p50_ms": reference.get("p50_ms", ""),
                    "current_p99_ms": current.get("p99_ms", ""),
                    "reference_p99_ms": reference.get("p99_ms", ""),
                }
            )


if __name__ == "__main__":
    main()
