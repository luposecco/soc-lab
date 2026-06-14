from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from typing import Any

from core.settings import repo_root

_DOCKER_STATS_TTL_SECS = 5.0
_DOCKER_STATS_LOCK_STALE_SECS = 30.0
_docker_stats_refresh_lock = threading.Lock()
_docker_stats_refresh_thread: threading.Thread | None = None


def _docker_stats_cache_dir() -> Any:
    return repo_root() / "runtime" / "cache"


def _docker_stats_cache_paths() -> tuple[Any, Any]:
    cache_dir = _docker_stats_cache_dir()
    return (
        cache_dir / "docker-stats.current.json",
        cache_dir / "docker-stats.previous.json",
    )


def _docker_stats_lock_path() -> Any:
    return _docker_stats_cache_dir() / "docker-stats.refresh.lock"


def _read_docker_stats_cache(path: Any) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    stats = data.get("stats")
    updated_at = data.get("updated_at")
    if not isinstance(stats, dict):
        return None
    if not isinstance(updated_at, (int, float)):
        return None
    return {"stats": stats, "updated_at": float(updated_at)}


def docker_stats_cache_meta() -> dict[str, Any]:
    current_path, previous_path = _docker_stats_cache_paths()
    current = _read_docker_stats_cache(current_path)
    if current:
        return {
            "source": "current",
            "updated_at": current["updated_at"],
            "age_seconds": max(0.0, time.time() - current["updated_at"]),
            "path": str(current_path),
        }
    previous = _read_docker_stats_cache(previous_path)
    if previous:
        return {
            "source": "previous",
            "updated_at": previous["updated_at"],
            "age_seconds": max(0.0, time.time() - previous["updated_at"]),
            "path": str(previous_path),
        }
    return {"source": "none", "updated_at": None, "age_seconds": None, "path": str(current_path)}


def _write_docker_stats_cache(stats: dict[str, dict[str, str]]) -> None:
    current_path, previous_path = _docker_stats_cache_paths()
    current = _read_docker_stats_cache(current_path)
    current_path.parent.mkdir(parents=True, exist_ok=True)
    if current_path.exists() and current is not None:
        current_path.replace(previous_path)

    payload = {"updated_at": time.time(), "stats": stats}
    tmp_path = current_path.parent / f"docker-stats.{os.getpid()}.{time.time_ns()}.tmp.json"
    tmp_path.write_text(json.dumps(payload))
    os.replace(tmp_path, current_path)


def _try_acquire_docker_stats_refresh_lock() -> bool:
    lock_path = _docker_stats_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if lock_path.exists() and time.time() - lock_path.stat().st_mtime > _DOCKER_STATS_LOCK_STALE_SECS:
            lock_path.unlink()
    except FileNotFoundError:
        pass
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    try:
        os.write(fd, str(os.getpid()).encode())
    finally:
        os.close(fd)
    return True


def _release_docker_stats_refresh_lock() -> None:
    try:
        _docker_stats_lock_path().unlink()
    except FileNotFoundError:
        pass


def _refresh_docker_stats_once() -> None:
    if not _try_acquire_docker_stats_refresh_lock():
        return
    try:
        fresh = _collect_docker_stats()
        if fresh:
            _write_docker_stats_cache(fresh)
    finally:
        _release_docker_stats_refresh_lock()


def _refresh_docker_stats_async() -> None:
    global _docker_stats_refresh_thread
    with _docker_stats_refresh_lock:
        if _docker_stats_refresh_thread and _docker_stats_refresh_thread.is_alive():
            return
        thread = threading.Thread(target=_refresh_docker_stats_once, name="docker-stats-refresh", daemon=True)
        _docker_stats_refresh_thread = thread
        thread.start()


def _collect_docker_stats() -> dict[str, dict[str, str]]:
    result = _run(
        [
            "docker",
            "stats",
            "--no-stream",
            "--format",
            "{{json .}}",
        ],
        check=False,
    )
    if result.returncode != 0:
        return {}
    rows: dict[str, dict[str, str]] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows[row.get("Name", "")] = row
    return rows


def _run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=repo_root(), capture_output=True, text=True, check=check)


def _compose(*args: str) -> list[str]:
    return ["docker", "compose", "-f", "compose.yml", *args]


def ensure_runtime_dirs() -> list[str]:
    root = repo_root()
    paths = [
        root / "runtime" / "logs" / "suricata",
        root / "runtime" / "logs" / "rules",
        root / "runtime" / "cache",
        root / "data" / "samples",
        root / "data" / "pcap",
        root / "data" / "rules" / "suricata",
        root / "data" / "rules" / "sigma",
    ]
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
    return [str(path) for path in paths]


def compose_up() -> dict[str, Any]:
    ensure_runtime_dirs()
    result = _run(["docker", "compose", "up", "-d"])
    return {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}


def compose_up_service(service: str) -> dict[str, Any]:
    result = _run(["docker", "compose", "up", "-d", service])
    return {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr, "service": service}


def compose_down(remove_volumes: bool = False) -> dict[str, Any]:
    command = ["docker", "compose", "down"]
    if remove_volumes:
        command.append("-v")
    result = _run(command)
    return {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr}


def compose_stop_service(service: str) -> dict[str, Any]:
    result = _run(["docker", "compose", "stop", service])
    return {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr, "service": service}


def compose_restart_service(service: str) -> dict[str, Any]:
    result = _run(["docker", "compose", "restart", service])
    return {"ok": result.returncode == 0, "stdout": result.stdout, "stderr": result.stderr, "service": service}


def compose_version() -> str:
    result = _run(["docker", "compose", "version"], check=False)
    return (result.stdout or result.stderr).strip()


def service_logs(service: str, tail: int = 50) -> str:
    result = _run(["docker", "logs", service, "--tail", str(tail)], check=False)
    return result.stdout + result.stderr


def docker_stats() -> dict[str, dict[str, str]]:
    current_path, previous_path = _docker_stats_cache_paths()
    current = _read_docker_stats_cache(current_path)
    now = time.time()
    if current and now - current["updated_at"] <= _DOCKER_STATS_TTL_SECS:
        return current["stats"]

    if current:
        _refresh_docker_stats_async()
        return current["stats"]
    previous = _read_docker_stats_cache(previous_path)
    if previous:
        _refresh_docker_stats_async()
        return previous["stats"]

    _refresh_docker_stats_once()
    current = _read_docker_stats_cache(current_path)
    if current:
        return current["stats"]
    previous = _read_docker_stats_cache(previous_path)
    if previous:
        return previous["stats"]
    return {}


def uninstall() -> dict[str, Any]:
    root = repo_root()
    removed: list[str] = []

    # Stop and remove containers + volumes
    r = _run(["docker", "compose", "down", "-v"], check=False)
    if r.returncode == 0:
        removed.append("docker containers + volumes")

    # Remove venv
    venv = root / ".venv"
    if venv.exists():
        shutil.rmtree(venv)
        removed.append(".venv")

    # Remove runtime artifacts
    soc_lab_dir = root / ".soc-lab"
    if soc_lab_dir.exists():
        shutil.rmtree(soc_lab_dir)
        removed.append(".soc-lab")

    # Remove generated pipelines
    gen_pipelines = root / "data" / "pipelines" / "generated"
    if gen_pipelines.exists():
        shutil.rmtree(gen_pipelines)
        removed.append("pipelines/generated")

    return {"ok": True, "removed": removed}
