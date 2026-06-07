from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from api.utils import bad

router = APIRouter(prefix="/api/alerts")

_SEV_MAP = {"critical": 1, "high": 2, "medium": 3, "low": 4}
_SEV_MAP_REV = {v: k for k, v in _SEV_MAP.items()}


def _es():
    from core.elastic.client import client
    return client()


@router.get("")
def alerts_list(
    size: int = Query(100, ge=1, le=500),
    severity: str = Query(""),
    q: str = Query(""),
    dataset: str = Query(""),
    offset: int = Query(0, ge=0),
) -> dict:
    try:
        es = _es()
        must: list[dict] = []
        if q:
            must.append({"query_string": {"query": q, "default_operator": "AND"}})
        if dataset:
            must.append({"term": {"event.dataset": dataset}})
        if severity and severity in _SEV_MAP:
            must.append({"term": {"alert.severity": _SEV_MAP[severity]}})
        query: dict[str, Any] = {"match_all": {}} if not must else {"bool": {"must": must}}
        result = es.options(ignore_status=[404]).search(
            index="soc-alerts",
            query=query,
            sort=[{"@timestamp": {"order": "desc"}}],
            size=size,
            from_=offset,
            source=["@timestamp", "alert.signature", "alert.severity", "alert.category", "alert.action",
                    "source.ip", "destination.ip", "destination.port", "network.transport",
                    "event.dataset", "rule.name", "tags"],
        )
        hits = result.get("hits", {})
        return {"total": hits.get("total", {}).get("value", 0), "alerts": [h["_source"] for h in hits.get("hits", [])]}
    except Exception as exc:
        raise bad(exc)


@router.get("/timeline")
def alerts_timeline(minutes: int = 60, buckets: int = 12) -> dict:
    try:
        es = _es()
        interval_ms = (minutes * 60 * 1000) // buckets
        result = es.options(ignore_status=[404]).search(
            index="soc-alerts",
            size=0,
            query={"range": {"@timestamp": {"gte": f"now-{minutes}m"}}},
            aggs={"buckets": {"date_histogram": {"field": "@timestamp", "fixed_interval": f"{interval_ms}ms",
                                                  "min_doc_count": 0,
                                                  "extended_bounds": {"min": f"now-{minutes}m", "max": "now"}}}},
        )
        raw = result.get("aggregations", {}).get("buckets", {}).get("buckets", [])
        return {"buckets": [{"count": b["doc_count"]} for b in raw[-buckets:]]}
    except Exception:
        return {"buckets": []}


@router.get("/stats")
def alerts_stats() -> dict:
    try:
        es = _es()
        result = es.options(ignore_status=[404]).search(
            index="soc-alerts",
            size=0,
            aggs={
                "by_severity": {"terms": {"field": "alert.severity", "size": 10}},
                "by_dataset": {"terms": {"field": "event.dataset", "size": 10}},
            },
        )
        total = result.get("hits", {}).get("total", {}).get("value", 0)
        by_sev = {_SEV_MAP_REV.get(b["key"], str(b["key"])): b["doc_count"]
                  for b in result.get("aggregations", {}).get("by_severity", {}).get("buckets", [])}
        by_dataset = {b["key"]: b["doc_count"]
                      for b in result.get("aggregations", {}).get("by_dataset", {}).get("buckets", [])}
        return {"total": total, "by_severity": by_sev, "by_dataset": by_dataset}
    except Exception as exc:
        raise bad(exc)
