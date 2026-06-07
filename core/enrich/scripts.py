from __future__ import annotations

import importlib.util
import inspect
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from core.settings import repo_root

VALID_ENRICHMENT_TYPES = {"play_single", "play_batch", "play_periodic"}


@dataclass
class EnrichmentScript:
    path: Path
    module: ModuleType
    meta: dict[str, Any]


def resolve_script_path(script_path: str) -> Path:
    path = repo_root() / "data" / "enrichments" / script_path
    if not path.exists():
        raise FileNotFoundError(f"Enrichment script not found: {path}")
    return path


def load_script(script_path: str, module_name: str) -> EnrichmentScript:
    path = resolve_script_path(script_path)
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load enrichment script: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    meta = _normalize_meta(getattr(module, "ENRICHMENT_META", {}), path)
    run_fn = getattr(module, "run", None)
    if not callable(run_fn):
        raise AttributeError(f"Enrichment script {path} must define a run(...) function")
    return EnrichmentScript(path=path, module=module, meta=meta)


def invoke_script(script: EnrichmentScript, ctx: Any, params: dict[str, Any] | None = None) -> None:
    run_fn = script.module.run
    arity = _run_positional_arity(run_fn)
    runtime_params = params or {}
    if arity == 1:
        if runtime_params:
            raise TypeError(
                f"Enrichment script {script.path.name} defines run(ctx) only; runtime params are not supported"
            )
        run_fn(ctx)
        return
    if arity == 2:
        run_fn(ctx, runtime_params)
        return
    raise TypeError(f"Enrichment script {script.path.name} must define run(ctx) or run(ctx, params)")


def _run_positional_arity(run_fn: Any) -> int:
    sig = inspect.signature(run_fn)
    positional = [
        param for param in sig.parameters.values()
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    return len(positional)


def _normalize_meta(raw_meta: Any, path: Path) -> dict[str, Any]:
    if raw_meta is None:
        raw_meta = {}
    if not isinstance(raw_meta, dict):
        raise TypeError(f"ENRICHMENT_META in {path} must be a dictionary")

    enrichment_type = raw_meta.get("type", "play_batch")
    if enrichment_type not in VALID_ENRICHMENT_TYPES:
        raise ValueError(
            f"ENRICHMENT_META.type in {path} must be one of {sorted(VALID_ENRICHMENT_TYPES)}"
        )

    return {
        "type": enrichment_type,
        "name": raw_meta.get("name") or path.stem,
        "description": raw_meta.get("description", ""),
    }
