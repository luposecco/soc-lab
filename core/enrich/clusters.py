from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from elasticsearch import Elasticsearch

from core.settings import repo_root

_DEFAULT_CONFIG = repo_root() / "data" / "enrichments" / "config" / "clusters.yml"


@dataclass
class ClusterDef:
    name: str
    mode: str  # internal | external | managed
    hosts: list[str]
    auth_type: str = ""   # api_key | basic | none
    auth_env: str = ""    # env var name holding the credential
    auth_user: str = ""
    auth_pass_env: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mode": self.mode,
            "hosts": self.hosts,
            "auth_type": self.auth_type or "none",
        }


class ClusterManager:
    def __init__(self, clusters: dict[str, ClusterDef]) -> None:
        self._clusters = clusters
        self._clients: dict[str, Elasticsearch] = {}

    @classmethod
    def load(cls, path: Path | None = None) -> ClusterManager:
        config_path = Path(path) if path else _DEFAULT_CONFIG
        clusters: dict[str, ClusterDef] = {}

        # Always include the internal lab cluster
        clusters["lab"] = ClusterDef(
            name="lab",
            mode="internal",
            hosts=[os.environ.get("SOC_LAB_ES_URL", "http://localhost:9200")],
        )

        if config_path.exists():
            raw = yaml.safe_load(config_path.read_text()) or {}
            for name, cfg in (raw.get("clusters") or {}).items():
                if name == "lab":
                    clusters["lab"] = ClusterDef(
                        name="lab",
                        mode=cfg.get("mode", "internal"),
                        hosts=cfg.get("hosts", ["http://localhost:9200"]),
                    )
                    continue
                auth = cfg.get("auth") or {}
                clusters[name] = ClusterDef(
                    name=name,
                    mode=cfg.get("mode", "external"),
                    hosts=cfg.get("hosts", []),
                    auth_type=auth.get("type", "none"),
                    auth_env=auth.get("env", ""),
                    auth_user=auth.get("user", ""),
                    auth_pass_env=auth.get("pass_env", ""),
                )

        return cls(clusters)

    def _make_client(self, name: str) -> Elasticsearch:
        if name not in self._clusters:
            raise ValueError(f"Unknown cluster: {name!r}. Defined clusters: {list(self._clusters)}")
        c = self._clusters[name]
        kwargs: dict[str, Any] = {"hosts": c.hosts}
        if c.auth_type == "api_key" and c.auth_env:
            key = os.environ.get(c.auth_env, "")
            if not key:
                raise EnvironmentError(f"Cluster {name!r}: env var {c.auth_env!r} is not set")
            kwargs["api_key"] = key
        elif c.auth_type == "basic":
            user = c.auth_user
            password = os.environ.get(c.auth_pass_env, "") if c.auth_pass_env else ""
            if not user:
                raise ValueError(f"Cluster {name!r}: basic auth requires auth.user")
            kwargs["basic_auth"] = (user, password)
        elif c.auth_type not in ("", "none"):
            raise ValueError(f"Cluster {name!r}: unsupported auth type {c.auth_type!r}")
        return Elasticsearch(**kwargs)

    def get_client(self, name: str) -> Elasticsearch:
        if name not in self._clients:
            self._clients[name] = self._make_client(name)
        return self._clients[name]

    def ping(self, name: str) -> dict[str, Any]:
        try:
            es = self._make_client(name)
            t0 = time.monotonic()
            info = es.info()
            latency_ms = round((time.monotonic() - t0) * 1000, 1)
            version = info.get("version", {}).get("number", "unknown")
            return {"name": name, "ok": True, "latency_ms": latency_ms, "version": version}
        except Exception as exc:
            return {"name": name, "ok": False, "error": str(exc)}

    def ping_all(self) -> list[dict[str, Any]]:
        return [self.ping(name) for name in self._clusters]

    def list_all(self) -> list[dict[str, Any]]:
        return [c.to_dict() for c in self._clusters.values()]

    def names(self) -> list[str]:
        return list(self._clusters.keys())
