#!/usr/bin/env python3
"""Configure and build D-Galois distributed analytics + graph-convert."""

from __future__ import annotations

from pathlib import Path

import config
from util import log, run, which

TARGETS = [
    "graph-convert",
    "bfs-push-dist",
    "sssp-push-dist",
    "pagerank-pull-dist",
    "triangle-counting-dist",
]


def _cmake_env() -> dict[str, str]:
    # APPDIR is stripped in util.sanitized_env. Keep this hook for extra flags.
    return {}


def _fmt_available() -> bool:
    probe = config.THIRD_PARTY / "fmt" / "lib" / "cmake" / "fmt"
    if probe.exists():
        return True
    try:
        result = run(
            ["pkg-config", "--exists", "fmt"],
            check=False,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _bootstrap_fmt() -> Path | None:
    """Install {fmt} locally. Galois requires find_package(fmt)."""
    prefix = config.THIRD_PARTY / "fmt"
    cmake_dir = prefix / "lib" / "cmake" / "fmt"
    if cmake_dir.exists():
        return prefix
    src = config.THIRD_PARTY / "fmt-src"
    src.parent.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        log("build", "fmt", "cloning fmt 10.2.1")
        run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                "10.2.1",
                "https://github.com/fmtlib/fmt.git",
                str(src),
            ]
        )
    build = config.THIRD_PARTY / "fmt-build"
    build.mkdir(parents=True, exist_ok=True)
    env = _cmake_env()
    run(
        [
            "cmake",
            "-S",
            str(src),
            "-B",
            str(build),
            "-DCMAKE_BUILD_TYPE=Release",
            "-DCMAKE_INSTALL_PREFIX=" + str(prefix),
            "-DFMT_TEST=OFF",
            "-DFMT_DOC=OFF",
        ],
        env=env,
    )
    run(
        ["cmake", "--build", str(build), "--parallel", str(config.BUILD_JOBS)],
        env=env,
    )
    run(["cmake", "--install", str(build)], env=env)
    return prefix


def configure() -> None:
    if not config.GALOIS_SRC.exists():
        raise FileNotFoundError(
            f"Galois submodule missing at {config.GALOIS_SRC}. "
            "Run: git submodule update --init task2/deps/Galois"
        )
    if which("cmake") is None:
        raise RuntimeError("cmake is not on PATH")
    if which("mpicc") is None:
        raise RuntimeError("MPI compiler (mpicc) is not on PATH")

    prefix_path: list[str] = []
    if not _fmt_available():
        log("build", "fmt", "system fmt not found, bootstrapping local copy")
        local_fmt = _bootstrap_fmt()
        if local_fmt is not None:
            prefix_path.append(str(local_fmt))

    config.BUILD_DIR.mkdir(parents=True, exist_ok=True)
    cmake_args = [
        "cmake",
        "-S",
        str(config.GALOIS_SRC),
        "-B",
        str(config.BUILD_DIR),
        "-DCMAKE_BUILD_TYPE=Release",
        "-DGALOIS_ENABLE_DIST=1",
        "-DGALOIS_COMM_STATS=1",
        "-DBUILD_TESTING=OFF",
        # GCC 15 no longer transitively includes <cstdint>. Galois 6.0 is older.
        "-DCMAKE_CXX_FLAGS=-include cstdint",
    ]
    if prefix_path:
        cmake_args.append("-DCMAKE_PREFIX_PATH=" + ";".join(prefix_path))
    log("build", "configure", config.BUILD_DIR)
    run(cmake_args, env=_cmake_env())


def build(force_configure: bool = False) -> None:
    cache = config.BUILD_DIR / "CMakeCache.txt"
    if force_configure or not cache.exists():
        configure()
    missing = [t for t in TARGETS if not _target_exists(t)]
    if not missing and not force_configure:
        log("build", "skip", "all targets already exist")
        return
    log("build", "compile", *TARGETS)
    run(
        [
            "cmake",
            "--build",
            str(config.BUILD_DIR),
            "--parallel",
            str(config.BUILD_JOBS),
            "--target",
            *TARGETS,
        ],
        env=_cmake_env(),
    )
    still_missing = [t for t in TARGETS if not _target_exists(t)]
    if still_missing:
        raise RuntimeError(f"failed to build: {still_missing}")


def _target_exists(target: str) -> bool:
    if target == "graph-convert":
        return config.graph_convert().is_file()
    mapping = {
        "bfs-push-dist": config.algo_binary("bfs"),
        "sssp-push-dist": config.algo_binary("sssp"),
        "pagerank-pull-dist": config.algo_binary("pr"),
        "triangle-counting-dist": config.algo_binary("tc"),
    }
    return mapping[target].is_file()
