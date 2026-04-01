#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shlex
from pathlib import Path


LATENCY_RE = re.compile(
    r"^\s*Latency\s+(?P<avg>[0-9.]+(?:us|ms|s))\s+"
    r"(?P<stdev>[0-9.]+(?:us|ms|s))\s+"
    r"(?P<p99>[0-9.]+(?:us|ms|s))\s+",
    re.MULTILINE,
)
REQUESTS_SEC_RE = re.compile(r"^\s*Requests/sec:\s+(?P<value>[0-9.]+)", re.MULTILINE)
SHORT_PERCENTILE_RE = re.compile(r"^\s*(?P<pct>[0-9.]+)%\s+(?P<value>\S+)\s*$", re.MULTILINE)
DETAILED_PERCENTILE_RE = re.compile(
    r"^\s*(?P<value>[0-9.]+)\s+(?P<percentile>[0-9.]+)\s+\d+\s+\S+\s*$",
    re.MULTILINE,
)


def duration_to_ms(token: str) -> float:
    token = token.strip()
    if token.endswith("us"):
        return float(token[:-2]) / 1000.0
    if token.endswith("ms"):
        return float(token[:-2])
    if token.endswith("s"):
        return float(token[:-1]) * 1000.0
    return float(token)


def extract_percentile_ms(text: str, target_pct: float) -> float | None:
    short_values: dict[float, float] = {}
    for match in SHORT_PERCENTILE_RE.finditer(text):
        short_values[float(match.group("pct"))] = duration_to_ms(match.group("value"))
    if target_pct in short_values:
        return short_values[target_pct]

    detailed_values: dict[float, float] = {}
    for match in DETAILED_PERCENTILE_RE.finditer(text):
        detailed_values[float(match.group("percentile")) * 100.0] = float(match.group("value"))
    return detailed_values.get(target_pct)


def parse_wrk_log(path: Path) -> dict[str, float | None]:
    text = path.read_text(encoding="utf-8")

    latency_avg_ms = None
    latency_stdev_ms = None
    latency_max_ms = None
    latency_matches = list(LATENCY_RE.finditer(text))
    if latency_matches:
        latency_match = latency_matches[-1]
        latency_avg_ms = duration_to_ms(latency_match.group("avg"))
        latency_stdev_ms = duration_to_ms(latency_match.group("stdev"))
        latency_max_ms = duration_to_ms(latency_match.group("p99"))

    requests_sec = None
    requests_matches = list(REQUESTS_SEC_RE.finditer(text))
    if requests_matches:
        requests_match = requests_matches[-1]
        requests_sec = float(requests_match.group("value"))

    max_from_distribution = extract_percentile_ms(text, 100.0)
    if max_from_distribution is not None:
        latency_max_ms = max_from_distribution

    return {
        "requests_sec": requests_sec,
        "latency_avg_ms": latency_avg_ms,
        "latency_stdev_ms": latency_stdev_ms,
        "latency_max_ms": latency_max_ms,
        "p50_ms": extract_percentile_ms(text, 50.0),
        "p90_ms": extract_percentile_ms(text, 90.0),
        "p95_ms": extract_percentile_ms(text, 95.0),
        "p99_ms": extract_percentile_ms(text, 99.0),
    }


def shell_value(value: float | None) -> str:
    if value is None:
        return "NA"
    return f"{value:.6f}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse wrk2 output and emit latency/QPS metrics.")
    parser.add_argument("--input", required=True, help="wrk/wrk2 output log path")
    parser.add_argument(
        "--format",
        choices=["json", "shell"],
        default="json",
        help="Output format. shell emits POSIX-safe assignments.",
    )
    args = parser.parse_args()

    metrics = parse_wrk_log(Path(args.input))
    if args.format == "json":
        print(json.dumps(metrics, sort_keys=True))
    else:
        for key, value in metrics.items():
            print(f"{key}={shlex.quote(shell_value(value))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
