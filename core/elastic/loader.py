from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from core.elastic.client import client as es_client

SO_RAW = "https://raw.githubusercontent.com/Security-Onion-Solutions/securityonion/2.4/main/salt/elasticsearch/files/ingest"
SO_RAW_DYNAMIC = "https://raw.githubusercontent.com/Security-Onion-Solutions/securityonion/2.4/main/salt/elasticsearch/files/ingest-dynamic"
SO_RAW_BASE = "https://raw.githubusercontent.com/Security-Onion-Solutions/securityonion/2.4/main"

SO_PIPELINES = [
    "suricata.common", "suricata.alert", "suricata.dnp3", "suricata.dns", "suricata.smtp",
    "suricata.http", "suricata.flow", "suricata.tls", "suricata.ssh", "suricata.smb",
    "suricata.ftp", "suricata.ftp_data", "suricata.fileinfo", "suricata.krb5", "suricata.snmp",
    "suricata.ike", "suricata.rdp", "suricata.nfs", "suricata.tftp", "suricata.dhcp",
    "suricata.sip", "suricata.tld", "suricata.dnsv3", "common", "common.nids", "dns.tld",
    "http.status",
]

REQUIRED_ECS_COMPONENTS = [
    "ecs", "base", "agent", "client", "destination", "dns", "error", "event", "file",
    "hash", "http", "log", "network", "observer", "related", "rule", "server", "source",
    "suricata", "tls", "url", "user", "user_agent",
]


def _wait_for_es(timeout: int = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            es_client().cluster.health()
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError("Elasticsearch did not become ready in time")


def _fetch(url: str, timeout: float = 15.0) -> str | None:
    try:
        r = httpx.get(url, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except Exception:
        return None


def _strip_jinja(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not re.match(r"^\s*\{%-?.*%\}\s*$", ln))


def _patch_pipeline(name: str, body: dict[str, Any]) -> dict[str, Any]:
    if name == "suricata.alert":
        procs = body.get("processors", [])
        procs = [x for x in procs if not ("set" in x and x["set"].get("field") == "_index")]
        nids_idx = next(
            (k for k, v in enumerate(procs) if "pipeline" in v and v["pipeline"].get("name") == "common.nids"),
            len(procs),
        )
        procs.insert(nids_idx, {
            "pipeline": {
                "if": "ctx.message2?.app_proto != null",
                "name": "suricata.{{message2.app_proto}}",
                "ignore_missing_pipeline": True,
                "ignore_failure": True,
            }
        })
        procs.insert(nids_idx + 1, {"set": {"field": "event.dataset", "value": "suricata.alert"}})
        body["processors"] = procs

    elif name == "suricata.common":
        for proc in body.get("processors", []):
            q = proc.get("pipeline")
            if isinstance(q, dict) and q.get("name") == "suricata.{{event.dataset}}":
                q["ignore_missing_pipeline"] = True
                q["ignore_failure"] = True

    elif name == "common":
        for proc in body.get("processors", []):
            q = proc.get("pipeline")
            if isinstance(q, dict):
                q.setdefault("ignore_missing_pipeline", True)
                q.setdefault("ignore_failure", True)

    return body


def load_so_pipeline(name: str) -> dict[str, Any]:
    if name == "common":
        raw = _fetch(f"{SO_RAW_DYNAMIC}/{name}")
        if raw is None:
            return {"name": name, "ok": False, "error": "Missing in SO repo"}
        raw = _strip_jinja(raw)
    else:
        raw = _fetch(f"{SO_RAW}/{name}")
        if raw is None:
            return {"name": name, "ok": False, "error": "Missing in SO repo"}

    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {"name": name, "ok": False, "error": str(exc)}

    body = _patch_pipeline(name, body)

    try:
        es_client().ingest.put_pipeline(id=name, body=body)
        return {"name": name, "ok": True}
    except Exception as exc:
        return {"name": name, "ok": False, "error": str(exc)}


def sync_pipelines() -> dict[str, Any]:
    _wait_for_es()
    results = [load_so_pipeline(p) for p in SO_PIPELINES]
    return {
        "loaded": [r["name"] for r in results if r["ok"]],
        "failed": [r["name"] for r in results if not r["ok"]],
        "results": results,
    }


def sync_templates() -> dict[str, Any]:
    _wait_for_es()
    es = es_client()
    loaded: list[str] = []
    failed: list[str] = []

    for comp in REQUIRED_ECS_COMPONENTS:
        name = f"ecs.{comp}"
        path = f"salt/elasticsearch/templates/component/ecs/{comp}.json"
        raw = _fetch(f"{SO_RAW_BASE}/{path}")
        if raw is None:
            failed.append(name)
            continue
        try:
            body = json.loads(raw)
            es.cluster.put_component_template(name=name, body=body)
            loaded.append(name)
        except Exception:
            failed.append(name)

    if not loaded:
        raise RuntimeError("No SO component templates were loaded")

    es.indices.put_index_template(
        name="suricata-so-ecs",
        index_patterns=["suricata-*"],
        composed_of=sorted(loaded),
        priority=250,
        template={
            "settings": {
                "index.mapping.ignore_malformed": True,
                "index.mapping.total_fields.limit": 5000,
                "index.number_of_replicas": 0,
            }
        },
    )
    return {"loaded": loaded, "failed": failed, "composed_template": "suricata-so-ecs"}


def sync_all() -> dict[str, Any]:
    templates = sync_templates()
    pipelines = sync_pipelines()
    return {"templates": templates, "pipelines": pipelines}
