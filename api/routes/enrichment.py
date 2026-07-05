from __future__ import annotations

import ast
from pathlib import Path

import yaml
from fastapi import APIRouter, Query

from api.models import ClusterSaveRequest, EnrichmentSaveRequest, EnrichRunRequest, ScriptSaveRequest, ScriptValidateRequest
from api.utils import bad
from core.settings import repo_root

router = APIRouter(prefix="/api/enrich")

_ENRICHMENTS_YML = repo_root() / "data" / "enrichments" / "config" / "enrichments.yml"
_CLUSTERS_YML = repo_root() / "data" / "enrichments" / "config" / "clusters.yml"
_SCRIPTS_DIR = repo_root() / "data" / "enrichments" / "scripts"


# ── Cluster endpoints ──────────────────────────────────────────────────────────

@router.get("/clusters")
def enrich_clusters() -> dict:
    try:
        from core.enrich.clusters import ClusterManager
        return {"clusters": ClusterManager.load().list_all()}
    except Exception as exc:
        raise bad(exc)


@router.post("/clusters/{name}/test")
def enrich_cluster_test(name: str) -> dict:
    try:
        from core.enrich.clusters import ClusterManager
        return ClusterManager.load().ping(name)
    except Exception as exc:
        raise bad(exc, 400)


@router.post("/clusters/ping")
def enrich_clusters_ping() -> dict:
    try:
        from core.enrich.clusters import ClusterManager
        return {"clusters": ClusterManager.load().ping_all()}
    except Exception as exc:
        raise bad(exc)


@router.post("/clusters-config/{name}")
def cluster_save(name: str, req: ClusterSaveRequest) -> dict:
    try:
        raw = yaml.safe_load(_CLUSTERS_YML.read_text()) if _CLUSTERS_YML.exists() else {}
        if not raw:
            raw = {}
        raw.setdefault("clusters", {})
        entry: dict = {"mode": req.mode, "hosts": req.hosts}
        if req.auth_type == "api_key" and req.auth_env:
            entry["auth"] = {"type": "api_key", "env": req.auth_env}
        elif req.auth_type == "basic":
            entry["auth"] = {"type": "basic", "user": req.auth_user, "pass_env": req.auth_pass_env}
        raw["clusters"][name] = entry
        _CLUSTERS_YML.write_text(yaml.dump(raw, default_flow_style=False, allow_unicode=True))
        return {"ok": True, "name": name}
    except Exception as exc:
        raise bad(exc)


@router.delete("/clusters-config/{name}")
def cluster_delete(name: str) -> dict:
    try:
        if not _CLUSTERS_YML.exists():
            return {"ok": True}
        raw = yaml.safe_load(_CLUSTERS_YML.read_text()) or {}
        (raw.get("clusters") or {}).pop(name, None)
        _CLUSTERS_YML.write_text(yaml.dump(raw, default_flow_style=False, allow_unicode=True))
        return {"ok": True, "name": name}
    except Exception as exc:
        raise bad(exc)


# ── Enrichment config endpoints ────────────────────────────────────────────────

@router.get("/enrichments")
def enrich_list() -> dict:
    try:
        from core.enrich.runner import load_enrichment_config
        return {"enrichments": load_enrichment_config()}
    except Exception as exc:
        raise bad(exc)


@router.post("/enrichments/{key}")
def enrichment_save(key: str, req: EnrichmentSaveRequest) -> dict:
    try:
        raw = yaml.safe_load(_ENRICHMENTS_YML.read_text()) if _ENRICHMENTS_YML.exists() else {}
        if not raw:
            raw = {}
        raw.setdefault("enrichments", {})
        entry: dict = {
            "name": req.display_name or key,
            "script": req.script,
            "targets": req.targets,
            "enabled": req.enabled,
        }
        if req.on_log:
            entry["on_log"] = True
        if req.schedule:
            entry["schedule"] = req.schedule
        if req.description:
            entry["description"] = req.description
        raw["enrichments"][key] = entry
        _ENRICHMENTS_YML.write_text(yaml.dump(raw, default_flow_style=False, allow_unicode=True))
        return {"ok": True, "key": key}
    except Exception as exc:
        raise bad(exc)


@router.delete("/enrichments/{key}")
def enrichment_delete(key: str) -> dict:
    try:
        if not _ENRICHMENTS_YML.exists():
            return {"ok": True}
        raw = yaml.safe_load(_ENRICHMENTS_YML.read_text()) or {}
        (raw.get("enrichments") or {}).pop(key, None)
        _ENRICHMENTS_YML.write_text(yaml.dump(raw, default_flow_style=False, allow_unicode=True))
        return {"ok": True, "key": key}
    except Exception as exc:
        raise bad(exc)


# ── Script file endpoints ──────────────────────────────────────────────────────

@router.get("/scripts")
def enrich_scripts() -> dict:
    try:
        _SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        files = sorted(
            f"scripts/{p.name}"
            for p in _SCRIPTS_DIR.glob("*.py")
            if not p.name.startswith("_")
        )
        return {"scripts": files}
    except Exception as exc:
        raise bad(exc)


@router.get("/script-content")
def enrich_script_content(path: str = Query(...)) -> dict:
    try:
        full = repo_root() / "data" / "enrichments" / path
        if not full.exists():
            return {"content": ""}
        return {"content": full.read_text()}
    except Exception as exc:
        raise bad(exc)


@router.post("/script-content")
def enrich_script_save(req: ScriptSaveRequest) -> dict:
    try:
        full = repo_root() / "data" / "enrichments" / req.path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(req.content)
        return {"ok": True, "path": req.path}
    except Exception as exc:
        raise bad(exc)


@router.post("/script-validate")
def enrich_script_validate(req: ScriptValidateRequest) -> dict:
    try:
        compile(req.content, req.path or "<string>", "exec")
        tree = ast.parse(req.content)
        has_run = any(
            isinstance(node, ast.FunctionDef) and node.name == "run"
            for node in ast.walk(tree)
        )
        if not has_run:
            return {"ok": False, "error": "Script must define a run(ctx) function"}
        return {"ok": True}
    except SyntaxError as e:
        return {"ok": False, "error": f"Syntax error at line {e.lineno}: {e.msg}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── Run / rollback endpoints ───────────────────────────────────────────────────

@router.post("/run/{name}")
def enrich_run(name: str, req: EnrichRunRequest = EnrichRunRequest()) -> dict:
    try:
        from core.enrich.runner import run_enrichment
        return run_enrichment(name, cluster=req.cluster or None, dry_run=req.dry_run, params=req.params)
    except Exception as exc:
        raise bad(exc, 500)


@router.get("/runs")
def enrich_runs(limit: int = Query(50, ge=1, le=500)) -> dict:
    try:
        from core.enrich.audit import list_runs
        return {"runs": list_runs(limit=limit)}
    except Exception as exc:
        raise bad(exc)


@router.post("/rollback/{run_id}")
def enrich_rollback(run_id: str, dry_run: bool = Query(False), force: bool = Query(False)) -> dict:
    try:
        from core.enrich.rollback import rollback
        return rollback(run_id, dry_run=dry_run, force=force)
    except Exception as exc:
        raise bad(exc, 500)
