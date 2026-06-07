from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from core.settings import repo_root
from core.enrich.clusters import ClusterManager
from core.enrich.context import EnrichmentContext
from core.enrich.scripts import invoke_script, load_script

_DEFAULT_CONFIG = repo_root() / "data" / "enrichments" / "config" / "enrichments.yml"


@dataclass
class EnrichmentDef:
    name: str
    script: str
    targets: list[str]
    enabled: bool = True
    schedule: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "script": self.script,
            "targets": self.targets,
            "enabled": self.enabled,
            "schedule": self.schedule,
            "type": self.meta.get("type", "play_batch"),
            "display_name": self.meta.get("name", self.name),
            "description": self.meta.get("description", ""),
        }


def load_enrichment_config(path: Path | None = None) -> list[dict[str, Any]]:
    config_path = Path(path) if path else _DEFAULT_CONFIG
    if not config_path.exists():
        return []
    raw = yaml.safe_load(config_path.read_text()) or {}
    enrichments = []
    for name, cfg in (raw.get("enrichments") or {}).items():
        script = load_script(cfg.get("script", ""), f"enrich_meta_{name}")
        enrichments.append(EnrichmentDef(
            name=name,
            script=cfg.get("script", ""),
            targets=cfg.get("targets") or ["lab"],
            enabled=bool(cfg.get("enabled", True)),
            schedule=cfg.get("schedule") or {},
            meta=script.meta,
        ).to_dict())
    return enrichments


def run_enrichment(
    name: str,
    cluster: str | None = None,
    dry_run: bool = False,
    params: dict[str, Any] | None = None,
    config_path: Path | None = None,
) -> dict[str, Any]:
    config_path = Path(config_path) if config_path else _DEFAULT_CONFIG
    if not config_path.exists():
        raise FileNotFoundError(f"Enrichments config not found: {config_path}")

    raw = yaml.safe_load(config_path.read_text()) or {}
    enrichments = raw.get("enrichments") or {}
    if name not in enrichments:
        raise ValueError(f"Enrichment {name!r} not found in config")

    cfg = enrichments[name]
    if not cfg.get("enabled", True):
        raise ValueError(f"Enrichment {name!r} is disabled")

    targets = cfg.get("targets") or ["lab"]
    if cluster and cluster not in targets:
        raise ValueError(f"Cluster {cluster!r} is not allowed for enrichment {name!r}")
    clients = [cluster] if cluster else targets
    script_rel = cfg.get("script", "")
    script = load_script(script_rel, f"enrich_run_{name}")

    mgr = ClusterManager.load()
    run_id = f"{name}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    results = []

    for cluster_name in clients:
        es = mgr.get_client(cluster_name)
        ctx = EnrichmentContext(es=es, cluster=cluster_name, enrichment=name, run_id=run_id, dry_run=dry_run)
        try:
            invoke_script(script, ctx, params=params)
            results.append({"cluster": cluster_name, "ok": True, **ctx.summary()})
        except Exception as exc:
            results.append({"cluster": cluster_name, "ok": False, "error": str(exc), "run_id": run_id})

    return {
        "run_id": run_id,
        "enrichment": name,
        "type": script.meta.get("type", "play_batch"),
        "results": results,
    }
