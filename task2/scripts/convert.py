#!/usr/bin/env python3
"""Convert MTX graphs into the Galois .gr family used by DistBench."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import config
from util import log, run


@dataclass(frozen=True)
class ConvertedGraph:
    name: str
    mtx: Path
    gr: Path
    tgr: Path
    wgr: Path
    wtgr: Path
    sgr: Path


def _convert(mode: str, src: Path, dst: Path, extra: list[str] | None = None) -> None:
    if dst.exists() and dst.stat().st_size > 0:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(config.graph_convert()), f"-{mode}"]
    if extra:
        cmd.extend(extra)
    cmd.extend([str(src), str(dst)])
    log("convert", mode, src.name, "->", dst.name)
    run(cmd)


def _parse_mtx_header(path: Path) -> tuple[bool, int, int]:
    """Return (symmetric, n_vertices, stored_nnz)."""
    symmetric = False
    stored = 0
    n_vertices = 0
    with path.open() as handle:
        first = handle.readline()
        if "symmetric" in first.lower() or "hermitian" in first.lower():
            symmetric = True
        for line in handle:
            if line.startswith("%"):
                continue
            parts = line.split()
            if len(parts) >= 3:
                n_vertices = max(int(parts[0]), int(parts[1]))
                stored = int(parts[2])
                break
    return symmetric, n_vertices, stored


def mtx_to_edgelist(mtx: Path, edgelist: Path, *, weighted: bool) -> None:
    """Write a 0-based Galois edgelist, expanding a symmetric MTX once."""
    if edgelist.exists() and edgelist.stat().st_size > 0:
        return
    symmetric, _n_vertices, _ = _parse_mtx_header(mtx)
    log("convert", "mtx2edgelist", mtx.name, "symmetric=" + str(symmetric))
    edgelist.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    max_id = -1
    with mtx.open() as src, edgelist.open("w") as dst:
        for line in src:
            if line.startswith("%"):
                continue
            break
        for line in src:
            parts = line.split()
            if len(parts) < 2:
                continue
            src_id = int(parts[0]) - 1
            dst_id = int(parts[1]) - 1
            if src_id < 0 or dst_id < 0:
                continue
            if src_id == dst_id:
                continue
            max_id = max(max_id, src_id, dst_id)
            if weighted:
                dst.write(f"{src_id} {dst_id} 1\n")
            else:
                dst.write(f"{src_id} {dst_id}\n")
            written += 1
            if symmetric:
                if weighted:
                    dst.write(f"{dst_id} {src_id} 1\n")
                else:
                    dst.write(f"{dst_id} {src_id}\n")
                written += 1
        # edgelist2gr infers |V| = max(id)+1. Do not pad trailing isolates
        # with a self-loop: DistTC's MiningPartitioner asserts
        # globalKeptEdges*2 == |E| and a loop makes |E| odd. Isolated
        # trailing vertices do not change BFS/SSSP/TC answers.
    log("convert", "mtx2edgelist", f"wrote {written} directed edges")


def convert_dataset(name: str, mtx: Path, *, force: bool = False) -> ConvertedGraph:
    base = config.DATASET_DIR / name / name
    graph = ConvertedGraph(
        name=name,
        mtx=mtx,
        gr=base.with_suffix(".gr"),
        tgr=base.with_suffix(".tgr"),
        wgr=base.with_suffix(".wgr"),
        wtgr=base.with_suffix(".wtgr"),
        sgr=base.with_suffix(".sgr"),
    )
    spec = config.DATASETS[name]
    if force and spec.tc:
        for leftover in (base.with_suffix(".sgr"), base.with_suffix(".cgr")):
            if leftover.exists():
                leftover.unlink()
                log("convert", "removed", leftover.name)

    el = base.with_suffix(".el")
    wel = base.with_suffix(".wel")
    if not (graph.gr.exists() and graph.gr.stat().st_size > 0):
        mtx_to_edgelist(mtx, el, weighted=False)
        _convert("edgelist2gr", el, graph.gr, ["-edgeType=void"])
        _convert("gr2tgr", graph.gr, graph.tgr, ["-edgeType=void"])
    elif not (graph.tgr.exists() and graph.tgr.stat().st_size > 0):
        _convert("gr2tgr", graph.gr, graph.tgr, ["-edgeType=void"])

    if not (graph.wgr.exists() and graph.wgr.stat().st_size > 0):
        mtx_to_edgelist(mtx, wel, weighted=True)
        _convert("edgelist2gr", wel, graph.wgr, ["-edgeType=uint32"])
        _convert("gr2tgr", graph.wgr, graph.wtgr, ["-edgeType=uint32"])
    elif not (graph.wtgr.exists() and graph.wtgr.stat().st_size > 0):
        _convert("gr2tgr", graph.wgr, graph.wtgr, ["-edgeType=uint32"])

    if spec.tc:
        cleaned = base.with_suffix(".cgr")
        if not (graph.sgr.exists() and graph.sgr.stat().st_size > 0):
            # Copy the already-symmetric .gr. gr2cgr can leave an odd |E|
            # (self-loop / orientation) and DistTC then SIGABRTs.
            graph.sgr.write_bytes(graph.gr.read_bytes())
            log("convert", "sgr", "copied .gr (symmetric, no gr2cgr)")
            if cleaned.exists():
                cleaned.unlink()

    _write_source_cache(graph, spec)
    # Text edgelists of Orkut-scale graphs are several GiB. The .gr family is enough.
    for extra in (el, wel, base.with_suffix(".cgr")):
        if extra.exists():
            extra.unlink()
            log("convert", "removed", extra.name)
    return graph


def _write_source_cache(graph: ConvertedGraph, spec: config.DatasetSpec) -> None:
    cache = graph.gr.with_name("source.txt")
    if spec.source is not None:
        cache.write_text(str(spec.source) + "\n")
        return
    if spec.directed and spec.family == "citation":
        # Median out-degree on cit-Patents landed in a 26-vertex out-component.
        source = pick_max_out_from_mtx(graph.mtx)
        cache.write_text(str(source) + "\n")
        log("convert", "source", graph.name, source, "(max out-degree)")
        return
    if cache.exists() and cache.stat().st_size > 0:
        return
    source = pick_source_from_edgelist(graph.gr.with_suffix(".el"))
    cache.write_text(str(source) + "\n")
    log("convert", "source", graph.name, source)


def pick_max_out_from_mtx(mtx: Path) -> int:
    """0-based vertex with the largest out-degree in the MTX (no symmetrize)."""
    outdeg: dict[int, int] = {}
    with mtx.open() as handle:
        for line in handle:
            if line.startswith("%"):
                continue
            break
        for line in handle:
            parts = line.split()
            if len(parts) < 2:
                continue
            src_id = int(parts[0]) - 1
            dst_id = int(parts[1]) - 1
            if src_id < 0 or dst_id < 0 or src_id == dst_id:
                continue
            outdeg[src_id] = outdeg.get(src_id, 0) + 1
    if not outdeg:
        return 0
    return max(outdeg, key=lambda vertex: (outdeg[vertex], vertex))


def pick_source_from_edgelist(edgelist: Path) -> int:
    """Median out-degree among vertices with at least one real out-edge."""
    outdeg: dict[int, int] = {}
    if not edgelist.exists():
        return 0
    with edgelist.open() as handle:
        for line in handle:
            parts = line.split()
            if len(parts) < 2:
                continue
            src_id = int(parts[0])
            dst_id = int(parts[1])
            if src_id == dst_id:
                continue
            outdeg[src_id] = outdeg.get(src_id, 0) + 1
    if not outdeg:
        return 0
    ranked = sorted(outdeg, key=lambda vertex: (outdeg[vertex], vertex))
    return ranked[len(ranked) // 2]


def cached_source(graph: ConvertedGraph) -> int | None:
    cache = graph.gr.with_name("source.txt")
    if cache.exists():
        text = cache.read_text().strip()
        if text:
            return int(text)
    return None
