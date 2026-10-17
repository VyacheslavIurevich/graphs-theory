#!/usr/bin/env python3
"""Strong-scaling metrics: speedup and efficiency against the 1-node baseline."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _key(row: dict[str, Any]) -> tuple[str, str]:
    return row["algo"], row["dataset"]


def _sanity_equal(left: dict[str, Any] | None, right: dict[str, Any] | None) -> bool:
    if not left or not right:
        return not left and not right
    keys = (set(left) | set(right)) - {"residual_sum"}
    if not keys:
        return True
    for key in keys:
        if key not in left or key not in right:
            return False
        a, b = left[key], right[key]
        if isinstance(a, float) or isinstance(b, float):
            scale = max(1.0, abs(float(a)), abs(float(b)))
            # Distributed reductions are not associative; ~0.2% on belgium PR.
            if abs(float(a) - float(b)) > 5e-3 * scale:
                return False
        elif a != b:
            return False
    return True


def attach_sanity(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("status") == "ok":
            grouped[_key(row)].append(row)
    for items in grouped.values():
        baseline = next((r.get("sanity") for r in items if r.get("nodes") == 1), None)
        if baseline is None and items:
            baseline = items[0].get("sanity")
        for row in items:
            row["sanity_match"] = _sanity_equal(row.get("sanity"), baseline)
    for row in rows:
        row.setdefault("sanity_match", None)
    return rows


def attach_scaling(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baselines: dict[tuple[str, str], float] = {}
    for row in rows:
        if row.get("status") != "ok":
            continue
        if row.get("nodes") != 1:
            continue
        median = row.get("kernel_ms_median")
        if median:
            baselines[_key(row)] = median

    for row in rows:
        base = baselines.get(_key(row))
        median = row.get("kernel_ms_median")
        nodes = row.get("nodes")
        if not base or not median or not nodes:
            row["speedup"] = None
            row["efficiency"] = None
            continue
        speedup = base / median
        row["speedup"] = speedup
        row["efficiency"] = speedup / nodes
    return rows


def scaling_table(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_key(row)].append(row)
    table: list[dict[str, Any]] = []
    for (algo, dataset), items in sorted(grouped.items()):
        items = sorted(items, key=lambda r: r.get("nodes") or 0)
        table.append(
            {
                "algo": algo,
                "dataset": dataset,
                "points": [
                    {
                        "nodes": r.get("nodes"),
                        "status": r.get("status"),
                        "kernel_ms_median": r.get("kernel_ms_median"),
                        "speedup": r.get("speedup"),
                        "efficiency": r.get("efficiency"),
                        "graph_construct_ms": r.get("graph_construct_ms"),
                        "host_imbalance": r.get("host_imbalance"),
                        "num_iterations_median": r.get("num_iterations_median"),
                        "gluon_send_bytes_median": r.get("gluon_send_bytes_median"),
                        "gluon_num_messages_median": r.get("gluon_num_messages_median"),
                        "gluon_replication_factor": r.get("gluon_replication_factor"),
                        "sanity": r.get("sanity"),
                        "sanity_match": r.get("sanity_match"),
                    }
                    for r in items
                ],
            }
        )
    return table
