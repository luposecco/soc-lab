from __future__ import annotations

import json
import os
import subprocess
import time
import yaml

from fastapi import APIRouter, HTTPException, Query

from core.settings import repo_root
from api.models import RuleFileWriteRequest, RuleValidateRequest
from api.utils import bad

router = APIRouter(prefix="/api/rules")

_SURI_ACTIONS = {"alert", "pass", "drop", "reject", "rejectsrc", "rejectdst", "rejectboth"}
_suricata_count_cache: tuple[float, int] | None = None
_suricata_disabled_count_cache: tuple[float, int] | None = None
_suricata_error_count_cache: tuple[float, int] | None = None


def _clear_suricata_count_caches() -> None:
    global _suricata_count_cache, _suricata_disabled_count_cache, _suricata_error_count_cache
    _suricata_count_cache = None
    _suricata_disabled_count_cache = None
    _suricata_error_count_cache = None


# ── helpers ───────────────────────────────────────────────────────────────────

def _docker_exec(args: list[str], timeout: int = 5) -> str:
    try:
        r = subprocess.run(["docker", "exec", *args], capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except Exception:
        return ""


def _security_check(path: str) -> "Path":
    from pathlib import Path
    root = repo_root()
    target = (root / path).resolve()
    rules_root = (root / "data" / "rules").resolve()
    if not str(target).startswith(str(rules_root)):
        raise HTTPException(status_code=403, detail="Access denied: path outside rules/")
    return target


def _rule_path_parse(path: str) -> "tuple[str, int | None]":
    if "#" in path:
        base, line_str = path.rsplit("#", 1)
        try:
            return base, int(line_str)
        except ValueError:
            pass
    return path, None


# ── suricata rule grep ────────────────────────────────────────────────────────

def _parse_rule_line(line: str, file_id: str, line_no: int, source: str) -> dict | None:
    s = line.strip()
    if not s or s.startswith("#"):
        return None
    if s.split(None, 1)[0] not in _SURI_ACTIONS:
        return None
    name = sid = ""
    if "msg:" in s:
        try:
            name = s.split("msg:", 1)[1].split(";")[0].strip().strip('"')
        except Exception:
            pass
    if "sid:" in s:
        try:
            sid = s.split("sid:", 1)[1].split(";")[0].strip()
        except Exception:
            pass
    if not name:
        return None
    return {"name": name, "sid": sid, "file": f"{file_id}#{line_no}",
            "type": "suricata", "source": source, "status": "enabled"}


def _rule_matches(rule: dict, ql: str) -> bool:
    if not ql:
        return True
    return ql in rule.get("name", "").lower() or ql in rule.get("sid", "")


def _rule_has_error(raw: str) -> bool:
    """Quick check: does an enabled rule line have obvious syntax errors?"""
    s = raw.strip()
    if not s or s.startswith("#"):
        return False
    if s.split(None, 1)[0] not in _SURI_ACTIONS:
        return True
    return "msg:" not in s or "sid:" not in s or "rev:" not in s


def _yaml_rule_status(rule_type: str, content: str) -> str:
    try:
        parsed = yaml.safe_load(content)
    except Exception:
        return "error"
    if not isinstance(parsed, dict):
        return "error"
    if rule_type == "sigma":
        for field in ("title", "logsource", "detection"):
            if field not in parsed:
                return "error"
    return "enabled"


def _grep_suricata_rules(q: str, limit: int = 10, source_filter: str = "", status_filter: str = "") -> dict:
    results: list[dict] = []
    ql = q.lower() if q else ""
    want_disabled = status_filter == "disabled"
    want_error = status_filter == "error"

    def _parse_with_status(raw: str, file_id: str, line_no: int, source: str) -> dict | None:
        stripped = raw.strip()
        if want_disabled:
            if not stripped.startswith("#"):
                return None
            rule = _parse_rule_line(stripped.lstrip("#").strip(), file_id, line_no, source)
            if rule:
                rule["status"] = "disabled"
            return rule
        if want_error:
            # parse as enabled rule, mark error if missing required keywords
            if stripped.startswith("#"):
                return None
            rule = _parse_rule_line(raw, file_id, line_no, source)
            if rule and _rule_has_error(raw):
                rule["status"] = "error"
                return rule
            return None
        return _parse_rule_line(raw, file_id, line_no, source)

    if not source_filter or source_filter == "local":
        local_dir = repo_root() / "data" / "rules" / "suricata"
        if local_dir.exists():
            for f in sorted(local_dir.rglob("*.rules")):
                if f.name.startswith("."):
                    continue
                try:
                    for i, raw in enumerate(f.read_text(errors="replace").splitlines()):
                        rule = _parse_with_status(raw, str(f.relative_to(repo_root())), i, "local")
                        if rule and _rule_matches(rule, ql):
                            results.append(rule)
                            if len(results) >= limit:
                                return {"rules": results, "total": len(results), "truncated": True}
                except Exception:
                    pass

    # Error filter only checks local rules (docker rules are pre-validated by ET)
    if want_error:
        return {"rules": results, "total": len(results), "truncated": False}

    if not source_filter or source_filter == "docker":
        if want_disabled:
            grep_cmd = ["suricata", "grep", "-rn", "--include=*.rules", "^#.*sid:", "/var/lib/suricata/rules/"]
        elif ql:
            # grep msg field only for candidates, then post-filter on parsed name/sid
            grep_cmd = ["suricata", "grep", "-rn", "--include=*.rules", "-i", f"msg:.*{ql}\\|sid:{ql}", "/var/lib/suricata/rules/"]
        else:
            grep_cmd = ["suricata", "grep", "-rn", "--include=*.rules", "^alert\\|^pass\\|^drop", "/var/lib/suricata/rules/"]
        out = _docker_exec(grep_cmd, timeout=10)
        for raw_line in (out or "").splitlines():
            parts = raw_line.split(":", 2)
            if len(parts) < 3:
                continue
            fpath, lineno_str, rule_text = parts[0], parts[1], parts[2]
            try:
                lineno = int(lineno_str) - 1
            except ValueError:
                continue
            rule = _parse_with_status(rule_text, f"docker:suricata:{fpath}", lineno, "docker")
            if rule and _rule_matches(rule, ql):
                results.append(rule)
                if len(results) >= limit:
                    return {"rules": results, "total": len(results), "truncated": True}

    return {"rules": results, "total": len(results), "truncated": False}


def _count_local_rules(want_disabled: bool) -> int:
    total = 0
    local_dir = repo_root() / "data" / "rules" / "suricata"
    if not local_dir.exists():
        return 0
    for f in local_dir.rglob("*.rules"):
        if not f.is_file():
            continue
        try:
            for ln in f.read_text(errors="replace").splitlines():
                if "sid:" not in ln:
                    continue
                is_commented = ln.strip().startswith("#")
                if want_disabled == is_commented:
                    total += 1
        except Exception:
            pass
    return total


def _count_local_error_rules() -> int:
    total = 0
    local_dir = repo_root() / "data" / "rules" / "suricata"
    if not local_dir.exists():
        return 0
    for f in local_dir.rglob("*.rules"):
        if not f.is_file():
            continue
        try:
            for ln in f.read_text(errors="replace").splitlines():
                if _rule_has_error(ln):
                    total += 1
        except Exception:
            pass
    return total


def _get_suricata_count() -> int:
    global _suricata_count_cache
    now = time.time()
    if _suricata_count_cache and now - _suricata_count_cache[0] < 300:
        return _suricata_count_cache[1]
    total = _count_local_rules(want_disabled=False)
    out = _docker_exec(
        ["suricata", "sh", "-c", "grep -r --include='*.rules' 'sid:' /var/lib/suricata/rules/ | grep -vc '^[^:]*:#'"],
        timeout=20,
    )
    try:
        total += int((out or "").strip())
    except ValueError:
        pass
    _suricata_count_cache = (now, total)
    return total


def _get_suricata_disabled_count() -> int:
    global _suricata_disabled_count_cache
    now = time.time()
    if _suricata_disabled_count_cache and now - _suricata_disabled_count_cache[0] < 300:
        return _suricata_disabled_count_cache[1]
    total = _count_local_rules(want_disabled=True)
    out = _docker_exec(
        ["suricata", "sh", "-c", "grep -r --include='*.rules' 'sid:' /var/lib/suricata/rules/ | grep -c '^[^:]*:#'"],
        timeout=20,
    )
    try:
        total += int((out or "").strip())
    except ValueError:
        pass
    _suricata_disabled_count_cache = (now, total)
    return total


def _get_suricata_error_count() -> int:
    global _suricata_error_count_cache
    now = time.time()
    if _suricata_error_count_cache and now - _suricata_error_count_cache[0] < 300:
        return _suricata_error_count_cache[1]
    total = _count_local_error_rules()
    _suricata_error_count_cache = (now, total)
    return total


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.get("/status")
def rules_status() -> dict:
    status_file = repo_root() / "runtime" / "logs" / "rules" / "status.json"
    if not status_file.exists():
        return {"exists": False}
    try:
        data = json.loads(status_file.read_text())
        data["exists"] = True
        return data
    except Exception:
        return {"exists": False, "error": "Could not parse status.json"}


@router.post("/validate")
def rules_validate(body: RuleValidateRequest) -> dict:
    content = body.content.strip()
    rule_type = body.type

    if not content:
        return {"ok": False, "errors": ["Editor is empty"]}

    # Auto-detect type from content
    if not rule_type:
        first = (content.lstrip().splitlines() or [""])[0]
        rule_type = "suricata" if first.split(None, 1)[0] in _SURI_ACTIONS else "yaml"

    if rule_type == "suricata":
        # Write rule into container via stdin, run suricata -T against it.
        # Save exit code BEFORE rm so the shell exits with Suricata's code.
        try:
            result = subprocess.run(
                ["docker", "exec", "-i", "suricata", "sh", "-c",
                 "cat > /tmp/soc_validate.rules && "
                 "suricata -T -c /etc/suricata/suricata.yaml -S /tmp/soc_validate.rules 2>&1; "
                 "CODE=$?; rm -f /tmp/soc_validate.rules; exit $CODE"],
                input=content.encode(),
                capture_output=True,
                timeout=20,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "errors": ["Validation timed out — is Suricata running?"], "type": "suricata"}
        except Exception as exc:
            return {"ok": False, "errors": [f"Could not reach container: {exc}"], "type": "suricata"}

        output = result.stdout.decode(errors="replace")

        # Extract error lines regardless of exit code — suricata sometimes exits 0
        # but still prints [Error] lines (e.g. "No rule files match the pattern")
        error_lines = [
            l.strip() for l in output.splitlines()
            if any(k in l.lower() for k in ("[error]", "failed to", "invalid", "unknown keyword", "sids must"))
        ]
        if result.returncode != 0 or error_lines:
            return {
                "ok": False,
                "errors": error_lines[:5] or ["Suricata rejected the rule — check syntax"],
                "type": "suricata",
            }
        return {"ok": True, "errors": [], "type": "suricata"}

    # YAML (sigma / elastalert)
    try:
        import yaml
        parsed = yaml.safe_load(content)
    except Exception as exc:
        return {"ok": False, "errors": [f"YAML parse error: {exc}"], "type": rule_type}
    if not isinstance(parsed, dict):
        return {"ok": False, "errors": ["Content must be a YAML mapping"], "type": rule_type}
    errors: list[str] = []
    if rule_type == "sigma":
        for field in ("title", "logsource", "detection"):
            if field not in parsed:
                errors.append(f"Missing required Sigma field: '{field}'")
    return {"ok": not errors, "errors": errors, "type": rule_type}


@router.post("/compile")
def rules_compile() -> dict:
    try:
        from core.rules.compile import compile
        return compile()
    except Exception as exc:
        raise bad(exc, 500)


@router.get("/watcher")
def rules_watcher() -> dict:
    pid_file = repo_root() / ".soc-lab" / "rules-watcher.pid"
    if not pid_file.exists():
        return {"running": False}
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        return {"running": True, "pid": pid}
    except (ProcessLookupError, ValueError):
        return {"running": False}


@router.post("/watcher/start")
def rules_watcher_start() -> dict:
    try:
        from core.rules.compile import watch_start
        return watch_start()
    except Exception as exc:
        raise bad(exc, 500)


@router.post("/watcher/stop")
def rules_watcher_stop() -> dict:
    try:
        from core.rules.compile import watch_stop
        return watch_stop()
    except Exception as exc:
        raise bad(exc, 500)


@router.get("/log/{which}")
def rules_log(which: str, lines: int = 40) -> dict:
    valid = {"suricata": "suricata-compile.log", "sigma": "sigma-compile.log", "watcher": "watcher.log"}
    if which not in valid:
        raise HTTPException(status_code=400, detail=f"Unknown log: {which}")
    path = repo_root() / "runtime" / "logs" / "rules" / valid[which]
    if not path.exists():
        return {"log": "", "exists": False}
    content = path.read_text(errors="replace").splitlines()
    return {"log": "\n".join(content[-lines:]), "exists": True}


@router.get("/suricata-rules")
def rules_suricata_rules(q: str = Query(""), source: str = Query(""), limit: int = Query(10), status: str = Query("")) -> dict:
    return _grep_suricata_rules(q=q, limit=limit, source_filter=source, status_filter=status)


@router.get("/suricata-count")
def rules_suricata_count(status: str = Query("enabled")) -> dict:
    if status == "disabled":
        return {"count": _get_suricata_disabled_count()}
    if status == "error":
        return {"count": _get_suricata_error_count()}
    if status == "all":
        return {"count": _get_suricata_count() + _get_suricata_disabled_count()}
    return {"count": _get_suricata_count()}


@router.get("/files")
def rules_list_files(type: str = Query("sigma")) -> dict:
    from pathlib import Path
    root = repo_root()
    ext_map = {"sigma": [".yml", ".yaml"], "elastalert": [".yml", ".yaml"]}
    if type not in ext_map:
        raise HTTPException(status_code=400, detail=f"Unknown type: {type}")
    rules_dir = root / "data" / "rules" / type
    extensions = ext_map[type]
    files: list[dict] = []
    if rules_dir.exists():
        for f in sorted(rules_dir.rglob("*")):
            if not f.is_file() or f.name.startswith(".") or f.suffix not in extensions:
                continue
            name = f.stem
            status = "enabled"
            try:
                content = f.read_text(errors="replace")
                status = _yaml_rule_status(type, content)
                for line in content.splitlines():
                    s = line.strip()
                    if s.startswith("title:") or s.startswith("name:"):
                        name = s.split(":", 1)[1].strip()
                        break
            except Exception:
                status = "error"
            stat = f.stat()
            files.append({"name": name, "file": str(f.relative_to(root)), "stem": f.stem,
                          "type": type, "size": stat.st_size, "status": status, "source": "local"})
    return {"files": files, "type": type}


@router.get("/file")
def rules_file_get(path: str = Query(...)) -> dict:
    base, line_no = _rule_path_parse(path)
    if base.startswith("docker:"):
        _, container, container_path = base.split(":", 2)
        content = _docker_exec([container, "cat", container_path], timeout=8)
        if not content:
            raise HTTPException(status_code=404, detail="File not found in container")
        if line_no is not None:
            lines = content.splitlines()
            content = lines[line_no] if 0 <= line_no < len(lines) else ""
        return {"path": path, "content": content, "readonly": True}
    target = _security_check(base)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    content = target.read_text(errors="replace")
    if line_no is not None:
        lines = content.splitlines()
        content = lines[line_no] if 0 <= line_no < len(lines) else ""
    return {"path": path, "content": content, "readonly": False}


@router.post("/suricata-rule")
def rules_suricata_rule_save(body: RuleFileWriteRequest) -> dict:
    base, line_no = _rule_path_parse(body.path)
    target = _security_check(base)
    target.parent.mkdir(parents=True, exist_ok=True)
    if line_no is not None and target.exists():
        lines = target.read_text(errors="replace").splitlines()
        if 0 <= line_no < len(lines):
            lines[line_no] = body.content.strip()
        else:
            lines.append(body.content.strip())
        target.write_text("\n".join(lines) + "\n")
    elif target.exists():
        target.write_text(target.read_text(errors="replace").rstrip() + "\n" + body.content.strip() + "\n")
    else:
        target.write_text(body.content.strip() + "\n")
    _clear_suricata_count_caches()
    return {"ok": True, "path": body.path}


@router.post("/file")
def rules_file_write(body: RuleFileWriteRequest) -> dict:
    if "#" in body.path:
        raise HTTPException(status_code=400, detail="Line-addressed Suricata edits must use /api/rules/suricata-rule")
    target = _security_check(body.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content)
    if "/suricata/" in body.path or body.path.endswith(".rules"):
        _clear_suricata_count_caches()
    return {"saved": True, "path": body.path}


@router.delete("/file")
def rules_file_delete(path: str = Query(...)) -> dict:
    target = _security_check(path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    target.unlink()
    if "/suricata/" in path or path.endswith(".rules"):
        _clear_suricata_count_caches()
    return {"deleted": True, "path": path}
