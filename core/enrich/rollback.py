from __future__ import annotations

from typing import Any

from core.elastic.client import client as _lab_es
from core.enrich import audit as _audit


def rollback(run_id: str, dry_run: bool = False, force: bool = False) -> dict[str, Any]:
    records = _audit.read_run(run_id)
    if not records:
        return {"run_id": run_id, "error": "No audit records found for this run"}

    revertible = [record for record in records if record.get("rollback_supported")]
    blocked = [
        f"{record.get('index', '')}/{record.get('doc_id', '')}"
        for record in revertible
        if _audit.has_later_field_changes(record)
    ]

    if dry_run:
        return {
            "run_id": run_id,
            "dry_run": True,
            "would_revert": len(revertible),
            "blocked": blocked,
            "operations": [record.get("operation") for record in revertible],
        }

    if blocked and not force:
        return {
            "run_id": run_id,
            "error": "Rollback blocked because later enrichment runs changed the same document fields",
            "blocked": blocked,
        }

    es = _lab_es()
    reverted = 0
    errors: list[str] = []

    for record in reversed(revertible):
        doc_id = record.get("doc_id", "")
        doc_index = record.get("index", "")
        operation = record.get("operation", "")
        before = record.get("before", {})
        if not doc_id or not doc_index:
            continue

        try:
            if _audit.has_later_field_changes(record) and not force:
                errors.append(f"{doc_index}/{doc_id}: later field changes detected")
                continue

            if operation == "update_doc":
                fields_to_restore = {}
                fields_to_remove = []
                for field_name, state in before.items():
                    if not state.get("exists", False):
                        fields_to_remove.append(field_name)
                    else:
                        fields_to_restore[field_name] = state.get("value")
                if fields_to_restore:
                    es.update(index=doc_index, id=doc_id, body={"doc": _expand_fields(fields_to_restore)})
                if fields_to_remove:
                    es.update(
                        index=doc_index,
                        id=doc_id,
                        body={"script": {"source": _remove_fields_script(), "params": {"fields": fields_to_remove}}},
                    )
            elif operation == "remove_fields":
                restore = {
                    field_name: state.get("value")
                    for field_name, state in before.items()
                    if state.get("exists", False)
                }
                if restore:
                    es.update(index=doc_index, id=doc_id, body={"doc": _expand_fields(restore)})
            reverted += 1
        except Exception as exc:
            errors.append(f"{doc_index}/{doc_id}: {exc}")

    return {
        "run_id": run_id,
        "reverted": reverted,
        "total": len(records),
        "errors": errors,
    }


def _expand_fields(fields: dict[str, Any]) -> dict[str, Any]:
    root: dict[str, Any] = {}
    for field_name, value in fields.items():
        current = root
        parts = field_name.split(".")
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value
    return root


def _remove_fields_script() -> str:
    return """
for (field in params.fields) {
  def parts = field.splitOnToken('.');
  def current = ctx._source;
  boolean valid = true;
  for (int i = 0; i < parts.length - 1; i++) {
    if (!(current[parts[i]] instanceof Map)) {
      valid = false;
      break;
    }
    current = current[parts[i]];
  }
  if (valid) {
    current.remove(parts[parts.length - 1]);
  }
}
""".strip()
