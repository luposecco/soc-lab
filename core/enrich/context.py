from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Generator

from elasticsearch import Elasticsearch

from core.enrich import audit as _audit
from core.enrich.utils import default_query, field_state

_SET_FIELDS_SCRIPT = """
for (entry in params.fields.entrySet()) {
  def parts = entry.getKey().splitOnToken('.');
  def current = ctx._source;
  for (int i = 0; i < parts.length - 1; i++) {
    if (!(current[parts[i]] instanceof Map)) {
      current[parts[i]] = new HashMap();
    }
    current = current[parts[i]];
  }
  current[parts[parts.length - 1]] = entry.getValue();
}
""".strip()

_REMOVE_FIELDS_SCRIPT = """
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


class EnrichmentContext:
    def __init__(
        self,
        es: Elasticsearch,
        cluster: str,
        enrichment: str,
        run_id: str | None = None,
        dry_run: bool = False,
    ) -> None:
        self._es = es
        self.cluster = cluster
        self.enrichment = enrichment
        self.run_id = run_id or f"{enrichment}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.dry_run = dry_run
        self._stats = {"created": 0, "updated": 0, "deleted": 0}

    @property
    def raw(self) -> Elasticsearch:
        return self._es

    def get(self, index: str, id: str) -> dict[str, Any]:
        hit = self._es.get(index=index, id=id)
        return self._format_hit(hit)

    def search(
        self,
        index: str,
        query: dict[str, Any] | None = None,
        size: int = 100,
        sort: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"index": index, "query": default_query(query), "size": size}
        if sort is not None:
            kwargs["sort"] = sort
        result = self._es.search(**kwargs)
        return [self._format_hit(hit) for hit in result.get("hits", {}).get("hits", [])]

    def scan(
        self,
        index: str,
        query: dict[str, Any] | None = None,
        batch_size: int = 500,
    ) -> Generator[dict[str, Any], None, None]:
        result = self._es.search(index=index, query=default_query(query), size=batch_size, scroll="2m")
        scroll_id = result.get("_scroll_id")
        hits = result.get("hits", {}).get("hits", [])
        while hits:
            for hit in hits:
                yield self._format_hit(hit)
            if not scroll_id:
                break
            result = self._es.scroll(scroll_id=scroll_id, scroll="2m")
            scroll_id = result.get("_scroll_id")
            hits = result.get("hits", {}).get("hits", [])
        if scroll_id:
            try:
                self._es.clear_scroll(scroll_id=scroll_id)
            except Exception:
                pass

    def exists(self, index: str, id: str) -> bool:
        return bool(self._es.exists(index=index, id=id))

    def index_doc(self, index: str, doc: dict[str, Any], id: str | None = None) -> dict[str, Any]:
        if self.dry_run:
            return {"dry_run": True, "would_create": 1, "index": index, "id": id}

        if id:
            result = self._es.create(index=index, id=id, document=doc)
        else:
            result = self._es.index(index=index, document=doc)

        doc_id = result.get("_id", id)
        self._stats["created"] += 1
        _audit.write({
            "run_id": self.run_id,
            "enrichment": self.enrichment,
            "cluster": self.cluster,
            "index": index,
            "doc_id": doc_id,
            "operation": "index_doc",
            "before": {},
            "after": {"created": True},
            "changed_fields": [],
            "rollback_supported": False,
        })
        return {"created": 1, "id": doc_id, "index": index}

    def update_doc(self, index: str, id: str, fields: dict[str, Any]) -> dict[str, Any]:
        before_doc = self.get(index=index, id=id)
        before = {field_name: field_state(before_doc.get("_source", {}), field_name) for field_name in fields}

        if self.dry_run:
            return {"dry_run": True, "would_update": 1, "index": index, "id": id, "fields": list(fields)}

        self._es.update(
            index=index,
            id=id,
            script={"source": _SET_FIELDS_SCRIPT, "params": {"fields": fields}},
        )
        self._stats["updated"] += 1
        _audit.write({
            "run_id": self.run_id,
            "enrichment": self.enrichment,
            "cluster": self.cluster,
            "index": index,
            "doc_id": id,
            "operation": "update_doc",
            "before": before,
            "after": fields,
            "changed_fields": list(fields),
            "rollback_supported": True,
        })
        return {"updated": 1, "index": index, "id": id, "fields": list(fields)}

    def remove_fields(self, index: str, id: str, fields: list[str]) -> dict[str, Any]:
        before_doc = self.get(index=index, id=id)
        before = {field_name: field_state(before_doc.get("_source", {}), field_name) for field_name in fields}

        if self.dry_run:
            return {"dry_run": True, "would_update": 1, "index": index, "id": id, "fields": fields}

        self._es.update(
            index=index,
            id=id,
            script={"source": _REMOVE_FIELDS_SCRIPT, "params": {"fields": fields}},
        )
        self._stats["updated"] += 1
        _audit.write({
            "run_id": self.run_id,
            "enrichment": self.enrichment,
            "cluster": self.cluster,
            "index": index,
            "doc_id": id,
            "operation": "remove_fields",
            "before": before,
            "after": {},
            "changed_fields": fields,
            "rollback_supported": True,
        })
        return {"updated": 1, "index": index, "id": id, "removed": fields}

    def delete_doc(self, index: str, id: str) -> dict[str, Any]:
        if self.dry_run:
            return {"dry_run": True, "would_delete": 1, "index": index, "id": id}

        self._es.delete(index=index, id=id)
        self._stats["deleted"] += 1
        _audit.write({
            "run_id": self.run_id,
            "enrichment": self.enrichment,
            "cluster": self.cluster,
            "index": index,
            "doc_id": id,
            "operation": "delete_doc",
            "before": {},
            "after": {"deleted": True},
            "changed_fields": [],
            "rollback_supported": False,
        })
        return {"deleted": 1, "index": index, "id": id}

    def update_by_query(
        self,
        index: str,
        query: dict[str, Any] | None,
        fields: dict[str, Any],
        batch_size: int = 500,
    ) -> dict[str, Any]:
        docs = list(self.scan(index=index, query=query, batch_size=batch_size))
        if self.dry_run:
            return {"dry_run": True, "would_update": len(docs), "fields": list(fields)}

        updated = 0
        for doc in docs:
            result = self.update_doc(index=doc.get("_index", index), id=doc.get("_id", ""), fields=fields)
            updated += result.get("updated", 0)
        return {"updated": updated, "fields": list(fields)}

    def remove_by_query(
        self,
        index: str,
        query: dict[str, Any] | None,
        fields: list[str],
        batch_size: int = 500,
    ) -> dict[str, Any]:
        docs = list(self.scan(index=index, query=query, batch_size=batch_size))
        if self.dry_run:
            return {"dry_run": True, "would_update": len(docs), "fields": fields}

        updated = 0
        for doc in docs:
            result = self.remove_fields(index=doc.get("_index", index), id=doc.get("_id", ""), fields=fields)
            updated += result.get("updated", 0)
        return {"removed": fields, "updated": updated}

    def create_index(
        self,
        index: str,
        mappings: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.dry_run:
            return {"dry_run": True, "would_create": index}
        kwargs: dict[str, Any] = {}
        if mappings:
            kwargs["mappings"] = mappings
        if settings:
            kwargs["settings"] = settings
        self._es.indices.create(index=index, **kwargs)
        return {"created": index}

    def delete_index(self, index: str) -> dict[str, Any]:
        if self.dry_run:
            return {"dry_run": True, "would_delete": index}
        self._es.indices.delete(index=index)
        return {"deleted": index}

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "enrichment": self.enrichment,
            "cluster": self.cluster,
            "dry_run": self.dry_run,
            "docs_created": self._stats["created"],
            "docs_updated": self._stats["updated"],
            "docs_deleted": self._stats["deleted"],
        }

    def _format_hit(self, hit: dict[str, Any]) -> dict[str, Any]:
        source = hit.get("_source", {})
        return {"_id": hit.get("_id", ""), "_index": hit.get("_index", ""), "_source": source, **source}
