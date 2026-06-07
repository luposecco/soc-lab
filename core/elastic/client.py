from __future__ import annotations

from elasticsearch import Elasticsearch

from core.settings import es_url


def client() -> Elasticsearch:
    return Elasticsearch(es_url())
