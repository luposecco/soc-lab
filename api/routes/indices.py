from __future__ import annotations

from fastapi import APIRouter, Query

from core.elastic.aliases import RESERVED_ALIASES, create_alias, delete_alias, list_aliases, list_indices, list_managed_templates, parse_source_specs
from core.elastic.kibana import KibanaClient
from api.models import AliasCreateRequest
from api.utils import bad

router = APIRouter(prefix="/api")


@router.get("/indices")
def indices_list(all: bool = Query(False)) -> list[dict]:
    try:
        return list_indices(show_all=all)
    except Exception as exc:
        raise bad(exc)


@router.get("/aliases")
def aliases_list() -> dict:
    try:
        aliases = []
        for row in list_aliases(show_all=False, include_reserved=True):
            alias = row.get("alias", "")
            aliases.append({
                **row,
                "system_managed": alias in RESERVED_ALIASES,
                "manageable": alias not in RESERVED_ALIASES,
            })

        templates = []
        for row in list_managed_templates(include_reserved=True):
            alias = row.get("alias", "")
            templates.append({
                **row,
                "system_managed": alias in RESERVED_ALIASES,
                "manageable": alias not in RESERVED_ALIASES,
            })

        template_map: dict[str, list[str]] = {}
        for row in templates:
            template_map.setdefault(row.get("alias", ""), []).append(row.get("pattern", ""))

        grouped: dict[str, dict] = {}
        for row in aliases:
            alias = row.get("alias", "")
            entry = grouped.setdefault(alias, {
                "alias": alias,
                "indices": [],
                "patterns": template_map.get(alias, []),
                "system_managed": row.get("system_managed", False),
                "manageable": row.get("manageable", True),
            })
            index = row.get("index", "")
            if index:
                entry["indices"].append(index)

        for alias, patterns in template_map.items():
            grouped.setdefault(alias, {
                "alias": alias,
                "indices": [],
                "patterns": patterns,
                "system_managed": alias in RESERVED_ALIASES,
                "manageable": alias not in RESERVED_ALIASES,
            })

        data_view_titles: set[str] = set()
        try:
            kibana = KibanaClient()
            if kibana.is_available():
                data_view_titles = {view.get("title", "") for view in kibana.list_data_views()}
        except Exception:
            data_view_titles = set()

        grouped_aliases = []
        for alias in sorted(grouped):
            entry = grouped[alias]
            indices = sorted({index for index in entry.get("indices", []) if index})
            patterns = sorted({pattern for pattern in entry.get("patterns", []) if pattern})
            grouped_aliases.append({
                **entry,
                "indices": indices,
                "patterns": patterns,
                "has_wildcard": bool(patterns),
                "future_only": bool(patterns and not indices),
                "data_view_synced": alias in data_view_titles,
            })

        summary = {
            "visible_aliases": len(grouped_aliases),
            "system_aliases": sum(1 for row in grouped_aliases if row.get("system_managed")),
            "user_aliases": sum(1 for row in grouped_aliases if not row.get("system_managed")),
            "wildcard_templates": len(templates),
            "data_views_synced": sum(1 for row in grouped_aliases if row.get("data_view_synced")),
        }
        return {"aliases": aliases, "managed_templates": templates, "grouped_aliases": grouped_aliases, "summary": summary}
    except Exception as exc:
        raise bad(exc)


@router.post("/aliases")
def aliases_create(request: AliasCreateRequest) -> dict:
    try:
        source_tokens = list(request.sources)
        if request.filter_value:
            option = "--filter-json" if request.filter_mode == "json" else "--filter"
            source_tokens = [item for source in request.sources for item in (source, option, request.filter_value)]
        return create_alias(request.alias, parse_source_specs(source_tokens), force_yes=True)
    except Exception as exc:
        raise bad(exc, 400)


@router.delete("/aliases/{alias}")
def aliases_delete(alias: str) -> dict:
    try:
        return delete_alias(alias, force_yes=True)
    except Exception as exc:
        raise bad(exc, 400)
