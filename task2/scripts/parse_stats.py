#!/usr/bin/env python3
"""Parse Galois DistBench -statFile CSV (STAT/PARAM rows)."""

from __future__ import annotations

import csv
import re
import statistics
from pathlib import Path
from typing import Any


def parse_stat_file(path: Path) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    if not path.exists():
        return {"path": str(path), "rows": [], "params": {}, "stats": {}}
    text = path.read_text(errors="replace")
    reader = csv.reader(line for line in text.splitlines() if line.strip())
    header: list[str] | None = None
    for raw in reader:
        if not raw:
            continue
        if raw[0] == "STAT_TYPE":
            header = [h.strip() for h in raw]
            continue
        if header is None:
            # fallback when Galois omitted the header
            header = [
                "STAT_TYPE",
                "HOST_ID",
                "REGION",
                "CATEGORY",
                "TOTAL_TYPE",
                "TOTAL",
            ]
        while len(raw) < len(header):
            raw.append("")
        row = {header[i]: raw[i].strip() for i in range(len(header))}
        if len(raw) > len(header):
            row["TOTAL"] = (header[-1] and ",".join(raw[len(header) - 1 :])) or raw[-1]
        rows.append(row)

    params: dict[str, str] = {}
    stats: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        kind = row.get("STAT_TYPE", "")
        key = f"{row.get('REGION', '')}/{row.get('CATEGORY', '')}"
        if kind == "PARAM":
            params[key] = row.get("TOTAL", "")
        else:
            stats.setdefault(key, []).append(row)
    return {"path": str(path), "rows": rows, "params": params, "stats": stats}


def _first_float(stats: dict[str, list[dict[str, str]]], *keys: str) -> float | None:
    for key in keys:
        if stats.get(key):
            try:
                return float(stats[key][0].get("TOTAL", "nan"))
            except ValueError:
                return None
    return None


def _values_matching(stats: dict[str, list[dict[str, str]]], prefix: str) -> list[float]:
    out: list[float] = []
    for key, items in stats.items():
        category = key.split("/", 1)[-1]
        if category.startswith(prefix) and items:
            try:
                out.append(float(items[0]["TOTAL"]))
            except (ValueError, KeyError):
                continue
    return out


# Kernel Gluon counters look like ReduceSendBytes_BFS_0, not InitializeGraph.
_GLUON_KERNEL = re.compile(r"^(ReduceSendBytes|ReduceNumMessages)_(BFS|SSSP|PageRank|TC)_(\d+)$")


def _preferred_total(items: list[dict[str, str]]) -> float | None:
    preferred = None
    for item in items:
        try:
            value = float(item.get("TOTAL", "nan"))
        except (ValueError, TypeError):
            continue
        kind = item.get("TOTAL_TYPE", "")
        if kind == "HSUM":
            return value
        if preferred is None or kind in ("HMAX", "HOST_0"):
            preferred = value
    return preferred


def _gluon_kernel_series(
    stats: dict[str, list[dict[str, str]]], kind: str, warmup_runs: int
) -> list[float]:
    by_run: dict[int, float] = {}
    for key, items in stats.items():
        if not key.startswith("Gluon/") or not items:
            continue
        match = _GLUON_KERNEL.fullmatch(key.split("/", 1)[-1])
        if not match or match.group(1) != kind:
            continue
        value = _preferred_total(items)
        if value is None:
            continue
        by_run[int(match.group(3))] = value
    measured = [by_run[idx] for idx in sorted(by_run) if idx >= warmup_runs]
    if measured:
        return measured
    return [by_run[idx] for idx in sorted(by_run)]


def summarize_run(parsed: dict[str, Any], warmup_runs: int = 1) -> dict[str, Any]:
    stats = parsed.get("stats", {})
    timers = []
    for key, items in stats.items():
        category = key.split("/", 1)[-1]
        match = re.fullmatch(r"Timer_(\d+)", category)
        if not match or not items:
            continue
        try:
            timers.append((int(match.group(1)), float(items[0]["TOTAL"])))
        except ValueError:
            continue
    timers.sort()
    measured = [ms for idx, ms in timers if idx >= warmup_runs]
    if not measured and timers:
        measured = [ms for _, ms in timers]

    host_values: list[float] | None = None
    for key, items in stats.items():
        category = key.split("/", 1)[-1]
        if not category.startswith("Timer_"):
            continue
        for item in items:
            if item.get("TOTAL_TYPE") == "HostValues":
                raw = item.get("TOTAL", "")
                try:
                    host_values = [
                        float(part.strip())
                        for part in raw.replace(",", ";").split(";")
                        if part.strip()
                    ]
                except ValueError:
                    host_values = None

    imbalance = None
    if host_values:
        mean = statistics.fmean(host_values)
        if mean > 0:
            imbalance = max(host_values) / mean

    iterations = _values_matching(stats, "NumIterations_")
    work_items = _values_matching(stats, "NumWorkItems")
    send_bytes = _gluon_kernel_series(stats, "ReduceSendBytes", warmup_runs)
    num_messages = _gluon_kernel_series(stats, "ReduceNumMessages", warmup_runs)

    return {
        "kernel_ms": measured,
        "kernel_ms_median": statistics.median(measured) if measured else None,
        "kernel_ms_min": min(measured) if measured else None,
        "kernel_ms_max": max(measured) if measured else None,
        "warmup_timer_ms": timers[0][1] if timers else None,
        "graph_construct_ms": _first_float(
            stats,
            "DistBench/GraphConstructTime",
            "dGraph_Generic/GraphConstructTime",
            "dGraph_Mining/GraphConstructTime",
        ),
        "graph_reading_ms": _first_float(
            stats, "dGraph_Generic/GraphReading", "dGraph_Mining/GraphReading"
        ),
        "timer_total_ms": _first_float(
            stats,
            "BFS/TimerTotal",
            "SSSP/TimerTotal",
            "PageRank/TimerTotal",
            "TC/TimerTotal",
        ),
        "num_iterations": iterations,
        "num_iterations_median": statistics.median(iterations) if iterations else None,
        "num_work_items_sum": sum(work_items) if work_items else None,
        "host_times_ms": host_values,
        "host_imbalance": imbalance,
        "gluon_send_bytes": send_bytes,
        "gluon_send_bytes_median": (statistics.median(send_bytes) if send_bytes else None),
        "gluon_num_messages": num_messages,
        "gluon_num_messages_median": (statistics.median(num_messages) if num_messages else None),
        "gluon_replication_factor": _first_float(stats, "Gluon/ReplicationFactor"),
        "params": parsed.get("params", {}),
    }


def parse_sanity(stdout: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    int_patterns = {
        "nodes_visited": r"Number of nodes visited from source \d+ is (\d+)",
        "max_distance": r"Max distance from source \d+ is (\d+)",
        "triangles": r"Total number of triangles (\d+)",
    }
    for key, pattern in int_patterns.items():
        match = re.search(pattern, stdout)
        if match:
            out[key] = int(match.group(1))
    match = re.search(r"Rank sum is ([0-9.eE+-]+)", stdout)
    if match:
        out["rank_sum"] = float(match.group(1))
    match = re.search(r"Residual sum is ([0-9.eE+-]+)", stdout)
    if match:
        out["residual_sum"] = float(match.group(1))
    return out
