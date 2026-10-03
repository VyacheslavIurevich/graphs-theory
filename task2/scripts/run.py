#!/usr/bin/env python3
"""Launch one D-Galois DistBench run on N simulated nodes."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import config
from convert import ConvertedGraph, cached_source
from parse_stats import parse_sanity, parse_stat_file, summarize_run
from util import capture, log, which

TIME_BIN = "/usr/bin/time"


def resolve_source(spec: config.DatasetSpec, graph: ConvertedGraph, override: int | None = None) -> int:
    if override is not None:
        return override
    if spec.source is not None:
        return spec.source
    cached = cached_source(graph)
    if cached is not None:
        return cached
    return 0


def build_command(
    algo: str,
    graph: ConvertedGraph,
    nodes: int,
    source: int,
) -> list[str]:
    meta = config.ALGORITHMS[algo]
    binary = config.algo_binary(algo)
    if not binary.is_file():
        raise FileNotFoundError(binary)

    if algo == "sssp":
        input_graph = graph.wgr
        transpose = graph.wtgr
    elif algo == "tc":
        input_graph = graph.sgr
        transpose = None
    else:
        input_graph = graph.gr
        transpose = graph.tgr

    app = [
        str(binary),
        str(input_graph),
        f"-t={config.THREADS_PER_RANK}",
        f"-partition={config.PARTITION}",
        f"-runs={config.INTERNAL_RUNS}",
    ]
    if meta["needs_transpose"] and transpose is not None:
        app.append(f"-graphTranspose={transpose}")
    if algo != "tc":
        app.append(f"-exec={config.EXEC_MODEL}")
    if algo in ("bfs", "sssp"):
        app.append(f"-startNode={source}")
        # DistBFS/DistSSSP default is 1000; high-diameter roads/RGG need more.
        app.append(f"-maxIterations={config.BFS_SSSP_MAX_ITERATIONS}")
    if algo == "pr":
        app.append(f"-maxIterations={config.PR_MAX_ITERATIONS}")
        app.append(f"-tolerance={config.PR_TOLERANCE}")
    if algo == "tc":
        app.append("-symmetricGraph")

    mpirun = which("mpirun") or "mpirun"
    # --use-hwthread-cpus: OpenMPI slot count defaults to cores (4 on the
    # stand), so -n 6/-n 8 die with "not enough slots". Hyperthreads give 8
    # slots; P=6 then starts without --oversubscribe.
    return [
        mpirun,
        "--use-hwthread-cpus",
        "-n",
        str(nodes),
        "--bind-to",
        "none",
        *app,
    ]


def _parse_time_v(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    match = re.search(r"Maximum resident set size \(kbytes\): (\d+)", text)
    if match:
        out["peak_rss_kb"] = int(match.group(1))
    match = re.search(r"User time \(seconds\): ([0-9.]+)", text)
    if match:
        out["user_sec"] = float(match.group(1))
    match = re.search(r"System time \(seconds\): ([0-9.]+)", text)
    if match:
        out["sys_sec"] = float(match.group(1))
    return out


def run_once(
    algo: str,
    graph: ConvertedGraph,
    nodes: int,
    out_dir: Path,
    source: int | None = None,
    ignore_max_nodes: bool = False,
    timeout: int | None = None,
) -> dict[str, Any]:
    spec = config.DATASETS[graph.name]
    if spec.max_nodes is not None and nodes > spec.max_nodes and not ignore_max_nodes:
        return {
            "status": "skipped",
            "reason": f"nodes={nodes} > max_nodes={spec.max_nodes} for {graph.name}",
            "algo": algo,
            "dataset": graph.name,
            "nodes": nodes,
        }
    if not config.dataset_allowed_for_algo(spec, algo):
        return {
            "status": "skipped",
            "reason": f"{algo} requires a symmetric undirected graph; {graph.name} is directed",
            "algo": algo,
            "dataset": graph.name,
            "nodes": nodes,
        }

    src = resolve_source(spec, graph, source)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{algo}_{graph.name}_n{nodes}"
    stat_file = out_dir / f"{stem}.stats.csv"
    log_file = out_dir / f"{stem}.log"
    cmd = build_command(algo, graph, nodes, src)
    # inject statFile into the application argv (after binary name)
    app_index = cmd.index(str(config.algo_binary(algo)))
    cmd.insert(app_index + 1, f"-statFile={stat_file}")

    wrapped = cmd
    if Path(TIME_BIN).exists():
        wrapped = [TIME_BIN, "-v", *cmd]

    env = {
        "GALOIS_DO_NOT_BIND_THREADS": "1",
        "PRINT_PER_HOST_STATS": "1",
        "OMPI_MCA_btl_vader_single_copy_mechanism": "none",
    }
    log("run", f"{algo} n={nodes}", graph.name)
    started = time.monotonic()
    try:
        proc = capture(
            wrapped,
            env=env,
            timeout=timeout if timeout is not None else config.TIMEOUT_SEC,
            cwd=out_dir,
        )
        status = "ok" if proc.returncode == 0 else "error"
        output = proc.stdout or ""
        returncode = proc.returncode
    except Exception as exc:
        status = "timeout" if "timed out" in str(exc).lower() else "error"
        output = str(exc)
        returncode = None
    wall_ms = (time.monotonic() - started) * 1000.0
    log_file.write_text(output)

    parsed = parse_stat_file(stat_file)
    summary = summarize_run(parsed)
    summary.update(_parse_time_v(output))
    summary["sanity"] = parse_sanity(output)
    return {
        "status": status,
        "returncode": returncode,
        "algo": algo,
        "dataset": graph.name,
        "directed": spec.directed,
        "family": spec.family,
        "nodes": nodes,
        "threads_per_rank": config.THREADS_PER_RANK,
        "partition": config.PARTITION,
        "exec": config.EXEC_MODEL if algo != "tc" else "n/a",
        "source": src,
        "command": cmd,
        "wall_ms": wall_ms,
        "log": str(log_file),
        "stat_file": str(stat_file),
        **summary,
    }
