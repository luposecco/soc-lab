from __future__ import annotations

from fastapi import APIRouter, Query

from api.models import EnrichRunRequest
from api.utils import bad

router = APIRouter(prefix="/api/enrich")


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


@router.get("/enrichments")
def enrich_list() -> dict:
    try:
        from core.enrich.runner import load_enrichment_config
        return {"enrichments": load_enrichment_config()}
    except Exception as exc:
        raise bad(exc)


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
