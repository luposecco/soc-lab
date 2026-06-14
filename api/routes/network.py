from __future__ import annotations

from fastapi import APIRouter, Query

from api.utils import bad

router = APIRouter(prefix="/api/network")

# Suricata connection events are indexed under suricata.conn (not suricata.flow).
# Bytes live in client.ip_bytes / server.ip_bytes.
# All text fields require the .keyword sub-field for aggregations.
_DATASET = "suricata.conn"


def _es():
    from core.elastic.client import client
    return client()


@router.get("/flows")
def network_flows(
    size: int = Query(100, ge=1, le=500),
    q: str = Query(""),
    proto: str = Query(""),
) -> dict:
    try:
        es = _es()
        must: list[dict] = [{"term": {"event.dataset.keyword": _DATASET}}]
        if q:
            # search across src/dst IPs
            must.append({"query_string": {
                "query": q,
                "fields": ["source.ip", "destination.ip"],
                "default_operator": "OR",
            }})
        if proto:
            # transport values are uppercase in ES ("TCP","UDP") — match exactly
            must.append({"term": {"network.transport.keyword": proto.upper()}})

        result = es.options(ignore_status=[404]).search(
            index="suricata-*",
            query={"bool": {"must": must}},
            sort=[{"@timestamp": {"order": "desc"}}],
            size=size,
            source=[
                "@timestamp", "source.ip", "source.port",
                "destination.ip", "destination.port",
                "network.transport", "network.protocol",
                "client.ip_bytes", "server.ip_bytes",
                "connection.state",
            ],
        )
        hits = result.get("hits", {})

        agg_result = es.options(ignore_status=[404]).search(
            index="suricata-*",
            query={"term": {"event.dataset.keyword": _DATASET}},
            size=0,
            aggs={
                "unique_src": {"cardinality": {"field": "source.ip.keyword"}},
                "unique_dst": {"cardinality": {"field": "destination.ip.keyword"}},
                "by_proto": {"terms": {"field": "network.transport.keyword", "size": 10}},
                "total_bytes": {"sum": {"field": "client.ip_bytes"}},
                "top_src": {
                    "terms": {"field": "source.ip.keyword", "size": 5},
                    "aggs": {
                        "flows": {"value_count": {"field": "source.ip.keyword"}},
                        "bytes": {"sum": {"field": "client.ip_bytes"}},
                    },
                },
                "top_dst": {
                    "terms": {"field": "destination.ip.keyword", "size": 5},
                    "aggs": {
                        "bytes": {"sum": {"field": "client.ip_bytes"}},
                        "top_port": {"terms": {"field": "destination.port", "size": 1}},
                    },
                },
            },
        )
        aggs = agg_result.get("aggregations", {})

        def _top_src(agg: dict) -> list[dict]:
            return [
                {"ip": b["key"], "flows": b["flows"]["value"], "bytes": b["bytes"]["value"]}
                for b in agg.get("buckets", [])
            ]

        def _top_dst(agg: dict) -> list[dict]:
            rows = []
            for b in agg.get("buckets", []):
                port_buckets = b.get("top_port", {}).get("buckets", [])
                rows.append({
                    "ip": b["key"],
                    "flows": b["doc_count"],
                    "bytes": b["bytes"]["value"],
                    "port": port_buckets[0]["key"] if port_buckets else None,
                })
            return rows

        return {
            "total": hits.get("total", {}).get("value", 0),
            "flows": [h["_source"] for h in hits.get("hits", [])],
            "unique_src": aggs.get("unique_src", {}).get("value", 0),
            "unique_dst": aggs.get("unique_dst", {}).get("value", 0),
            "by_proto": {b["key"]: b["doc_count"] for b in aggs.get("by_proto", {}).get("buckets", [])},
            "total_bytes": int(aggs.get("total_bytes", {}).get("value", 0) or 0),
            "top_src": _top_src(aggs.get("top_src", {})),
            "top_dst": _top_dst(aggs.get("top_dst", {})),
        }
    except Exception as exc:
        raise bad(exc)
