from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from core.settings import es_url

BULK_SIZE = 500


def _bulk_flush(batch: str, pipeline_param: str = "") -> int:
    url = f"{es_url()}/_bulk{pipeline_param}"
    try:
        response = httpx.post(url, content=batch.encode(), headers={"Content-Type": "application/x-ndjson"}, timeout=60.0)
        response.raise_for_status()
        r = response.json()
    except Exception:
        return 0
    ok = 0
    for item in r.get("items", []):
        op = item.get("create") or item.get("index") or {}
        if not op.get("error"):
            ok += 1
    return ok


def bulk_ingest_json(file: Path, index: str, pipeline: str = "") -> int:
    pp = f"?pipeline={pipeline}" if pipeline else ""
    total = 0
    batch = ""
    n = 0
    with open(file, errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            batch += f'{{"create":{{"_index":"{index}"}}}}\n{line}\n'
            n += 1
            if n >= BULK_SIZE:
                total += _bulk_flush(batch, pp)
                batch = ""
                n = 0
    if batch:
        total += _bulk_flush(batch, pp)
    return total


def bulk_ingest_raw(file: Path, index: str, pipeline: str = "") -> int:
    pp = f"?pipeline={pipeline}" if pipeline else ""
    ts = datetime.now(timezone.utc).isoformat()
    total = 0
    batch = ""
    n = 0
    with open(file, errors="replace") as f:
        for line in f:
            line = line.rstrip()
            if not line:
                continue
            esc = json.dumps(line)
            batch += f'{{"create":{{"_index":"{index}"}}}}\n{{"message":{esc},"@timestamp":"{ts}"}}\n'
            n += 1
            if n >= BULK_SIZE:
                total += _bulk_flush(batch, pp)
                batch = ""
                n = 0
    if batch:
        total += _bulk_flush(batch, pp)
    return total
