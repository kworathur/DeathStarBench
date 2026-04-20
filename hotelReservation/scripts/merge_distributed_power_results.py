#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


LATENCY_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(us|ms|s)?\s*$", re.IGNORECASE)


def parse_number(value: str | None) -> float | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw or raw.upper() == "NA":
        return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def parse_latency_ms(value: str | None) -> float | None:
    if value is None:
        return None
    raw = value.strip()
    if not raw or raw.upper() == "NA":
        return None
    match = LATENCY_RE.match(raw)
    if not match:
        return parse_number(raw)
    magnitude = float(match.group(1))
    unit = (match.group(2) or "ms").lower()
    if unit == "us":
        return magnitude / 1000.0
    if unit == "s":
        return magnitude * 1000.0
    return magnitude


def discover_csvs(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(candidate for candidate in path.rglob("results.csv") if candidate.is_file())


def read_rows(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for csv_path in discover_csvs(path):
        with csv_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            rows.extend(reader)
    return rows


def key_for(row: dict[str, str]) -> tuple[str, str]:
    target = row.get("target", "").strip()
    rate = row.get("arrival_rate_rps", "").strip()
    return target, rate


def merge_rows(
    client_rows: list[dict[str, str]],
    server_rows: list[dict[str, str]],
) -> list[dict[str, str | float]]:
    client_index = {key_for(row): row for row in client_rows}
    server_index = {key_for(row): row for row in server_rows}
    keys = sorted(set(client_index) | set(server_index), key=lambda item: (item[0], float(item[1] or 0)))

    merged: list[dict[str, str | float]] = []
    for key in keys:
        client = client_index.get(key, {})
        server = server_index.get(key, {})
        merged.append(
            {
                "target": client.get("target") or server.get("target") or "",
                "governor": server.get("governor", ""),
                "arrival_rate_rps": parse_number(client.get("arrival_rate_rps") or server.get("arrival_rate_rps")),
                "requests_sec": parse_number(client.get("requests_sec")),
                "avg_power_watts": parse_number(server.get("avg_power_watts")),
                "latency_avg_ms": parse_latency_ms(client.get("latency_avg")),
                "latency_stdev_ms": parse_latency_ms(client.get("latency_stdev")),
                "latency_max_ms": parse_latency_ms(client.get("latency_max")),
                "p50_ms": parse_latency_ms(client.get("p50")),
                "p90_ms": parse_latency_ms(client.get("p90")),
                "p99_ms": parse_latency_ms(client.get("p99")),
                "socket_errors": client.get("socket_errors", ""),
                "non_2xx_3xx": parse_number(client.get("non_2xx_3xx")),
                "wrk_output": client.get("wrk_output", ""),
                "powerstat_output": server.get("powerstat_output", ""),
            }
        )
    return merged


def write_rows(path: Path, rows: list[dict[str, str | float]]) -> None:
    fieldnames = [
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
        "p99_ms",
        "socket_errors",
        "non_2xx_3xx",
        "wrk_output",
        "powerstat_output",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge distributed client and server sweep results.")
    parser.add_argument("--client", required=True, help="Client results CSV or directory containing results.csv files.")
    parser.add_argument("--server", required=True, help="Server results CSV or directory containing results.csv files.")
    parser.add_argument("--output", required=True, help="Output CSV path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client_rows = read_rows(Path(args.client))
    server_rows = read_rows(Path(args.server))
    merged_rows = merge_rows(client_rows, server_rows)
    write_rows(Path(args.output), merged_rows)


if __name__ == "__main__":
    main()
