#!/usr/bin/env python3
"""Experiment 2 configuration: D-Galois strong scaling on simulated nodes."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parent.parent
GALOIS_SRC = ROOT / "deps" / "Galois"
BUILD_DIR = ROOT / "build"
DATASET_DIR = ROOT / "dataset"
RESULTS_DIR = ROOT / "results"
THIRD_PARTY = ROOT / "third_party"

# Prefer already-downloaded SuiteSparse archives from task1.
LOCAL_DATASET_ROOTS = [
    ROOT.parent / "task1" / "results" / "graphs-theory-datasets",
    ROOT.parent / "task1" / "spla-bench" / "dataset",
]

DATASET_URL_BASE = (
    "http://media.githubusercontent.com/media/VyacheslavIurevich/graphs-theory-datasets/main"
)


def _cpu_count() -> int:
    return os.cpu_count() or 1


# Full-run curve on i5-1135G7 (4 cores / 8 threads, ~40 GiB).
# OpenMPI counts cores as slots unless mpirun gets --use-hwthread-cpus.
# P=4 = 4 compute + 4 Gluon comm = 8 HW threads (honest fill).
# P=8 = 16 software threads on 8 HW threads. MPI slots match (8), so the
# run starts; the oversubscribe is the extra Gluon thread per rank.
FULL_NODE_COUNTS = (1, 2, 4, 8)
# 4 h per DistBench process. After dropping Orkut the longest point is
# coPapersDBLP TC, about 25 min of kernel at P=1 for 22 runs.
FULL_TIMEOUT_SEC = 14400
# DistBFS/DistSSSP default cap is 1000. belgium_osm already needs ~800 rounds.
BFS_SSSP_MAX_ITERATIONS = 10000
# Hit the old default cap → resume must redo the point after raising the limit.
BFS_SSSP_DEFAULT_CAP = 1000


def default_node_counts() -> list[int]:
    """Powers of two up to the number of hardware threads.

    Each MPI rank is one simulated node with -t=1. Using more ranks than
    threads oversubscribes the CPU and is no longer a node-scaling experiment.
    """
    n = _cpu_count()
    counts = [p for p in (1, 2, 4, 8, 16, 32) if p <= n]
    if n not in counts:
        counts.append(n)
    return counts


def full_node_counts() -> list[int]:
    n = _cpu_count()
    counts = [p for p in FULL_NODE_COUNTS if p <= n]
    if not counts:
        counts = [1]
    if n not in counts:
        counts.append(n)
    return counts


def all_datasets() -> list[DatasetSpec]:
    return list(DATASETS.values())


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    directed: bool
    vertices: int
    edges: int
    nnz: int
    family: str
    why: str
    # Approximate RAM class for one copy of the graph in Galois CSR.
    min_ram_gb: float
    default: bool
    tc: bool
    # 0-based source from task1 cache when known; None => compute or 0.
    source: int | None = None
    max_nodes: int | None = None

    @property
    def url(self) -> str:
        return f"{DATASET_URL_BASE}/{self.name}.tar.gz?download=1"


# Full SuiteSparse list from task1/spla-bench/scripts/config.py DATASET_URL,
# plus the directed graphs that task1 dropped because spla symmetrizes MTX.
DATASETS: dict[str, DatasetSpec] = {
    "coAuthorsCiteseer": DatasetSpec(
        name="coAuthorsCiteseer",
        directed=False,
        vertices=227_320,
        edges=814_134,
        nnz=1_628_268,
        family="collaboration",
        why=(
            "Small undirected co-authorship graph from task1. Lower bound: "
            "when the graph is tiny, Gluon/MPI overhead should dominate and "
            "efficiency should fall. Also the smoke-test input."
        ),
        min_ram_gb=0.5,
        default=True,
        tc=True,
        source=4,
    ),
    "amazon-2008": DatasetSpec(
        name="amazon-2008",
        directed=True,
        vertices=735_323,
        edges=5_158_388,
        nnz=5_158_388,
        family="web",
        why=(
            "Directed web graph excluded from task1 because stock spla "
            "examples symmetrize Matrix Market input. Galois DistGraph keeps "
            "direction, so this is the smallest honest digraph for BFS/SSSP/PR."
        ),
        min_ram_gb=1.0,
        default=True,
        tc=False,
        source=181919,
    ),
    "belgium_osm": DatasetSpec(
        name="belgium_osm",
        directed=False,
        vertices=1_441_295,
        edges=1_549_970,
        nnz=3_099_940,
        family="road",
        why=(
            "High-diameter road network from task1. BFS/SSSP produce many "
            "narrow BSP rounds; scaling is limited by round latency, not by "
            "edge volume. Contrasts with power-law social graphs."
        ),
        min_ram_gb=1.5,
        default=True,
        tc=True,
        source=0,
    ),
    "coPapersDBLP": DatasetSpec(
        name="coPapersDBLP",
        directed=False,
        vertices=540_486,
        edges=15_245_729,
        nnz=30_491_458,
        family="collaboration",
        why=(
            "Dense undirected co-citation graph from task1. High average "
            "degree stresses triangle counting and edge-cut communication "
            "volume without requiring tens of millions of vertices."
        ),
        min_ram_gb=3.0,
        default=False,
        tc=True,
        source=21,
        max_nodes=4,
    ),
    "roadNet-CA": DatasetSpec(
        name="roadNet-CA",
        directed=False,
        vertices=1_971_281,
        edges=2_766_607,
        nnz=5_533_214,
        family="road",
        why=(
            "Larger SNAP road network from task1. Same high-diameter family "
            "as belgium_osm, used to check that the diameter effect is not "
            "an artefact of one country-sized OSM extract."
        ),
        min_ram_gb=2.0,
        default=False,
        tc=True,
        source=0,
    ),
    "cit-Patents": DatasetSpec(
        name="cit-Patents",
        directed=True,
        vertices=3_774_768,
        edges=16_518_948,
        nnz=16_518_948,
        family="citation",
        why=(
            "Directed patent-citation DAG excluded from task1. Tests BFS/PR "
            "on a large acyclic-ish digraph, where frontier growth differs "
            "from undirected social graphs."
        ),
        min_ram_gb=4.0,
        default=False,
        tc=False,
        source=None,
        max_nodes=4,
    ),
    "rgg_n_2_22_s0": DatasetSpec(
        name="rgg_n_2_22_s0",
        directed=False,
        vertices=4_194_304,
        edges=30_359_198,
        nnz=60_718_396,
        family="geometric",
        why=(
            "Random geometric graph from task1. Vertices have spatial "
            "locality, so an outgoing edge-cut should cut few edges. This is "
            "the optimistic case for distributed scaling."
        ),
        min_ram_gb=6.0,
        default=False,
        tc=True,
        source=1,
        max_nodes=2,
    ),
    "soc-LiveJournal1": DatasetSpec(
        name="soc-LiveJournal1",
        directed=True,
        vertices=4_847_571,
        edges=68_993_773,
        nnz=68_993_773,
        family="social",
        why=(
            "Directed social network excluded from task1. Power-law degrees "
            "make edge-cut partitions unbalanced; used to show when adding "
            "nodes does not help."
        ),
        min_ram_gb=8.0,
        default=False,
        tc=False,
        source=None,
        max_nodes=2,
    ),
}

# Dropped from this run, hours are the 22-run × P=1,2,4,8 estimate:
# rgg_n_2_23_s0 — same locality as rgg_n_2_22_s0, ~13 h; BFS/SSSP hit 1000 rounds.
# road_central — same diameter story as belgium_osm, ~12 h; BFS/SSSP hit 1000 rounds.
# com-Orkut — extreme degree skew and the long TC, ~21 h. coPapersDBLP keeps TC.

# Present in task1 DATASET_URL but not in the default experiment:
# hollywood-2009 — undirected; dropped in task1 because LAGraph BFS crashed.
# indochina-2004 — huge web crawl; dropped because it did not finish.
# They are not the "excluded digraphs". Keep URLs available if needed later.
OPTIONAL_URLS = {
    "hollywood-2009": f"{DATASET_URL_BASE}/hollywood-2009.tar.gz?download=1",
    "indochina-2004": f"{DATASET_URL_BASE}/indochina-2004.tar.gz?download=1",
}


class AlgorithmSpec(TypedDict):
    target: str
    variant: str
    region: str
    needs_transpose: bool
    needs_weights: bool
    needs_symmetric: bool
    why_variant: str


ALGORITHMS: dict[str, AlgorithmSpec] = {
    "bfs": {
        "target": "bfs-push-dist",
        "variant": "push",
        "region": "BFS",
        "needs_transpose": True,
        "needs_weights": False,
        "needs_symmetric": False,
        "why_variant": ("Galois distributed README: push BFS outperforms pull on CPU."),
    },
    "sssp": {
        "target": "sssp-push-dist",
        "variant": "push",
        "region": "SSSP",
        "needs_transpose": True,
        "needs_weights": True,
        "needs_symmetric": False,
        "why_variant": (
            "Galois distributed README: push SSSP outperforms pull on CPU. "
            "Unit edge weights keep the problem comparable to task1."
        ),
    },
    "pr": {
        "target": "pagerank-pull-dist",
        "variant": "pull",
        "region": "PageRank",
        "needs_transpose": True,
        "needs_weights": False,
        "needs_symmetric": False,
        "why_variant": ("Galois distributed README: pull PageRank outperforms push."),
    },
    "tc": {
        "target": "triangle-counting-dist",
        "variant": "disttc",
        "region": "TC",
        "needs_transpose": False,
        "needs_weights": False,
        "needs_symmetric": True,
        "why_variant": (
            "Only DistTC binary. Runs on CPU despite the GPU-oriented README; "
            "tc.cpp contains a do_all CPU kernel. Requires a clean symmetric graph."
        ),
    },
}

# Partition/exec: Galois recommends OEC+Sync for <= 16 hosts.
PARTITION = "oec"
EXEC_MODEL = "Sync"
THREADS_PER_RANK = 1
INTERNAL_RUNS = 22  # Timer_0 warmup, Timer_1..21 measured
PR_MAX_ITERATIONS = 20
PR_TOLERANCE = 1e-12  # effectively force the iteration cap
TIMEOUT_SEC = 1800
BUILD_JOBS = max(1, _cpu_count() - 1)

# Metrics kept in the JSON summary. See README / CONTEXT for justification.
METRIC_KEYS = [
    "kernel_ms_median",
    "kernel_ms_min",
    "kernel_ms_max",
    "graph_construct_ms",
    "timer_total_ms",
    "wall_ms",
    "num_iterations_median",
    "host_imbalance",
    "peak_rss_kb",
    "gluon_send_bytes_median",
    "gluon_num_messages_median",
    "gluon_replication_factor",
    "speedup",
    "efficiency",
]


def default_datasets() -> list[DatasetSpec]:
    return [d for d in DATASETS.values() if d.default]


def large_datasets() -> list[DatasetSpec]:
    return [d for d in DATASETS.values() if not d.default]


def dataset_allowed_for_algo(spec: DatasetSpec, algo: str) -> bool:
    if algo == "tc":
        return spec.tc
    return True


def graph_convert() -> Path:
    return BUILD_DIR / "tools" / "graph-convert" / "graph-convert"


def algo_binary(algo: str) -> Path:
    target = ALGORITHMS[algo]["target"]
    folder = {
        "bfs": "bfs",
        "sssp": "sssp",
        "pr": "pagerank",
        "tc": "triangle-counting",
    }[algo]
    return BUILD_DIR / "lonestar" / "analytics" / "distributed" / folder / target
