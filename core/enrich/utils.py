from __future__ import annotations

from typing import Any


def default_query(query: dict[str, Any] | None) -> dict[str, Any]:
    return query or {"match_all": {}}


def nested_field_exists(doc: dict[str, Any], field_path: str) -> bool:
    current: Any = doc
    for part in field_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def nested_field_value(doc: dict[str, Any], field_path: str) -> Any:
    current: Any = doc
    for part in field_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(field_path)
        current = current[part]
    return current


def field_state(doc: dict[str, Any], field_path: str) -> dict[str, Any]:
    if not nested_field_exists(doc, field_path):
        return {"exists": False}
    return {"exists": True, "value": nested_field_value(doc, field_path)}
