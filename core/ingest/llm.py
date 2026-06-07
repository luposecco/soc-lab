from __future__ import annotations

import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from core.settings import es_url, repo_root
from core.ingest.pipeline import _PIPELINES_GEN, load_pipeline_to_es

OLLAMA_URL = "http://localhost:11434"


def ollama_ready() -> bool:
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False


def _docker_quit() -> bool:
    uname = platform.system()
    if subprocess.run(["docker", "desktop", "stop"], capture_output=True).returncode == 0:
        return True
    if uname == "Darwin":
        if subprocess.run(["osascript", "-e", 'quit app "Docker"'], capture_output=True).returncode == 0:
            return True
    if Path("/proc/version").exists() and "microsoft" in Path("/proc/version").read_text().lower():
        if subprocess.run(["powershell.exe", "-NoProfile", "-Command", "Stop-Process -Name 'Docker Desktop' -Force"], capture_output=True).returncode == 0:
            return True
    for svc in ["docker-desktop", "docker"]:
        if subprocess.run(["systemctl", "--user", "stop", svc], capture_output=True).returncode == 0:
            return True
    return False


def _docker_restore() -> bool:
    uname = platform.system()
    if subprocess.run(["docker", "desktop", "start"], capture_output=True).returncode == 0:
        pass
    elif uname == "Darwin":
        subprocess.run(["open", "-a", "Docker"], capture_output=True)
    elif Path("/proc/version").exists() and "microsoft" in Path("/proc/version").read_text().lower():
        subprocess.run(["powershell.exe", "-NoProfile", "-Command", "Start-Process 'Docker Desktop'"], capture_output=True)
    else:
        subprocess.run(["systemctl", "--user", "start", "docker-desktop"], capture_output=True)
        subprocess.run(["systemctl", "start", "docker"], capture_output=True)

    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if subprocess.run(["docker", "info"], capture_output=True).returncode == 0:
            break
        time.sleep(2)
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        return False

    subprocess.run([sys.executable, "-c", "from core.stack.runtime import compose_up; compose_up()"], capture_output=True)
    deadline2 = time.monotonic() + 240
    while time.monotonic() < deadline2:
        try:
            r = httpx.get(f"{es_url()}/_cluster/health", timeout=5.0)
            if r.is_success:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def generate_pipeline_ai(work_file: Path, pipeline_name: str, llm_ram_mode: str = "none") -> Path:
    from core.ingest import pipeline_gen

    if not ollama_ready():
        raise RuntimeError(f"Ollama is required for --build-pipeline and must be running at {OLLAMA_URL}")

    model = pipeline_gen.choose_model()
    if not model:
        raise RuntimeError("No suitable 7B/8B Ollama model found. Install one (e.g.: ollama pull qwen2.5-coder:7b)")

    out_dir = _PIPELINES_GEN()
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{pipeline_name}.yml"

    tmp_samples = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
    with open(work_file, errors="replace") as f:
        non_blank = (ln for ln in f if ln.strip())
        for i, ln in enumerate(non_blank):
            if i >= 20:
                break
            tmp_samples.write(ln.encode())
    tmp_samples.close()
    samples_path = Path(tmp_samples.name)

    validate_es = llm_ram_mode != "quit-docker"
    if llm_ram_mode == "quit-docker":
        _docker_quit()

    orig_val = pipeline_gen.VALIDATE_WITH_ES
    pipeline_gen.VALIDATE_WITH_ES = validate_es
    try:
        lines = pipeline_gen.read_samples(str(samples_path))
        pipeline = pipeline_gen.generate_grok_pipeline(lines, pipeline_name, model)
    finally:
        pipeline_gen.unload_model(model)
        pipeline_gen.VALIDATE_WITH_ES = orig_val
        samples_path.unlink(missing_ok=True)

    if llm_ram_mode == "quit-docker":
        if not _docker_restore():
            raise RuntimeError("Docker/Lab restore failed after generation")

    import yaml  # type: ignore[import-untyped]
    out.write_text(yaml.dump(pipeline, default_flow_style=False, sort_keys=False))
    return out
