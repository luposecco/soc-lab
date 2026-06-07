from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.elastic.client import client as _lab_es

AUDIT_INDEX_PREFIX = "soc-lab-enrichment-audit"

_AUDIT_INDEX_MAPPINGS = {
    "mappings": {
        "properties": {
            "@timestamp": {"type": "date"},
            "run_id": {"type": "keyword"},
            "enrichment": {"type": "keyword"},
            "cluster": {"type": "keyword"},
            "index": {"type": "keyword"},
            "doc_id": {"type": "keyword"},
            "operation": {"type": "keyword"},
            "changed_fields": {"type": "keyword"},
            "rollback_supported": {"type": "boolean"},
            "before": {"type": "object", "enabled": False},
            "after": {"type": "object", "enabled": False},
        }
    }
}


def _today_index() -> str:
    return f"{AUDIT_INDEX_PREFIX}-{datetime.now(timezone.utc).strftime('%Y.%m.%d')}"


def write(record: dict[str, Any]) -> None:
    _ensure_audit_index(_today_index())
    if "@timestamp" not in record:
        record["@timestamp"] = datetime.now(timezone.utc).isoformat()
    record.setdefault("changed_fields", [])
    record.setdefault("rollback_supported", False)
    _lab_es().index(index=_today_index(), document=record)


def read_run(run_id: str) -> list[dict[str, Any]]:
    es = _lab_es()
    result = es.options(ignore_status=[404]).search(
        index=f"{AUDIT_INDEX_PREFIX}-*",
        query={"term": {"run_id": run_id}},
        sort=[{"@timestamp": {"order": "asc"}}],
        size=10000,
    )
    return [h["_source"] | {"_id": h["_id"], "_index": h["_index"]} for h in result.get("hits", {}).get("hits", [])]


def list_runs(limit: int = 50) -> list[dict[str, Any]]:
    es = _lab_es()
    result = es.options(ignore_status=[404]).search(
        index=f"{AUDIT_INDEX_PREFIX}-*",
        size=0,
        aggs={
            "by_run": {
                "terms": {"field": "run_id", "size": limit, "order": {"latest": "desc"}},
                "aggs": {
                    "latest": {"max": {"field": "@timestamp"}},
                    "enrichment": {"terms": {"field": "enrichment", "size": 1}},
                    "cluster": {"terms": {"field": "cluster", "size": 1}},
                    "operations": {"value_count": {"field": "operation"}},
                },
            }
        },
    )
    buckets = result.get("aggregations", {}).get("by_run", {}).get("buckets", [])
    runs = []
    for b in buckets:
        enr_buckets = b.get("enrichment", {}).get("buckets", [])
        cl_buckets = b.get("cluster", {}).get("buckets", [])
        runs.append({
            "run_id": b["key"],
            "enrichment": enr_buckets[0]["key"] if enr_buckets else "",
            "cluster": cl_buckets[0]["key"] if cl_buckets else "",
            "operations": b.get("operations", {}).get("value", 0),
            "timestamp": b.get("latest", {}).get("value_as_string", ""),
        })
    return runs


def has_later_field_changes(record: dict[str, Any]) -> bool:
    changed_fields = record.get("changed_fields") or []
    if not changed_fields:
        return False

    result = _lab_es().options(ignore_status=[404]).search(
        index=f"{AUDIT_INDEX_PREFIX}-*",
        size=1,
        query={
            "bool": {
                "must": [
                    {"term": {"cluster": record.get("cluster", "")}},
                    {"term": {"index": record.get("index", "")}},
                    {"term": {"doc_id": record.get("doc_id", "")}},
                    {"range": {"@timestamp": {"gt": record.get("@timestamp", "")}}},
                    {"term": {"rollback_supported": True}},
                    {"terms": {"changed_fields": changed_fields}},
                ],
                "must_not": [
                    {"term": {"run_id": record.get("run_id", "")}},
                ],
            }
        },
    )
    return bool(result.get("hits", {}).get("hits", []))


def _ensure_audit_index(index_name: str) -> None:
    _lab_es().options(ignore_status=[400]).indices.create(index=index_name, **_AUDIT_INDEX_MAPPINGS)
