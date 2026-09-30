#!/usr/bin/env python3
from __future__ import annotations

import os
import socket
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def log(scope: str, status: str, *args) -> None:
    print(f"[{scope} | {status}]", *args, flush=True)


def sanitized_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Drop Cursor AppImage variables that break CMake and MPI.

    Cursor sets APPDIR, so CMake looks for modules inside the AppImage mount
    and fails with 'Could not find CMAKE_ROOT'. LD_LIBRARY_PATH from the same
    mount can also shadow the system MPI/GCC libraries.
    """
    env = os.environ.copy()
    for key in ("APPDIR", "APPIMAGE", "OWD", "ARGV0"):
        env.pop(key, None)

    cursor_prefixes = (
        "/tmp/.mount_Cursor",
        "/tmp/.mount_cursor",
    )

    def _clean_path(value: str) -> str:
        parts = []
        for part in value.split(":"):
            if any(part.startswith(prefix) for prefix in cursor_prefixes):
                continue
            parts.append(part)
        return ":".join(parts)

    for key in ("PATH", "LD_LIBRARY_PATH", "LD_PRELOAD"):
        if key in env:
            cleaned = _clean_path(env[key])
            if cleaned:
                env[key] = cleaned
            else:
                env.pop(key, None)

    if extra:
        env.update(extra)
    return env


def run(
    args: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    log("subprocess", "run", " ".join(str(a) for a in args))
    return subprocess.run(
        list(map(str, args)),
        cwd=None if cwd is None else str(cwd),
        env=sanitized_env(env),
        check=check,
        timeout=timeout,
        text=True,
    )


def capture(
    args: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    log("subprocess", "capture", " ".join(str(a) for a in args))
    return subprocess.run(
        list(map(str, args)),
        cwd=None if cwd is None else str(cwd),
        env=sanitized_env(env),
        check=False,
        timeout=timeout,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def which(name: str) -> str | None:
    from shutil import which as _which

    return _which(name)


def _read_first(path: Path) -> str:
    try:
        return path.read_text(errors="replace").strip()
    except OSError:
        return ""


def collect_host_info() -> dict[str, Any]:
    """Snapshot of the machine that produced a results directory."""
    meminfo: dict[str, str] = {}
    for line in _read_first(Path("/proc/meminfo")).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meminfo[key.strip()] = value.strip()
    model = ""
    for line in _read_first(Path("/proc/cpuinfo")).splitlines():
        if line.lower().startswith("model name"):
            model = line.split(":", 1)[1].strip()
            break
    uname = ""
    try:
        uname = subprocess.check_output(["uname", "-a"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        uname = ""
    return {
        "hostname": socket.gethostname(),
        "uname": uname,
        "cpu_model": model,
        "cpu_count": os.cpu_count(),
        "mem_total": meminfo.get("MemTotal"),
        "mem_available": meminfo.get("MemAvailable"),
    }


def git_rev(path: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
