#!/usr/bin/env python3
"""Build, prepare graphs, run D-Galois scaling, and write a JSON report."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
from build import build
from convert import convert_dataset
from datasets import ensure_mtx
from metrics import attach_sanity, attach_scaling, scaling_table
from run import resolve_source, run_once
from util import collect_host_info, git_rev, log


def _parse_list(value: str | None, fallback: Iterable[str]) -> list[str]:
    if not value:
        return list(fallback)
    if value.strip().lower() in ("all", "*"):
        return [d.name for d in config.all_datasets()]
    if value.strip().lower() == "large":
        return [d.name for d in config.large_datasets()]
    if value.strip().lower() == "default":
        return [d.name for d in config.default_datasets()]
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_nodes(value: str | None, profile: str) -> list[int]:
    if value:
        return [int(item) for item in value.split(",") if item.strip()]
    if profile == "stand":
        return config.stand_node_counts()
    return config.default_node_counts()


def _dataset_names(args: argparse.Namespace) -> list[str]:
    profile = getattr(args, "profile", "laptop")
    fallback = (
        [d.name for d in config.all_datasets()]
        if profile == "stand"
        else [d.name for d in config.default_datasets()]
    )
    return _parse_list(getattr(args, "dataset", None), fallback)


def _ignore_max_nodes(args: argparse.Namespace) -> bool:
    if getattr(args, "ignore_max_nodes", False):
        return True
    return getattr(args, "profile", "laptop") == "stand"


def _timeout_sec(args: argparse.Namespace) -> int:
    if getattr(args, "timeout", None):
        return int(args.timeout)
    if getattr(args, "profile", "laptop") == "stand":
        return config.STAND_TIMEOUT_SEC
    return config.TIMEOUT_SEC


def cmd_build(args: argparse.Namespace) -> None:
    build(force_configure=args.force)


def _run_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return row["algo"], row["dataset"], int(row["nodes"])


def _is_stale(row: dict[str, Any], source: int | None) -> bool:
    """True if an existing ok row must be measured again."""
    if row.get("status") != "ok":
        return True
    if row.get("algo") in ("bfs", "sssp"):
        iters = row.get("num_iterations_median")
        if iters is not None and iters >= config.BFS_SSSP_DEFAULT_CAP:
            return True
        old_source = row.get("source")
        if source is not None and old_source is not None and int(old_source) != int(source):
            return True
    return False


def cmd_prepare(args: argparse.Namespace) -> None:
    names = _dataset_names(args)
    build(force_configure=False)
    force = bool(getattr(args, "force_convert", False))
    for name in names:
        mtx = ensure_mtx(name)
        graph = convert_dataset(name, mtx, force=force)
        log("prepare", "ready", name, graph.gr)


def cmd_run(args: argparse.Namespace) -> Path:
    profile = getattr(args, "profile", "laptop")
    algos = _parse_list(args.algo, config.ALGORITHMS.keys())
    names = _dataset_names(args)
    nodes_list = _parse_nodes(args.nodes, profile)
    ignore_cap = _ignore_max_nodes(args)
    timeout = _timeout_sec(args)
    resume = bool(getattr(args, "resume", False))
    resume_from = Path(args.resume_from) if getattr(args, "resume_from", None) else None
    build(force_configure=False)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.output) if args.output else config.RESULTS_DIR / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    existing: dict[tuple[str, str, int], dict[str, Any]] = {}
    created_at = stamp
    source_report = resume_from / "report.json" if resume_from else out_dir / "report.json"
    if (resume or resume_from) and source_report.is_file():
        previous = json.loads(source_report.read_text())
        created_at = previous.get("created_at", stamp)
        for row in previous.get("runs", []):
            existing[_run_key(row)] = row
        log("run", "resume", f"{len(existing)} rows from", source_report)

    info_path = out_dir / "stand_info.txt"
    if not info_path.exists():
        _write_stand_info(
            out_dir,
            profile=profile,
            names=names,
            nodes_list=nodes_list,
            timeout=timeout,
        )
    else:
        with info_path.open("a") as handle:
            handle.write(f"resumed_at: {stamp}\n")
            handle.write(f"nodes: {','.join(map(str, nodes_list))}\n")

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    failed_tc: set[str] = {
        key[1]
        for key, row in existing.items()
        if key[0] == "tc" and row.get("status") == "error" and key[2] != 8
    }

    def flush() -> None:
        _write_report(
            out_dir,
            rows=rows,
            created_at=created_at,
            resumed_at=stamp if (resume or resume_from) else None,
            profile=profile,
            ignore_cap=ignore_cap,
            timeout=timeout,
            names=names,
            nodes_list=nodes_list,
        )

    for name in names:
        mtx = ensure_mtx(name)
        graph = convert_dataset(name, mtx, force=name in failed_tc)
        for algo in algos:
            for nodes in nodes_list:
                key = (algo, name, nodes)
                prev = existing.get(key)
                source = resolve_source(config.DATASETS[name], graph)
                if prev and prev.get("status") == "skipped":
                    rows.append(prev)
                    seen.add(key)
                    log("run", "skip", algo, name, f"n={nodes}")
                    continue
                if prev and not _is_stale(prev, source):
                    rows.append(prev)
                    seen.add(key)
                    log("run", "skip", algo, name, f"n={nodes}")
                    continue
                row = run_once(
                    algo,
                    graph,
                    nodes,
                    out_dir / "runs",
                    ignore_max_nodes=ignore_cap,
                    timeout=timeout,
                )
                rows.append(row)
                seen.add(key)
                log("run", row["status"], algo, name, f"n={nodes}")
                flush()

    for key, row in existing.items():
        if key not in seen:
            rows.append(row)

    flush()
    recent = config.RESULTS_DIR / "recent"
    if recent.is_symlink() or recent.exists():
        recent.unlink()
    recent.symlink_to(out_dir.name)
    log("report", "wrote", out_dir / "report.json")
    return out_dir / "report.json"


def _write_report(
    out_dir: Path,
    *,
    rows: list[dict[str, Any]],
    created_at: str,
    resumed_at: str | None,
    profile: str,
    ignore_cap: bool,
    timeout: int,
    names: list[str],
    nodes_list: list[int],
) -> None:
    attach_scaling(rows)
    attach_sanity(rows)
    host = collect_host_info()
    report: dict[str, Any] = {
        "created_at": created_at,
        "resumed_at": resumed_at,
        "profile": profile,
        "ignore_max_nodes": ignore_cap,
        "timeout_sec": timeout,
        "machine": {
            **host,
            "threads_per_rank": config.THREADS_PER_RANK,
            "partition": config.PARTITION,
            "exec": config.EXEC_MODEL,
            "internal_runs": config.INTERNAL_RUNS,
            "pr_max_iterations": config.PR_MAX_ITERATIONS,
            "bfs_sssp_max_iterations": config.BFS_SSSP_MAX_ITERATIONS,
            "node_counts": nodes_list,
        },
        "git": {
            "repo": git_rev(config.ROOT.parent),
            "galois": git_rev(config.GALOIS_SRC),
        },
        "justification": {
            "model": (
                "Each MPI rank is one simulated node with -t=1. "
                "GALOIS_DO_NOT_BIND_THREADS=1 is required when several ranks "
                "share a laptop. Partition is outgoing edge-cut with BSP Sync "
                "because Galois recommends that pair for <= 16 hosts. "
                "mpirun --use-hwthread-cpus so OpenMPI slots follow hardware "
                "threads (the stand has 4 cores / 8 threads). P=6 is a milder "
                "oversubscribe point than P=8."
            ),
            "metrics": (
                "Kernel time is Galois Timer_i after dropping the first run as "
                "warmup. Speedup and efficiency use the 1-node kernel median. "
                "GraphConstructTime is kept separately so partitioning cost is "
                "not mistaken for algorithm scaling. HostValues give imbalance. "
                "Gluon ReduceSendBytes/ReduceNumMessages (kernel region only, "
                "warmup dropped) show when scaling hits communication. "
                "PageRank uses a fixed iteration cap so work does not change with p. "
                "BFS/SSSP pass -maxIterations=10000 so high-diameter graphs "
                "are not cut off at the DistBench default of 1000."
            ),
            "datasets": {name: config.DATASETS[name].why for name in names},
        },
        "runs": rows,
        "scaling": scaling_table(rows),
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2))
    _write_markdown(out_dir / "report.md", report)
    _write_handoff(out_dir, report)


def _write_stand_info(
    out_dir: Path,
    *,
    profile: str,
    names: list[str],
    nodes_list: list[int],
    timeout: int,
) -> None:
    host = collect_host_info()
    lines = [
        f"profile: {profile}",
        f"hostname: {host.get('hostname')}",
        f"uname: {host.get('uname')}",
        f"cpu_model: {host.get('cpu_model')}",
        f"cpu_count: {host.get('cpu_count')}",
        f"mem_total: {host.get('mem_total')}",
        f"mem_available: {host.get('mem_available')}",
        f"nodes: {','.join(map(str, nodes_list))}",
        f"datasets: {','.join(names)}",
        f"timeout_sec: {timeout}",
        f"partition: {config.PARTITION}",
        f"exec: {config.EXEC_MODEL}",
        f"threads_per_rank: {config.THREADS_PER_RANK}",
        f"repo: {git_rev(config.ROOT.parent)}",
        f"galois: {git_rev(config.GALOIS_SRC)}",
        "",
    ]
    (out_dir / "stand_info.txt").write_text("\n".join(lines))


def _write_handoff(out_dir: Path, report: dict[str, Any]) -> None:
    ok = sum(1 for r in report["runs"] if r.get("status") == "ok")
    err = sum(1 for r in report["runs"] if r.get("status") in ("error", "timeout"))
    skipped = sum(1 for r in report["runs"] if r.get("status") == "skipped")
    text = f"""Отдайте весь этот каталог целиком:

  {out_dir}

Минимум, без которого нельзя разобрать прогон:
  report.json
  report.md
  stand_info.txt
  console.log          (если запускали scripts/run_stand.sh)
  runs/*.log
  runs/*.stats.csv

Сводка: ok={ok} error/timeout={err} skipped={skipped}
"""
    (out_dir / "WHAT_TO_SEND.txt").write_text(text)


def _fmt_metric(value: object, digits: int = 3) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# D-Galois node scaling",
        "",
        f"Created: {report['created_at']}",
        f"Profile: {report.get('profile', '')}",
        "",
        "## Scaling",
        "",
        "| algo | dataset | nodes | status | kernel ms | speedup | efficiency | construct ms | imb | msgs | send KB | sanity |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for group in report["scaling"]:
        for point in group["points"]:
            send_kb = point.get("gluon_send_bytes_median")
            if send_kb is not None:
                send_kb = send_kb / 1024.0
            sanity = point.get("sanity") or {}
            sanity_bits = []
            if "nodes_visited" in sanity:
                sanity_bits.append(f"vis={sanity['nodes_visited']}")
            if "max_distance" in sanity:
                sanity_bits.append(f"d={sanity['max_distance']}")
            if "triangles" in sanity:
                sanity_bits.append(f"tri={sanity['triangles']}")
            if "rank_sum" in sanity:
                sanity_bits.append(f"pr={sanity['rank_sum']:.4g}")
            if point.get("sanity_match") is False:
                sanity_bits.append("MISMATCH")
            lines.append(
                "| {algo} | {dataset} | {nodes} | {status} | {kernel} | {speedup} | {eff} | {construct} | {imb} | {msgs} | {send} | {sanity} |".format(
                    algo=group["algo"],
                    dataset=group["dataset"],
                    nodes=point.get("nodes"),
                    status=point.get("status"),
                    kernel=_fmt_metric(point.get("kernel_ms_median"), 1),
                    speedup=_fmt_metric(point.get("speedup")),
                    eff=_fmt_metric(point.get("efficiency")),
                    construct=_fmt_metric(point.get("graph_construct_ms"), 1),
                    imb=_fmt_metric(point.get("host_imbalance")),
                    msgs=_fmt_metric(point.get("gluon_num_messages_median"), 0),
                    send=_fmt_metric(send_kb, 1),
                    sanity=", ".join(sanity_bits),
                )
            )
    lines += [
        "",
        "## Methodology",
        "",
        report["justification"]["model"],
        "",
        report["justification"]["metrics"],
        "",
    ]
    path.write_text("\n".join(lines) + "\n")


def cmd_report(args: argparse.Namespace) -> None:
    src = Path(args.input) if args.input else config.RESULTS_DIR / "recent" / "report.json"
    report = json.loads(src.read_text())
    attach_scaling(report["runs"])
    attach_sanity(report["runs"])
    report["scaling"] = scaling_table(report["runs"])
    src.write_text(json.dumps(report, indent=2))
    _write_markdown(src.with_suffix(".md"), report)
    log("report", "rewrote", src.with_suffix(".md"))


def cmd_all(args: argparse.Namespace) -> None:
    cmd_build(args)
    cmd_run(args)


def _add_run_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--algo", help="comma-separated: bfs,sssp,tc,pr")
    parser.add_argument(
        "--dataset",
        help="comma-separated names, or all / large / default",
    )
    parser.add_argument("--nodes", help="comma-separated rank counts, e.g. 1,2,4,8")
    parser.add_argument("--output", help="results directory")
    parser.add_argument(
        "--profile",
        choices=("laptop", "stand"),
        default="laptop",
        help="laptop = default graphs; stand = all graphs, ignore max_nodes, 6h timeout",
    )
    parser.add_argument(
        "--ignore-max-nodes",
        action="store_true",
        help="do not skip runs above DatasetSpec.max_nodes (laptop safety cap)",
    )
    parser.add_argument("--timeout", type=int, help="seconds per DistBench process")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="skip ok points already in --output/report.json; redo errors and stale rows",
    )
    parser.add_argument(
        "--resume-from",
        help="load an existing report.json and continue into --output",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="D-Galois distributed scaling experiment (task2)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="configure and compile Galois")
    p_build.add_argument("--force", action="store_true")
    p_build.set_defaults(func=cmd_build)

    p_prep = sub.add_parser("prepare", help="download MTX and convert to .gr")
    p_prep.add_argument("--dataset", help="comma-separated names, or all / large / default")
    p_prep.add_argument("--profile", choices=("laptop", "stand"), default="laptop")
    p_prep.add_argument(
        "--force-convert",
        action="store_true",
        help="rebuild .sgr even if it already exists",
    )
    p_prep.set_defaults(func=cmd_prepare)

    p_run = sub.add_parser("run", help="run the scaling sweep")
    _add_run_flags(p_run)
    p_run.set_defaults(func=cmd_run)

    p_rep = sub.add_parser("report", help="rebuild markdown from report.json")
    p_rep.add_argument("--input", help="path to report.json")
    p_rep.set_defaults(func=cmd_report)

    p_all = sub.add_parser("all", help="build + run (honours --profile)")
    p_all.add_argument("--force", action="store_true")
    _add_run_flags(p_all)
    p_all.set_defaults(func=cmd_all)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
