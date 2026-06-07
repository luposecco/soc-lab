from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from core.settings import es_url
from core.elastic.kibana import KibanaClient
from core.ingest.preprocess import convert_cef, detect_format, preprocess
from core.ingest.bulk import bulk_ingest_json, bulk_ingest_raw
from core.ingest.pipeline import (
    load_pipeline_to_es,
    resolve_explicit_pipeline,
    wrap_now_pipeline,
)
from core.ingest.llm import OLLAMA_URL, generate_pipeline_ai, ollama_ready


def _safe_base(name: str) -> str:
    stem = Path(name).stem
    base = stem.lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base or "logs"


def report_ingest_quality(index: str, pipeline: str, keep: bool = False) -> dict[str, Any]:
    if pipeline == "none" or keep:
        return {}
    try:
        es_base = es_url()
        total = httpx.get(f"{es_base}/{index}/_count", timeout=10.0).json().get("count", 0)
        errors = httpx.get(f"{es_base}/{index}/_count?q=error.message:*", timeout=10.0).json().get("count", 0)
        parse_errs = httpx.get(f"{es_base}/{index}/_count?q=parse_error:*", timeout=10.0).json().get("count", 0)
        hits = httpx.post(f"{es_base}/{index}/_search", json={"size": 100, "query": {"match_all": {}}}, timeout=10.0).json().get("hits", {}).get("hits", [])
        keep_fields = {"message", "@timestamp", "event", "ecs", "tags", "error", "parse_error"}
        counts = [len([k for k in h.get("_source", {}) if k not in keep_fields]) for h in hits]
        avg_fields = sum(counts) / len(counts) if counts else 0.0
    except Exception:
        return {}
    return {"total": total, "errors": errors, "parse_errors": parse_errs, "avg_fields": avg_fields}


def _now_only_pipeline() -> str:
    """Create/upsert a minimal pipeline that rebases @timestamp to ingest time."""
    name = "_soc-lab-now-passthrough"
    body = {"processors": [
        {"set": {"field": "event.created", "copy_from": "@timestamp", "ignore_failure": True}},
        {"set": {"field": "@timestamp", "value": "{{{_ingest.timestamp}}}"}},
    ]}
    httpx.put(f"{es_url()}/_ingest/pipeline/{name}", json=body, timeout=10.0)
    return name


def _ingest_direct(fmt: str, work_file: Path, index: str, tmp_paths: list[Path], now: bool = False) -> int:
    pipeline = _now_only_pipeline() if now else ""
    if fmt == "json":
        return bulk_ingest_json(work_file, index, pipeline=pipeline)
    if fmt == "cef":
        cef_json, _ = convert_cef(work_file)
        tmp_paths.append(cef_json)
        return bulk_ingest_json(cef_json, index, pipeline=pipeline)
    return 0


def process_file(
    original: Path,
    *,
    keep: bool = False,
    now: bool = False,
    index_override: str = "",
    type_override: str = "",
    use_ai: bool = False,
    llm_ram_mode: str = "none",
    fixed_pipeline: str = "",
) -> dict[str, Any]:
    tmp_paths: list[Path] = []
    try:
        work_file, is_tmp = preprocess(original)
        if is_tmp:
            tmp_paths.append(work_file)

        fmt = detect_format(work_file)
        base = _safe_base(original.name)
        date_suffix = datetime.now().strftime("%Y.%m.%d")
        index = f"{index_override}-{date_suffix}" if index_override else f"logs-{base}-{date_suffix}"
        index_pattern = f"{index.rsplit('-', 1)[0]}-*"

        if not keep:
            es = es_url()
            httpx.delete(f"{es}/_data_stream/{index_pattern}", timeout=8.0)
            httpx.delete(f"{es}/{index_pattern}", timeout=8.0)

        pipeline = ""
        pipeline_used = "none"
        count = 0

        if fixed_pipeline:
            pipeline = fixed_pipeline
            if now:
                pipeline = wrap_now_pipeline(pipeline)
            pipeline_used = pipeline
            count = bulk_ingest_raw(work_file, index, pipeline)

        elif type_override:
            try:
                pipeline = resolve_explicit_pipeline(type_override)
                if now:
                    pipeline = wrap_now_pipeline(pipeline)
                pipeline_used = pipeline
                count = bulk_ingest_raw(work_file, index, pipeline)
            except ValueError as exc:
                if fmt in ("json", "cef"):
                    count = _ingest_direct(fmt, work_file, index, tmp_paths, now=now)
                else:
                    raise RuntimeError(f"{exc}. Try --build-pipeline for text logs.") from exc

        elif use_ai:
            if fmt in ("json", "cef"):
                count = _ingest_direct(fmt, work_file, index, tmp_paths, now=now)
            else:
                pname = f"gen-{base}"
                pfile = generate_pipeline_ai(work_file, pname, llm_ram_mode)
                load_pipeline_to_es(pname, pfile)
                pipeline = pname
                if now:
                    pipeline = wrap_now_pipeline(pipeline)
                pipeline_used = pipeline
                count = bulk_ingest_raw(work_file, index, pipeline)

        else:
            if fmt in ("json", "cef"):
                count = _ingest_direct(fmt, work_file, index, tmp_paths, now=now)
            else:
                raise RuntimeError("For text logs you must specify --type <pipeline> or --build-pipeline")

        KibanaClient().ensure_data_view(index_pattern, name=base)
        quality = report_ingest_quality(index, pipeline_used, keep)
        return {
            "file": str(original),
            "index": index,
            "docs": count,
            "pipeline": pipeline_used,
            "format": fmt,
            "quality": quality,
        }
    finally:
        for p in tmp_paths:
            p.unlink(missing_ok=True)


def upload(
    target: str | None = None,
    *,
    batch: bool = False,
    folder: str | None = None,
    keep: bool = False,
    now: bool = False,
    index_override: str = "",
    type_override: str = "",
    use_ai: bool = False,
    llm_ram_mode: str = "none",
) -> list[dict[str, Any]]:
    if type_override and use_ai:
        raise ValueError("Choose only one mode: --type or --build-pipeline")
    if llm_ram_mode not in ("none", "quit-docker"):
        raise ValueError(f"Invalid --llm-ram-mode '{llm_ram_mode}' (use: none|quit-docker)")

    if batch:
        folder_path = Path(folder or target or "")
        if not folder_path.is_dir():
            raise FileNotFoundError(f"Batch folder not found: {folder_path}")
        files = [f for f in sorted(folder_path.iterdir()) if f.is_file() and not f.name.startswith(".")]
        if not files:
            raise FileNotFoundError(f"No files in folder: {folder_path}")

        shared_pipeline = ""
        if type_override:
            shared_pipeline = resolve_explicit_pipeline(type_override)
        elif use_ai:
            if not ollama_ready():
                raise RuntimeError(f"Ollama required for --build-pipeline at {OLLAMA_URL}")
            first = next((f for f in files), None)
            if first:
                work, is_tmp = preprocess(first)
                fmt = detect_format(work)
                if is_tmp:
                    work.unlink(missing_ok=True)
                if fmt == "other":
                    bname = f"gen-batch-{_safe_base(folder_path.name)}"
                    pfile = generate_pipeline_ai(first, bname, llm_ram_mode)
                    load_pipeline_to_es(bname, pfile)
                    shared_pipeline = bname

        results = []
        for f in files:
            try:
                r = process_file(
                    f, keep=True, now=now, index_override=index_override,
                    type_override=type_override if not shared_pipeline else "",
                    use_ai=use_ai, llm_ram_mode=llm_ram_mode, fixed_pipeline=shared_pipeline,
                )
                results.append(r)
            except Exception as exc:
                results.append({"file": str(f), "error": str(exc)})
        return results

    if not target:
        raise ValueError("Missing target file")
    f = Path(target)
    if not f.is_file():
        raise FileNotFoundError(f"File not found: {f}")
    if use_ai and not ollama_ready():
        raise RuntimeError(f"Ollama required for --build-pipeline at {OLLAMA_URL}")
    return [process_file(
        f, keep=keep, now=now, index_override=index_override,
        type_override=type_override, use_ai=use_ai, llm_ram_mode=llm_ram_mode,
    )]
