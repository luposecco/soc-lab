from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from core.settings import es_url, repo_root

_PIPELINES_ES = lambda: repo_root() / "data" / "pipelines" / "elasticsearch"
_PIPELINES_CUSTOM = lambda: repo_root() / "data" / "pipelines" / "custom"
_PIPELINES_GEN = lambda: repo_root() / "data" / "pipelines" / "generated"


def _pipeline_exists_in_es(name: str) -> bool:
    try:
        r = httpx.get(f"{es_url()}/_ingest/pipeline/{name}", timeout=8.0)
        return r.status_code == 200
    except Exception:
        return False


def _pipeline_file_for_type(t: str) -> Path | None:
    if t.endswith(".yml") or t.endswith(".yaml"):
        p = Path(t)
        if p.exists():
            return p.resolve()
        p2 = repo_root() / t
        if p2.exists():
            return p2.resolve()
        return None
    for candidate in [
        _PIPELINES_ES() / f"{t}.yml",
        _PIPELINES_ES() / f"{t}.yaml",
        _PIPELINES_CUSTOM() / f"{t}.yml",
        _PIPELINES_CUSTOM() / f"{t}.yaml",
        _PIPELINES_GEN() / f"{t}.yml",
        _PIPELINES_GEN() / f"{t}.yaml",
    ]:
        if candidate.exists():
            return candidate
    return None


def _pipeline_hints(q: str) -> list[str]:
    import difflib
    names: list[str] = []
    for d in [_PIPELINES_ES(), _PIPELINES_CUSTOM(), _PIPELINES_GEN()]:
        if d.is_dir():
            for fn in d.iterdir():
                if fn.suffix in (".yml", ".yaml"):
                    names.append(fn.stem)
    uniq = sorted(set(names))
    if not q or not uniq:
        return []
    q_lower = q.lower()
    subs = [n for n in uniq if q_lower in n.lower() or n.lower() in q_lower]
    close = difflib.get_close_matches(q_lower, uniq, n=12, cutoff=0.45)
    out: list[str] = []
    seen: set[str] = set()
    for n in subs + close:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out[:5]


def _yml_to_json(file: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-untyped]
    return yaml.safe_load(file.read_text())


def load_pipeline_to_es(name: str, file: Path) -> None:
    body = _yml_to_json(file)
    r = httpx.put(f"{es_url()}/_ingest/pipeline/{name}", json=body, timeout=15.0)
    if r.status_code != 200:
        raise RuntimeError(f"Failed to load pipeline '{name}' from {file} (HTTP {r.status_code})")


def resolve_explicit_pipeline(t: str) -> str:
    if _pipeline_exists_in_es(t):
        return t
    p = _pipeline_file_for_type(t)
    if p is None:
        hints = _pipeline_hints(t)
        msg = f"Pipeline '{t}' not found in Elasticsearch or local folders."
        if hints:
            msg += " Did you mean: " + ", ".join(hints)
        raise ValueError(msg)
    name = p.stem
    load_pipeline_to_es(name, p)
    return name


def wrap_now_pipeline(base: str) -> str:
    now_name = f"{base}-now"
    body = {
        "processors": [
            {"pipeline": {"name": base}},
            {"set": {"field": "event.created", "copy_from": "@timestamp", "ignore_failure": True}},
            {"set": {"field": "@timestamp", "value": "{{{_ingest.timestamp}}}"}},
        ]
    }
    httpx.put(f"{es_url()}/_ingest/pipeline/{now_name}", json=body, timeout=10.0)
    return now_name


def list_pipeline_dirs() -> dict[str, Path]:
    return {
        "elasticsearch": _PIPELINES_ES(),
        "custom": _PIPELINES_CUSTOM(),
        "generated": _PIPELINES_GEN(),
    }
