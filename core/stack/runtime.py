from __future__ import annotations

import shutil
import subprocess
from typing import Any

from core.settings import repo_root


def _run(command: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=repo_root(), capture_output=True, text=True, check=check)


def _compose(*args: str) -> list[str]:
    return ["docker", "compose", "-f", "compose.yml", *args]


def ensure_runtime_dirs() -> list[str]:
    root = repo_root()
    paths = [
        root / "runtime" / "logs" / "suricata",
        root / "runtime" / "logs" / "rules",
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
        import json

        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows[row.get("Name", "")] = row
    return rows


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
