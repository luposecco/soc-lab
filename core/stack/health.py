from __future__ import annotations

from typing import Any

import httpx

from core.settings import es_url, kibana_url, repo_root
from core.stack.runtime import docker_stats


def _get_json(url: str) -> dict[str, Any] | None:
    try:
        response = httpx.get(url, timeout=3.0)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def elasticsearch_health() -> dict[str, Any]:
    data = _get_json(f"{es_url()}/_cluster/health")
    if not data:
        return {"reachable": False}
    return {
        "reachable": True,
        "status": data.get("status"),
        "number_of_nodes": data.get("number_of_nodes"),
        "active_primary_shards": data.get("active_primary_shards"),
        "active_shards": data.get("active_shards"),
    }


def kibana_health() -> dict[str, Any]:
    data = _get_json(f"{kibana_url()}/api/status")
    if not data:
        return {"reachable": False}
    return {
        "reachable": True,
        "level": data.get("status", {}).get("overall", {}).get("level"),
        "summary": data.get("status", {}).get("overall", {}).get("summary"),
    }


def suricata_event_tail(lines: int = 3) -> list[str]:
    path = repo_root() / "runtime" / "logs" / "suricata" / "eve.json"
    if not path.exists():
        return []
    return path.read_text(errors="replace").splitlines()[-lines:]


def stack_health_summary(services: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "services": services,
        "elasticsearch": elasticsearch_health(),
        "kibana": kibana_health(),
        "suricata_tail": suricata_event_tail(),
    }


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _status_tag(service: dict[str, Any]) -> dict[str, str]:
    state = service.get("State", "")
    health = service.get("Health", "")
    if state == "running" and health == "healthy":
        return {"label": "Running", "class": "running"}
    if state == "running" and health:
        return {"label": health.title(), "class": "warning"}
    if state == "running":
        return {"label": "Running", "class": "running"}
    if state:
        return {"label": state.title(), "class": "stopped"}
    return {"label": "Unknown", "class": "warning"}


def _service_port(service: dict[str, Any]) -> str:
    publishers = service.get("Publishers") or []
    if publishers:
        first = publishers[0]
        published = first.get("PublishedPort")
        if published:
            return f"port {published}"
    return ""


def _service_meta(service: dict[str, Any], default_version: str = "") -> str:
    image = service.get("Image", "")
    version = default_version
    if ":" in image:
        version = f"v{image.rsplit(':', 1)[-1]}"
    port = _service_port(service)
    parts = [part for part in [version, port] if part]
    return " · ".join(parts)


def _service_exists(services: list[dict[str, Any]], service_name: str) -> bool:
    return any((service.get("Name") or service.get("Service")) == service_name for service in services)


def _suricata_alert_count() -> int:
    data = _get_json(f"{es_url()}/suricata-*/_count?q=event.dataset:suricata.alert")
    return _safe_int(data.get("count") if data else 0)


def _elastalert_error_count() -> int:
    data = _get_json(f"{es_url()}/elastalert2_alerts_error/_count")
    return _safe_int(data.get("count") if data else 0)


def _sum_docs() -> int:
    data = _get_json(f"{es_url()}/_cat/indices?format=json&h=docs.count")
    if not isinstance(data, list):
        return 0
    return sum(_safe_int(row.get("docs.count")) for row in data)


def stack_service_cards(services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name = {service.get("Name", service.get("Service", "")): service for service in services}
    stats = docker_stats()
    elastic = elasticsearch_health()
    kibana = kibana_health()
    cards: list[dict[str, Any]] = []

    def add_card(service_name: str, title: str, icon: str, icon_class: str, stats_fields: list[dict[str, str]], fallback_meta: str = "") -> None:
        service = by_name.get(service_name, {})
        stat_row = stats.get(service_name, {})
        exists = _service_exists(services, service_name)
        tag = _status_tag(service) if service else {"label": "Stopped", "class": "stopped"}
        primary_action = "stop" if exists and service.get("State") == "running" else "start"
        cards.append(
            {
                "service": service_name,
                "title": title,
                "icon": icon,
                "icon_class": icon_class,
                "meta": _service_meta(service, fallback_meta) or fallback_meta,
                "tag": tag,
                "exists": exists,
                "primary_action": primary_action,
                "stats": [
                    {
                        "label": field["label"],
                        "value": field["value"](service, stat_row),
                        "tone": field.get("tone", ""),
                    }
                    for field in stats_fields
                ],
            }
        )

    add_card(
        "elasticsearch",
        "Elasticsearch",
        "ti ti-database",
        "es",
        [
            {"label": "CPU", "value": lambda _s, st: st.get("CPUPerc", "—")},
            {"label": "RAM", "value": lambda _s, st: st.get("MemUsage", "—").split(" / ")[0] if st else "—"},
            {"label": "Docs", "value": lambda _s, _st: f"{_sum_docs():,}"},
        ],
        fallback_meta="v8.13.0 · port 9200",
    )
    add_card(
        "kibana",
        "Kibana",
        "ti ti-chart-bar",
        "ki",
        [
            {"label": "CPU", "value": lambda _s, st: st.get("CPUPerc", "—")},
            {"label": "RAM", "value": lambda _s, st: st.get("MemUsage", "—").split(" / ")[0] if st else "—"},
            {"label": "Status", "value": lambda _s, _st: kibana.get("level", "—")},
        ],
        fallback_meta="v8.13.0 · port 5601",
    )
    add_card(
        "suricata",
        "Suricata",
        "ti ti-shield",
        "su",
        [
            {"label": "CPU", "value": lambda _s, st: st.get("CPUPerc", "—")},
            {"label": "RAM", "value": lambda _s, st: st.get("MemUsage", "—").split(" / ")[0] if st else "—"},
            {"label": "Alerts", "value": lambda _s, _st: str(_suricata_alert_count()), "tone": "red"},
        ],
        fallback_meta="v7.x · IDS",
    )
    add_card(
        "filebeat",
        "Filebeat",
        "ti ti-activity-heartbeat",
        "fb",
        [
            {"label": "CPU", "value": lambda _s, st: st.get("CPUPerc", "—")},
            {"label": "RAM", "value": lambda _s, st: st.get("MemUsage", "—").split(" / ")[0] if st else "—"},
            {"label": "Network", "value": lambda _s, st: st.get("NetIO", "—")},
        ],
        fallback_meta="v8.13.0",
    )
    add_card(
        "logstash",
        "Logstash",
        "ti ti-arrows-transfer-down",
        "ls",
        [
            {"label": "CPU", "value": lambda _s, st: st.get("CPUPerc", "—")},
            {"label": "RAM", "value": lambda _s, st: st.get("MemUsage", "—").split(" / ")[0] if st else "—"},
            {"label": "Pipelines", "value": lambda _s, _st: "0"},
        ],
        fallback_meta="not configured",
    )
    add_card(
        "elastalert2",
        "ElastAlert2",
        "ti ti-bell",
        "ea",
        [
            {"label": "CPU", "value": lambda _s, st: st.get("CPUPerc", "—")},
            {"label": "RAM", "value": lambda _s, st: st.get("MemUsage", "—").split(" / ")[0] if st else "—"},
            {"label": "Errors", "value": lambda _s, _st: str(_elastalert_error_count()), "tone": "amber"},
        ],
        fallback_meta="v2.x",
    )
    return cards
