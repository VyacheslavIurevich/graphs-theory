#!/usr/bin/env python3
"""Download SuiteSparse MTX graphs used by task1, preferring local copies."""

from __future__ import annotations

import tarfile
import urllib.request
from pathlib import Path

import config
from util import log

HEADERS = {
    "User-Agent": "graphs-theory-task2/1.0",
    "Accept": "*/*",
}


def mtx_path(name: str) -> Path:
    return config.DATASET_DIR / name / f"{name}.mtx"


def find_local_mtx(name: str) -> Path | None:
    candidates = [
        mtx_path(name),
        config.DATASET_DIR / f"{name}.mtx",
    ]
    for root in config.LOCAL_DATASET_ROOTS:
        candidates.append(root / name / f"{name}.mtx")
        candidates.append(root / f"{name}.mtx")
    for path in candidates:
        if path.is_file() and path.stat().st_size > 0:
            return path
    return None


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    log("dataset", "download", url, "->", dest)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req) as src, dest.open("wb") as out:
        while True:
            chunk = src.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)


def _extract_mtx(archive: Path, dest_mtx: Path) -> None:
    dest_mtx.parent.mkdir(parents=True, exist_ok=True)
    log("dataset", "extract", archive, "->", dest_mtx)
    with tarfile.open(archive, "r:*") as tar:
        mtx_members = sorted(
            (m for m in tar.getmembers() if m.name.endswith(".mtx")),
            key=lambda m: (len(Path(m.name).name), m.name),
        )
        if not mtx_members:
            raise RuntimeError(f"{archive} contains no .mtx file")
        chosen = mtx_members[0]
        extracted = tar.extractfile(chosen)
        if extracted is None:
            raise RuntimeError(f"cannot extract {chosen.name}")
        dest_mtx.write_bytes(extracted.read())


def ensure_mtx(name: str) -> Path:
    local = find_local_mtx(name)
    if local is not None:
        dest = mtx_path(name)
        if local.resolve() != dest.resolve():
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                log("dataset", "copy-local", local, "->", dest)
                dest.write_bytes(local.read_bytes())
            return dest
        return local

    spec = config.DATASETS.get(name)
    url = spec.url if spec else config.OPTIONAL_URLS.get(name)
    if not url:
        raise KeyError(f"unknown dataset {name}")

    config.DATASET_DIR.mkdir(parents=True, exist_ok=True)
    archive = config.DATASET_DIR / f"{name}.tar.gz"
    if not archive.exists():
        _download(url, archive)
    dest = mtx_path(name)
    if not dest.exists():
        _extract_mtx(archive, dest)
    return dest
