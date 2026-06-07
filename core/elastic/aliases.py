from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from core.confirm import confirm
from core.elastic.client import client as es_client
from core.elastic.kibana import KibanaClient

TEMPLATE_PREFIX = "soc-lab-alias"
MISSING = object()
RESERVED_ALIASES = {"soc-alerts", "suricata", "sigma-alerts"}
SOC_ALERTS_FILTER = {
    "bool": {
        "should": [
            {"term": {"event.dataset": "alert"}},
            {"term": {"event.dataset": "suricata.alert"}},
            {"term": {"tags": "alert"}},
        ],
        "minimum_should_match": 1,
    }
}


@dataclass
class SourceSpec:
    source: str
    filter_type: str = ""
    filter_value: str = ""


def _safe_alias_name(name: str) -> None:
    if not name:
        raise ValueError("Alias name is required")
    if name == "_all":
        raise ValueError(f"Refusing unsafe alias name: {name}")
    if name.startswith("."):
        raise ValueError(f"Refusing system-style alias name: {name}")
    if "*" in name:
        raise ValueError(f"Alias name cannot contain wildcards: {name}")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$", name):
        raise ValueError(f"Unsafe alias name: {name}")


def _ensure_not_reserved(alias: str) -> None:
    if alias in RESERVED_ALIASES:
        raise ValueError(f"Alias '{alias}' is system-managed and cannot be modified by users")


def _safe_source_name(source: str) -> None:
    if not source:
        raise ValueError("Source index or pattern is required")
    if source == "_all":
        raise ValueError(f"Refusing unsafe source: {source}")
    if source.startswith("."):
        raise ValueError(f"Refusing system index source: {source}")
    if "," in source:
        raise ValueError(f"Source cannot contain comma: {source}")
    if "/" in source:
        raise ValueError(f"Source cannot contain slash: {source}")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._+*-]*$", source):
        raise ValueError(f"Unsafe source index or pattern: {source}")


def _has_wildcard(source: str) -> bool:
    return "*" in source


def _template_name(alias: str, pattern: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._+-]", "-", alias)[:80]
    digest = hashlib.sha1(pattern.encode()).hexdigest()[:12]
    return f"{TEMPLATE_PREFIX}-{safe}-{digest}"


def _filter_object(filter_type: str, filter_value: str) -> dict[str, Any] | None:
    if not filter_type:
        return None
    if filter_type == "query_string":
        if not filter_value:
            raise ValueError("--filter cannot be empty")
        return {"query_string": {"query": filter_value}}
    if filter_type == "json":
        try:
            parsed = json.loads(filter_value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid --filter-json: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Invalid --filter-json: filter must be a JSON object")
        if not parsed:
            raise ValueError("Invalid --filter-json: filter object cannot be empty")
        return parsed
    raise ValueError(f"Unknown filter type: {filter_type}")


def parse_source_specs(tokens: list[str]) -> list[SourceSpec]:
    specs: list[SourceSpec] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in {"--filter", "--filter-json"}:
            raise ValueError(f"{token} must follow a source index or pattern")
        if token.startswith("--"):
            raise ValueError(f"Unknown option for index create: {token}")
        _safe_source_name(token)
        spec = SourceSpec(source=token)
        i += 1
        if i < len(tokens) and tokens[i] in {"--filter", "--filter-json"}:
            option = tokens[i]
            if i + 1 >= len(tokens):
                raise ValueError(f"{option} requires a value")
            spec.filter_type = "query_string" if option == "--filter" else "json"
            spec.filter_value = tokens[i + 1]
            i += 2
        specs.append(spec)
    if not specs:
        raise ValueError("At least one source index or pattern is required")
    return specs


def list_indices(show_all: bool = False) -> list[dict[str, Any]]:
    rows = list(es_client().cat.indices(format="json", h="health,status,index,docs.count,store.size"))
    if show_all:
        return rows
    return [row for row in rows if not row.get("index", "").startswith(".")]


def list_aliases(show_all: bool = False, include_reserved: bool = False) -> list[dict[str, Any]]:
    rows = es_client().cat.aliases(format="json", h="alias,index")
    if show_all:
        return rows
    filtered = [row for row in rows if not row["alias"].startswith(".") and not row["index"].startswith(".")]
    if include_reserved:
        return filtered
    return [row for row in filtered if row.get("alias") not in RESERVED_ALIASES]


def list_managed_templates(include_reserved: bool = False) -> list[dict[str, str]]:
    es = es_client()
    response = es.options(ignore_status=[404]).indices.get_index_template(name=f"{TEMPLATE_PREFIX}-*")
    items = response.get("index_templates", []) if hasattr(response, "get") else []
    rows: list[dict[str, str]] = []
    for item in items:
        name = item.get("name", "")
        meta = item.get("index_template", {}).get("_meta", {})
        if meta.get("managed_by") == "soc-lab" and meta.get("purpose") == "alias-template":
            rows.append({"template": name, "alias": meta.get("alias", ""), "pattern": meta.get("pattern", "")})
    if include_reserved:
        return rows
    return [row for row in rows if row.get("alias") not in RESERVED_ALIASES]


def _index_exists(index: str) -> bool:
    try:
        rows = es_client().cat.indices(index=index, format="json", h="index")
        return any(row.get("index") == index for row in rows)
    except Exception:
        return False


def _alias_backing_indices(alias: str) -> list[str]:
    rows = es_client().options(ignore_status=[404]).cat.aliases(name=alias, format="json", h="index")
    return sorted({row.get("index", "") for row in (rows or []) if row.get("index")})


def _resolve_indices(source: str) -> list[str]:
    if _has_wildcard(source):
        rows = es_client().cat.indices(index=source, format="json", h="index")
        return sorted({row.get("index", "") for row in rows if row.get("index")})
    return [source] if _index_exists(source) else []


def _validate_filter(filter_obj: dict[str, Any], indices: list[str]) -> None:
    es = es_client()
    target = ",".join(indices) if indices else None
    response = es.indices.validate_query(index=target, query=filter_obj, explain=True) if target else es.indices.validate_query(query=filter_obj, explain=True)
    if not response.get("valid"):
        raise ValueError(f"Filter validation failed for [{target or 'all-indices'}]: {json.dumps(response)}")


def create_alias(alias: str, specs: list[SourceSpec], *, force_yes: bool = False) -> dict[str, Any]:
    _safe_alias_name(alias)
    _ensure_not_reserved(alias)
    if _index_exists(alias):
        raise ValueError(f"Refusing to create alias '{alias}': a physical index with that name already exists")

    index_filters: dict[str, dict[str, Any] | None] = {}
    wildcard_specs: list[tuple[str, dict[str, Any] | None]] = []
    for spec in specs:
      _safe_source_name(spec.source)
      filter_obj = _filter_object(spec.filter_type, spec.filter_value)
      matches = _resolve_indices(spec.source)
      if not matches and not _has_wildcard(spec.source):
          raise ValueError(f"Source '{spec.source}' does not match any existing index")
      if filter_obj is not None:
          _validate_filter(filter_obj, matches)
      for index in matches:
          existing = index_filters.get(index, MISSING)
          if existing is not MISSING and existing != filter_obj:
              raise ValueError(f"Index '{index}' is targeted more than once with different filters")
          index_filters[index] = filter_obj
      if _has_wildcard(spec.source):
          wildcard_specs.append((spec.source, filter_obj))

    all_indices = sorted(index_filters.keys())
    if not all_indices and not (force_yes or confirm(
        f"The requested sources do not currently match any Elasticsearch indices. Managed templates can still be created for alias '{alias}'. Continue?"
    )):
        raise SystemExit(0)

    existing_backing = _alias_backing_indices(alias)
    if existing_backing and not (force_yes or confirm(
        f"Alias '{alias}' already exists. This will add the requested sources and managed templates. Continue?"
    )):
        raise SystemExit(0)

    if all_indices:
        actions = []
        for index in all_indices:
            action: dict[str, Any] = {"index": index, "alias": alias}
            if index_filters[index] is not None:
                action["filter"] = index_filters[index]
            actions.append({"add": action})
        es_client().indices.update_aliases(actions=actions)

    for pattern, filter_obj in wildcard_specs:
        aliases_body: dict[str, Any] = {}
        if filter_obj is not None:
            aliases_body["filter"] = filter_obj
        es_client().indices.put_index_template(
            name=_template_name(alias, pattern),
            index_patterns=[pattern],
            priority=300,
            template={"aliases": {alias: aliases_body}},
            _meta={"managed_by": "soc-lab", "purpose": "alias-template", "alias": alias, "pattern": pattern},
        )
    KibanaClient().ensure_data_view(alias, name=alias)
    return {"alias": alias, "matched_indices": all_indices, "wildcard_patterns": [pattern for pattern, _ in wildcard_specs]}


def delete_alias(alias: str, *, force_yes: bool = False) -> dict[str, Any]:
    _safe_alias_name(alias)
    _ensure_not_reserved(alias)
    if _index_exists(alias):
        raise ValueError(f"Refusing to delete '{alias}': it is a physical index, and this command only removes aliases/data views/templates")
    backing = _alias_backing_indices(alias)
    templates = [row["template"] for row in list_managed_templates() if row["alias"] == alias]
    if not (force_yes or confirm(
        f"This will remove alias '{alias}', its SOC Lab managed templates, and the Kibana data view. Physical indices and documents will NOT be deleted. Continue?"
    )):
        raise SystemExit(0)
    if backing:
        es_client().indices.update_aliases(actions=[{"remove": {"index": index, "alias": alias}} for index in backing])
    for template in templates:
        es_client().options(ignore_status=[404]).indices.delete_index_template(name=template)
    KibanaClient().delete_data_view(alias)
    return {"alias": alias, "removed_from": backing, "removed_templates": templates}


def ensure_soc_alerts_alias() -> dict[str, Any]:
    es = es_client()
    current_backing = _alias_backing_indices("soc-alerts")
    if current_backing:
        es.indices.update_aliases(actions=[{"remove": {"index": index, "alias": "soc-alerts"}} for index in current_backing])

    template_name = _template_name("soc-alerts", "suricata-*")
    es.indices.put_index_template(
        name=template_name,
        index_patterns=["suricata-*"],
        priority=500,
        template={"aliases": {"soc-alerts": {"filter": SOC_ALERTS_FILTER}}},
        _meta={"managed_by": "soc-lab", "purpose": "alias-template", "alias": "soc-alerts", "pattern": "suricata-*"},
    )

    suricata_indices = _resolve_indices("suricata-*")
    actions = [{"add": {"index": index, "alias": "soc-alerts", "filter": SOC_ALERTS_FILTER}} for index in suricata_indices]

    if _index_exists("elastalert2_alerts"):
        actions.append({"add": {"index": "elastalert2_alerts", "alias": "soc-alerts"}})

    if actions:
        es.indices.update_aliases(actions=actions)

    KibanaClient().ensure_data_view("soc-alerts", name="Alerts")
    return {
        "alias": "soc-alerts",
        "suricata_indices": suricata_indices,
        "elastalert2_attached": _index_exists("elastalert2_alerts"),
        "template": template_name,
    }


def ensure_suricata_alias() -> dict[str, Any]:
    """suricata → all suricata-* indices (no filter, all event types)."""
    es = es_client()
    template_name = _template_name("suricata", "suricata-*")
    es.indices.put_index_template(
        name=template_name,
        index_patterns=["suricata-*"],
        priority=490,
        template={"aliases": {"suricata": {}}},
        _meta={"managed_by": "soc-lab", "purpose": "alias-template", "alias": "suricata", "pattern": "suricata-*"},
    )
    suricata_indices = _resolve_indices("suricata-*")
    if suricata_indices:
        actions = [{"add": {"index": idx, "alias": "suricata"}} for idx in suricata_indices]
        es.indices.update_aliases(actions=actions)
    kb = KibanaClient()
    # Use suricata-* as the data view pattern so it always matches new date-based
    # indices without depending on the alias being populated at view-creation time.
    kb.delete_data_view("suricata")
    kb.ensure_data_view("suricata-*", name="Suricata")
    return {"alias": "suricata", "indices": suricata_indices, "template": template_name}


def ensure_sigma_alerts_alias() -> dict[str, Any]:
    """sigma-alerts → elastalert2_alerts index."""
    es = es_client()
    if _index_exists("elastalert2_alerts"):
        es.indices.update_aliases(actions=[{"add": {"index": "elastalert2_alerts", "alias": "sigma-alerts"}}])
    KibanaClient().ensure_data_view("sigma-alerts", name="Sigma alerts")
    return {"alias": "sigma-alerts", "attached": _index_exists("elastalert2_alerts")}


def ensure_system_aliases() -> dict[str, Any]:
    return {
        "soc_alerts": ensure_soc_alerts_alias(),
        "suricata": ensure_suricata_alias(),
        "sigma_alerts": ensure_sigma_alerts_alias(),
    }
