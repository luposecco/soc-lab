from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.settings import repo_root


def _rules_log_dir() -> Path:
    return repo_root() / "runtime" / "logs" / "rules"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_runtime_dirs() -> None:
    _rules_log_dir().mkdir(parents=True, exist_ok=True)
    (repo_root() / ".soc-lab").mkdir(parents=True, exist_ok=True)


def count_suricata_rules() -> tuple[int, int]:
    et = subprocess.run(
        ["docker", "exec", "suricata", "sh", "-c",
         "grep -hE 'sid:[[:space:]]*[0-9]+' /var/lib/suricata/rules/*.rules 2>/dev/null | wc -l"],
        capture_output=True, text=True,
    )
    custom = subprocess.run(
        ["docker", "exec", "suricata", "sh", "-c",
         "grep -r --include='*.rules' -hE 'sid:[[:space:]]*[0-9]+' /etc/suricata/rules/custom/ 2>/dev/null | wc -l"],
        capture_output=True, text=True,
    )
    return int(et.stdout.strip() or 0), int(custom.stdout.strip() or 0)


def write_status(
    suricata_status: str,
    sigma_status: str,
    sigma_ok: int,
    sigma_fail: int,
    et_rules: int,
    custom_rules: int,
    sigma_total: int,
) -> None:
    now = _now_iso()
    data = {
        "updated_at": now,
        "suricata": {
            "status": suricata_status,
            "last_check": now,
            "et_rules": et_rules,
            "custom_rules": custom_rules,
            "error_log": "runtime/logs/rules/suricata-compile.log",
        },
        "sigma": {
            "status": sigma_status,
            "last_check": now,
            "loaded_rules": sigma_total,
            "ok_count": sigma_ok,
            "fail_count": sigma_fail,
            "error_log": "runtime/logs/rules/sigma-compile.log",
        },
    }
    (_rules_log_dir() / "status.json").write_text(json.dumps(data, indent=2))


def compile_suricata() -> dict[str, Any]:
    log_path = _rules_log_dir() / "suricata-compile.log"
    result = subprocess.run(
        ["docker", "exec", "suricata", "suricata", "-T", "-c", "/etc/suricata/suricata.yaml"],
        capture_output=True, text=True,
    )
    output = result.stdout + result.stderr
    # suricata exits 1 when custom dir is empty (just a warning, not a real failure)
    no_rules_warning = "No rule files match the pattern" in output
    ok = result.returncode == 0 or (result.returncode == 1 and no_rules_warning
                                     and "error" not in output.lower().split("no rule")[0].lower())
    with open(log_path, "w") as fh:
        fh.write(f"[{_now_iso()}] Running Suricata rule compile check\n")
        fh.write(output)
        fh.write(f"[{_now_iso()}] Result: {'ok' if ok else 'fail'} (exit {result.returncode})\n")
    return {"ok": ok, "log": str(log_path)}


def compile_sigma() -> dict[str, Any]:
    sigma_dir = repo_root() / "data" / "rules" / "sigma"
    log_path = _rules_log_dir() / "sigma-compile.log"
    ok_count = fail_count = total_count = 0

    with open(log_path, "w") as log_fh:
        for rule_file in sorted(sigma_dir.rglob("*.yml")):
            total_count += 1
            rel_path = rule_file.relative_to(sigma_dir)
            result = subprocess.run(
                ["docker", "exec", "elastalert2", "sigma", "convert",
                 "-t", "elastalert", "--without-pipeline", f"/opt/sigma/rules/{rel_path.as_posix()}"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                ok_count += 1
            else:
                fail_count += 1
                log_fh.write(f"[{_now_iso()}] sigma conversion failed: {rel_path.as_posix()}\n")
                if result.stderr:
                    log_fh.write(result.stderr)
        log_fh.write(f"[{_now_iso()}] sigma compile summary: ok={ok_count} fail={fail_count}\n")

    return {
        "ok": fail_count == 0,
        "ok_count": ok_count,
        "fail_count": fail_count,
        "total_count": total_count,
        "log": str(log_path),
    }


def compile() -> dict[str, Any]:
    _ensure_runtime_dirs()
    from api.routes.rules import _clear_suricata_count_caches, _get_suricata_error_count

    if subprocess.run(["docker", "exec", "suricata", "true"], capture_output=True).returncode != 0:
        raise RuntimeError("Suricata container not running (use: soc-lab stack start)")
    if subprocess.run(["docker", "exec", "elastalert2", "true"], capture_output=True).returncode != 0:
        raise RuntimeError("ElastAlert2 container not running (use: soc-lab stack start)")

    suricata_result = compile_suricata()
    suricata_status = "ok" if suricata_result["ok"] else "fail"
    et_count = custom_count = 0
    if suricata_result["ok"]:
        et_count, custom_count = count_suricata_rules()

    sigma_result = compile_sigma()
    sigma_status = "ok" if sigma_result["ok"] else "fail"
    _clear_suricata_count_caches()
    suricata_error_count = _get_suricata_error_count()

    write_status(
        suricata_status, sigma_status,
        sigma_result["ok_count"], sigma_result["fail_count"],
        et_count, custom_count, sigma_result["total_count"],
    )
    return {
        "suricata": {**suricata_result, "et_rules": et_count, "custom_rules": custom_count, "error_count": suricata_error_count},
        "sigma": sigma_result,
        "status_file": str(_rules_log_dir() / "status.json"),
    }


def _dir_hash(path: Path, glob: str) -> str:
    parts = sorted(f"{f} {f.stat().st_mtime_ns}" for f in path.glob(glob) if f.is_file())
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()


def watch_loop() -> None:
    _ensure_runtime_dirs()
    root = repo_root()
    watcher_log = _rules_log_dir() / "watcher.log"
    status_file = _rules_log_dir() / "status.json"
    prev_suricata = prev_sigma = ""

    while True:
        cur_suricata = _dir_hash(root / "data" / "rules" / "suricata", "*.rules")
        cur_sigma = _dir_hash(root / "data" / "rules" / "sigma", "*.yml")
        if cur_suricata != prev_suricata or cur_sigma != prev_sigma or not status_file.exists():
            with open(watcher_log, "a") as fh:
                fh.write(f"[{_now_iso()}] Rule change detected. Running compile checks.\n")
            try:
                compile()
            except Exception as exc:
                with open(watcher_log, "a") as fh:
                    fh.write(f"[{_now_iso()}] compile error: {exc}\n")
            prev_suricata = cur_suricata
            prev_sigma = cur_sigma
        time.sleep(2)


def watch_start() -> dict[str, Any]:
    _ensure_runtime_dirs()
    pid_file = repo_root() / ".soc-lab" / "rules-watcher.pid"

    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            return {"ok": True, "message": f"Rules watcher already running (pid: {pid})", "pid": pid}
        except (ProcessLookupError, ValueError):
            pid_file.unlink(missing_ok=True)

    if _is_wsl() and not _systemd_available():
        return {"ok": True, "message": "WSL detected without systemd: rules watcher not started. Run manual compile checks with: soc-lab rules compile"}

    watcher_log = _rules_log_dir() / "watcher.log"
    proc = subprocess.Popen(
        [sys.executable, "-c", "from core.rules.compile import watch_loop; watch_loop()"],
        stdout=open(watcher_log, "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    pid_file.write_text(str(proc.pid))
    return {"ok": True, "message": f"Rules watcher started (pid: {proc.pid})", "pid": proc.pid}


def watch_stop() -> dict[str, Any]:
    pid_file = repo_root() / ".soc-lab" / "rules-watcher.pid"
    if not pid_file.exists():
        return {"ok": True, "message": "Rules watcher not running"}
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        pid_file.unlink(missing_ok=True)
        return {"ok": True, "message": f"Rules watcher stopped (pid: {pid})", "pid": pid}
    except (ProcessLookupError, ValueError):
        pid_file.unlink(missing_ok=True)
        return {"ok": True, "message": "Rules watcher not running"}


def _is_wsl() -> bool:
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except Exception:
        return False


def _systemd_available() -> bool:
    try:
        result = subprocess.run(["ps", "-p", "1", "-o", "comm="], capture_output=True, text=True)
        return result.stdout.strip() == "systemd"
    except Exception:
        return False
