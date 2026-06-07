from __future__ import annotations

from fastapi import APIRouter, Query

from api.utils import bad

router = APIRouter(prefix="/api/network")


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
        must: list[dict] = [{"term": {"event.dataset": "suricata.flow"}}]
        if q:
            must.append({"query_string": {"query": q}})
        if proto:
            must.append({"term": {"network.transport": proto.lower()}})
        result = es.options(ignore_status=[404]).search(
            index="suricata-*",
            query={"bool": {"must": must}},
            sort=[{"@timestamp": {"order": "desc"}}],
            size=size,
            source=["@timestamp", "source.ip", "source.port", "destination.ip", "destination.port",
                    "network.transport", "network.bytes", "network.packets", "event.duration",
                    "flow.pkts_toserver", "flow.pkts_toclient", "flow.bytes_toserver", "flow.bytes_toclient"],
        )
        hits = result.get("hits", {})
        agg_result = es.options(ignore_status=[404]).search(
            index="suricata-*",
            query={"term": {"event.dataset": "suricata.flow"}},
            size=0,
            aggs={
                "unique_src": {"cardinality": {"field": "source.ip"}},
                "unique_dst": {"cardinality": {"field": "destination.ip"}},
                "by_proto": {"terms": {"field": "network.transport", "size": 10}},
            },
        )
        aggs = agg_result.get("aggregations", {})
        return {
            "total": hits.get("total", {}).get("value", 0),
            "flows": [h["_source"] for h in hits.get("hits", [])],
            "unique_src": aggs.get("unique_src", {}).get("value", 0),
            "unique_dst": aggs.get("unique_dst", {}).get("value", 0),
            "by_proto": {b["key"]: b["doc_count"] for b in aggs.get("by_proto", {}).get("buckets", [])},
        }
    except Exception as exc:
        raise bad(exc)
