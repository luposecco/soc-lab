from __future__ import annotations

import importlib.util
import inspect
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from core.enrich.validation import resolve_script_file

@dataclass
class EnrichmentScript:
    path: Path
    module: ModuleType


def resolve_script_path(script_path: str) -> Path:
    return resolve_script_file(script_path, must_exist=True)


def load_script(script_path: str, module_name: str) -> EnrichmentScript:
    path = resolve_script_path(script_path)
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load enrichment script: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    run_fn = getattr(module, "run", None)
    if not callable(run_fn):
        raise AttributeError(f"Enrichment script {path} must define a run(ctx) function")
    return EnrichmentScript(path=path, module=module)


def invoke_script(script: EnrichmentScript, ctx: Any, params: dict[str, Any] | None = None) -> None:
    ctx.params = params or {}
    run_fn = script.module.run
    arity = _run_positional_arity(run_fn)
    if arity >= 2:
        run_fn(ctx, ctx.params)
    else:
        run_fn(ctx)


def _run_positional_arity(run_fn: Any) -> int:
    sig = inspect.signature(run_fn)
    positional = [
        param for param in sig.parameters.values()
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    return len(positional)
