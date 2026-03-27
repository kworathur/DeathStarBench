#!/usr/bin/env python3
"""Parse wrk/wrk2-style perf result text files and emit latency histograms."""

from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont


PERCENTILE_RE = re.compile(
    r"^\s*(?P<value>\d+(?:\.\d+)?)\s+(?P<percentile>\d+(?:\.\d+)?)\s+"
    r"(?P<total_count>\d+)\s+(?P<inverse>\S+)\s*$"
)
LATENCY_RE = re.compile(
    r"^\s*Latency\s+(?P<avg>\d+(?:\.\d+)?)ms\s+(?P<stdev>\d+(?:\.\d+)?)ms\s+"
    r"(?P<p99>\d+(?:\.\d+)?)ms"
)
REQUESTS_RE = re.compile(
    r"^\s*(?P<requests>\d+)\s+requests in\s+(?P<duration>.+?),\s+(?P<read>.+?)\s+read\s*$"
)
SOCKET_RE = re.compile(
    r"^\s*Socket errors:\s+connect\s+(?P<connect>\d+),\s+read\s+(?P<read>\d+),\s+"
    r"write\s+(?P<write>\d+),\s+timeout\s+(?P<timeout>\d+)\s*$"
)
REQ_SEC_RE = re.compile(r"^\s*Requests/sec:\s+(?P<value>\d+(?:\.\d+)?)")
TRANSFER_RE = re.compile(r"^\s*Transfer/sec:\s+(?P<value>\S+)")


@dataclass
class PerfSummary:
    source_file: str
    avg_ms: float | None
    stdev_ms: float | None
    p99_ms: float | None
    requests: int | None
    duration: str | None
    bytes_read: str | None
    requests_per_sec: float | None
    transfer_per_sec: str | None
    socket_errors: dict[str, int]
    histogram_samples_ms: list[float]
    percentile_points: list[tuple[float, float]]


def parse_perf_file(path: Path) -> PerfSummary:
    avg_ms = stdev_ms = p99_ms = None
    requests = None
    duration = bytes_read = None
    requests_per_sec = None
    transfer_per_sec = None
    socket_errors = {"connect": 0, "read": 0, "write": 0, "timeout": 0}

    cumulative: list[tuple[float, int]] = []
    percentile_points: list[tuple[float, float]] = []

    for raw_line in path.read_text().splitlines():
        line = raw_line.rstrip("\n")

        match = LATENCY_RE.match(line)
        if match:
            avg_ms = float(match.group("avg"))
            stdev_ms = float(match.group("stdev"))
            p99_ms = float(match.group("p99"))
            continue

        match = REQUESTS_RE.match(line)
        if match:
            requests = int(match.group("requests"))
            duration = match.group("duration")
            bytes_read = match.group("read")
            continue

        match = SOCKET_RE.match(line)
        if match:
            socket_errors = {key: int(match.group(key)) for key in socket_errors}
            continue

        match = REQ_SEC_RE.match(line)
        if match:
            requests_per_sec = float(match.group("value"))
            continue

        match = TRANSFER_RE.match(line)
        if match:
            transfer_per_sec = match.group("value")
            continue

        match = PERCENTILE_RE.match(line)
        if match:
            value = float(match.group("value"))
            percentile = float(match.group("percentile"))
            total_count = int(match.group("total_count"))
            cumulative.append((value, total_count))
            percentile_points.append((percentile * 100.0, value))

    histogram_samples_ms = expand_histogram_samples(cumulative)

    return PerfSummary(
        source_file=str(path),
        avg_ms=avg_ms,
        stdev_ms=stdev_ms,
        p99_ms=p99_ms,
        requests=requests,
        duration=duration,
        bytes_read=bytes_read,
        requests_per_sec=requests_per_sec,
        transfer_per_sec=transfer_per_sec,
        socket_errors=socket_errors,
        histogram_samples_ms=histogram_samples_ms,
        percentile_points=percentile_points,
    )


def expand_histogram_samples(cumulative: Iterable[tuple[float, int]]) -> list[float]:
    samples: list[float] = []
    previous = 0
    for value_ms, total_count in cumulative:
        delta = max(0, total_count - previous)
        samples.extend([value_ms] * delta)
        previous = total_count
    return samples


def build_histogram(samples: list[float], bins: int | None = None) -> list[tuple[float, float, int]]:
    if not samples:
        return []

    sample_count = len(samples)
    value_min = min(samples)
    value_max = max(samples)

    if math.isclose(value_min, value_max):
        return [(value_min, value_max, sample_count)]

    if bins is None:
        bins = min(12, max(6, int(math.sqrt(sample_count))))

    width = (value_max - value_min) / bins
    edges = [value_min + width * i for i in range(bins + 1)]
    counts = [0] * bins

    for sample in samples:
        index = min(bins - 1, int((sample - value_min) / width))
        counts[index] += 1

    histogram = []
    for idx, count in enumerate(counts):
        histogram.append((edges[idx], edges[idx + 1], count))
    return histogram


def load_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for font_name in ("Arial.ttf", "Helvetica.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    center_x: float,
    y: float,
    font: ImageFont.ImageFont | ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    draw.text((center_x - text_width / 2, y), text, font=font, fill=fill)


def percentile_chart_to_png(title: str, percentile_points: list[tuple[float, float]]) -> Image.Image:
    width = 900
    height = 420
    margin_left = 70
    margin_right = 20
    margin_top = 50
    margin_bottom = 70
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(20)
    label_font = load_font(12)
    small_font = load_font(11)
    axis_color = "#334155"
    grid_color = "#cbd5e1"
    bar_color = "#2563eb"
    text_color = "#1f2937"

    if not percentile_points:
        draw_centered_text(draw, "No histogram data", width / 2, height / 2 - 8, label_font, text_color)
        return image

    max_latency = max(latency_ms for _, latency_ms in percentile_points) or 1.0
    draw_centered_text(draw, title, width / 2, 10, title_font, text_color)

    for tick in range(0, 5):
        latency_value = max_latency * tick / 4
        y = margin_top + plot_height - (plot_height * tick / 4)
        draw.line((margin_left, y, width - margin_right, y), fill=grid_color, width=1)
        label = f"{latency_value:.1f}"
        bbox = draw.textbbox((0, 0), label, font=label_font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        draw.text((margin_left - 10 - text_width, y - text_height / 2), label, font=label_font, fill=text_color)

    for tick in range(0, 5):
        percentile_value = tick * 25
        x = margin_left + plot_width * tick / 4
        draw.line((x, margin_top, x, margin_top + plot_height), fill=grid_color, width=1)
        label = f"{percentile_value:g}"
        bbox = draw.textbbox((0, 0), label, font=label_font)
        text_width = bbox[2] - bbox[0]
        draw.text((x - text_width / 2, margin_top + plot_height + 8), label, font=label_font, fill=text_color)

    draw.line((margin_left, margin_top, margin_left, margin_top + plot_height), fill=axis_color, width=2)
    draw.line(
        (margin_left, margin_top + plot_height, width - margin_right, margin_top + plot_height),
        fill=axis_color,
        width=2,
    )

    plot_points: list[tuple[float, float]] = []
    for percentile, latency_ms in percentile_points:
        x = margin_left + plot_width * (percentile / 100.0)
        y = margin_top + plot_height - plot_height * (latency_ms / max_latency)
        plot_points.append((x, y))

    if len(plot_points) == 1:
        x, y = plot_points[0]
        draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=bar_color)
    else:
        draw.line(plot_points, fill=bar_color, width=3, joint="curve")

    for percentile in (50, 90, 99, 99.9):
        closest = min(percentile_points, key=lambda point: abs(point[0] - percentile))
        x = margin_left + plot_width * (closest[0] / 100.0)
        y = margin_top + plot_height - plot_height * (closest[1] / max_latency)
        draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=bar_color)
        draw_centered_text(draw, f"{closest[0]:g}%", x, max(margin_top, y - 18), small_font, text_color)

    draw_centered_text(draw, "Requests (%)", width / 2, height - 22, label_font, text_color)
    draw_centered_text(draw, "Latency (ms)", 24, height / 2 - 8, label_font, text_color)
    return image


def write_summary_json(path: Path, summaries: list[PerfSummary]) -> None:
    data = []
    for summary in summaries:
        data.append(
            {
                "source_file": summary.source_file,
                "avg_ms": summary.avg_ms,
                "stdev_ms": summary.stdev_ms,
                "p99_ms": summary.p99_ms,
                "requests": summary.requests,
                "duration": summary.duration,
                "bytes_read": summary.bytes_read,
                "requests_per_sec": summary.requests_per_sec,
                "transfer_per_sec": summary.transfer_per_sec,
                "socket_errors": summary.socket_errors,
                "histogram_sample_count": len(summary.histogram_samples_ms),
            }
        )
    path.write_text(json.dumps(data, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="Perf result text files to parse")
    parser.add_argument(
        "--out-dir",
        default="latency_histograms",
        help="Directory for generated histogram PNGs and summary JSON",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries: list[PerfSummary] = []
    for input_name in args.inputs:
        path = Path(input_name)
        summary = parse_perf_file(path)
        summaries.append(summary)

        png = percentile_chart_to_png(f"{path.stem} latency percentiles", summary.percentile_points)
        png.save(out_dir / f"{path.stem}_histogram.png")

    write_summary_json(out_dir / "summary.json", summaries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
