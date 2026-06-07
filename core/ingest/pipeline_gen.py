"""
Generate a validated Elasticsearch ingest pipeline from sample logs using Ollama.

Moved from scripts/tools/pipeline_generator.py.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

ES_URL = os.environ.get("SOC_LAB_ES_URL", "http://localhost:9200")
OLLAMA_URL = "http://localhost:11434"
MAX_RETRIES = 3
LLM_TIMEOUT = 120
VALIDATE_WITH_ES = os.environ.get("PIPELINE_GEN_VALIDATE_ES", "true").lower() == "true"


def read_samples(path: str, limit: int = 24) -> list[str]:
    lines: list[str] = []
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if line.strip():
                lines.append(line)
            if len(lines) >= 400:
                break

    if len(lines) <= limit:
        return lines

    chosen: list[str] = []
    seen: set[str] = set()

    def add(idx: int) -> None:
        if 0 <= idx < len(lines):
            s = lines[idx]
            if s not in seen:
                seen.add(s)
                chosen.append(s)

    for i in range(8):
        add(i)
    mid = len(lines) // 2
    for i in range(-4, 4):
        add(mid + i)
    for i in range(8, 0, -1):
        add(len(lines) - i)
    for i in sorted(range(len(lines)), key=lambda j: len(lines[j]), reverse=True)[:20]:
        add(i)

    return chosen[:limit]


def simulate_pipeline(pipeline: dict[str, Any], lines: list[str]) -> tuple[bool, str, Any]:
    if not VALIDATE_WITH_ES:
        return True, "validation skipped", []
    docs = [{"_source": {"message": l}} for l in lines[:5]]
    req = urllib.request.Request(
        ES_URL + "/_ingest/pipeline/_simulate",
        data=json.dumps({"pipeline": pipeline, "docs": docs}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")[:800]
        except Exception:
            body = ""
        return False, f"simulate http {e.code}: {body}", []
    except Exception as e:
        return False, f"simulate error: {e}", []

    docs_out = [d for d in out.get("docs", []) if isinstance(d, dict)]
    if not docs_out:
        return False, "simulate returned no docs", []

    good = err_count = 0
    extracted_counts: list[int] = []
    parsed_examples: list[dict[str, Any]] = []
    line_feedback: list[dict[str, Any]] = []
    for i, d in enumerate(docs_out):
        src_line = lines[i] if i < len(lines) else ""
        if "error" in d:
            err_count += 1
            line_feedback.append({"line": src_line, "matched": False, "fields": 0})
            continue
        src = d.get("doc", {}).get("_source", {}) or {}
        keys = [k for k in src.keys() if k not in ("message", "@timestamp", "event", "ecs", "tags", "error", "parse_error")]
        extracted_counts.append(len(keys))
        line_feedback.append({"line": src_line, "matched": len(keys) > 0, "fields": len(keys)})
        if keys and len(parsed_examples) < 2:
            parsed_examples.append({k: src.get(k) for k in keys[:8]})
        if keys:
            good += 1
    need = max(1, len(docs_out) // 2)
    avg_fields = (sum(extracted_counts) / len(extracted_counts)) if extracted_counts else 0.0
    details = {"parsed_examples": parsed_examples, "line_feedback": line_feedback}
    if good >= need and avg_fields >= 2.0 and err_count <= max(1, len(docs_out) // 3):
        return True, "", details
    return False, f"insufficient parse quality: good={good}/{len(docs_out)} avg_fields={avg_fields:.2f} errors={err_count}", details


def call_ollama(model: str, prompt: str) -> str:
    payload = {"model": model, "prompt": prompt, "stream": True, "options": {"temperature": 0.0, "num_predict": 500}}
    req = urllib.request.Request(
        OLLAMA_URL + "/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    out = ""
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT + 20) as r:
        for line in r:
            chunk = json.loads(line.decode())
            out += chunk.get("response", "")
            if chunk.get("done"):
                break
    return out.strip()


def unload_model(model: str) -> None:
    payload = {"model": model, "keep_alive": 0}
    req = urllib.request.Request(
        OLLAMA_URL + "/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception:
        pass


def choose_model() -> str:
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=10) as r:
            tags = json.load(r)
    except Exception:
        return ""
    models = [m.get("name", "") for m in tags.get("models", [])]
    priority = ["qwen2.5-coder:7b", "qwen2.5:7b", "mistral:7b", "llama3.1:8b", "qwen3:8b"]
    for p in priority:
        for m in models:
            if p in m:
                return m
    return ""


def extract_grok(text: str) -> str:
    text = text.strip()
    if "```" in text:
        inside: list[str] = []
        in_block = False
        for ln in text.split("\n"):
            if ln.startswith("```"):
                in_block = not in_block
                continue
            if in_block:
                inside.append(ln)
        text = "\n".join(inside).strip() or text
    for ln in text.split("\n"):
        ln = ln.strip().strip('"')
        if "%{" in ln:
            return ln
    return text.split("\n")[0].strip().strip('"')


def literal_presence_check(pattern: str, sample_line: str) -> tuple[bool, str]:
    if not sample_line:
        return True, ""
    if sample_line[0] in ("[", "<", "("):
        lit = "\\" + sample_line[0]
        if lit not in pattern and sample_line[0] not in pattern:
            return False, f"pattern lost starting literal '{sample_line[0]}'"
    if "|" in sample_line and "\\|" not in pattern and "|" not in pattern:
        return False, "pattern lost '|' separators"
    keys = [m.group(1) + "=" for m in re.finditer(r"\b([A-Za-z_][\w.-]*)=", sample_line)][:6]
    if keys:
        kept = sum(1 for k in keys if k in pattern)
        if "kvpairs" in pattern:
            if kept < 1:
                return False, "pattern uses kvpairs but lost all key=value literals"
        elif kept < min(2, len(keys)):
            return False, "pattern lost key=value literals"
    return True, ""


def structural_hint(lines: list[str]) -> str:
    if not lines:
        return ""
    first = lines[0]
    hints = []
    if first.startswith("["):
        hints.append("sample lines start with '[' and include a closing ']' before the rest of fields")
    if "<" in first and ">" in first:
        hints.append("sample includes angle-bracket segments; keep those literals if present")
    if ' topic="' in first:
        hints.append("sample uses quoted values like topic=\"...\"; preserve quotes in pattern")
    if "=" in first:
        hints.append("sample contains '=' assignments; do not convert these tokens into plain words")
    return "; ".join(hints)


def grok_pipeline(name: str, pattern: str) -> dict[str, Any]:
    return {
        "description": f"Generated grok pipeline for {name}",
        "processors": [
            {"grok": {"field": "message", "patterns": [pattern]}},
            {"date": {"field": "timestamp", "target_field": "@timestamp", "formats": ["ISO8601", "yyyy-MM-dd HH:mm:ss.SSS", "yyyy-MM-dd HH:mm:ss", "yyyy/MM/dd-HH:mm:ssX"], "ignore_failure": True}},
            {"kv": {"field": "kvpairs", "field_split": " ", "value_split": "=", "trim_key": '"', "trim_value": '"', "ignore_failure": True}},
            {"remove": {"field": "kvpairs", "ignore_missing": True}},
        ],
        "on_failure": [{"set": {"field": "parse_error", "value": "{{_ingest.on_failure_message}}"}}],
    }


def generate_grok_pipeline(lines: list[str], name: str, model: str) -> dict[str, Any]:
    sample = "\n".join(lines[:10])
    shape_hint = structural_hint(lines)
    last_error = last_pattern = ""
    last_parsed: list[dict[str, Any]] = []
    last_line_feedback: list[dict[str, Any]] = []

    for attempt in range(1, MAX_RETRIES + 1):
        prompt = (
            "Create one Elasticsearch grok pattern for these logs. "
            "Output only the raw grok pattern, no markdown, no explanation. "
            "Use known grok tokens (examples: TIMESTAMP_ISO8601, IP, NUMBER, WORD, DATA, GREEDYDATA, NOTSPACE, URI, PATH) and choose the best ones for these logs.\n"
            "Do not invent or move literal characters; copy exact prefixes and separators from the sample lines.\n"
            "If a token appears as key=value in the sample, keep it as key=value in the pattern.\n"
            "Do not assume logs are key=value; infer structure from the sample exactly.\n"
            "Preserve literal wrappers/delimiters from the sample (for example [] <> quotes prefixes).\n"
            "If logs are 'timestamp + key=value pairs', prefer capturing timestamp as 'timestamp'.\n"
            "If logs are not clearly KV, make your best field-name guesses and still return one practical pattern.\n\n"
            "Important: avoid repeated captures like (%{DATA:key}=%{GREEDYDATA:value})* because they keep only the last pair. "
            "When repeated key=value tokens appear anywhere in the line (start/middle/end), capture that contiguous block once as 'kvpairs', and capture any surrounding text as separate fields (for example prefix/suffix).\n\n"
            f"Logs:\n{sample}\n\n"
        )
        prompt += f"Attempt: {attempt}/{MAX_RETRIES}\n"
        if last_error:
            prompt += f"Previous attempt failed: {last_error}\nReturn corrected grok pattern only.\n"
        if last_pattern:
            prompt += f"Previous pattern was: {last_pattern}\nAdjust it instead of starting from scratch.\n"
        if "good=0" in last_error:
            first_line = lines[0] if lines else ""
            prompt += (
                "The previous pattern matched zero lines. "
                "Your next pattern must preserve the exact literal prefix and separators from this sample line: "
                f"{json.dumps(first_line, ensure_ascii=True)}\n"
            )
        if last_parsed:
            prompt += "Previous parsed output sample:\n"
            for i, doc in enumerate(last_parsed, start=1):
                prompt += f"- doc{i}: {json.dumps(doc, ensure_ascii=True)}\n"
        if last_line_feedback:
            prompt += "Previous per-line match results:\n"
            for i, fb in enumerate(last_line_feedback[:5], start=1):
                prompt += f"- line{i}: matched={str(fb.get('matched')).lower()} fields={fb.get('fields', 0)} text={json.dumps(fb.get('line', ''), ensure_ascii=True)}\n"
        prompt += (
            "Quality target: capture at least 3 meaningful named fields per line; "
            "if a timestamp exists, capture it into field 'timestamp'. "
            "Return one anchored pattern using ^ and $. "
            "If the line appears key=value based, you may capture the remainder as 'kvpairs' so a KV processor can parse it.\n"
        )
        if shape_hint:
            prompt += f"Structure hints: {shape_hint}.\n"
        try:
            raw = call_ollama(model, prompt)
        except Exception as e:
            last_error = str(e)
            continue

        pat = extract_grok(raw)
        if not pat:
            last_error = "empty or invalid grok pattern"
            continue
        ok_lit, lit_reason = literal_presence_check(pat, lines[0] if lines else "")
        if not ok_lit:
            last_error = f"literal-check failed: {lit_reason}"
            last_pattern = pat
            continue
        last_pattern = pat
        candidate = grok_pipeline(name, pat)
        ok, err, details = simulate_pipeline(candidate, lines)
        if ok:
            return candidate
        last_error = err
        last_parsed = details.get("parsed_examples", []) if isinstance(details, dict) else []
        last_line_feedback = details.get("line_feedback", []) if isinstance(details, dict) else []

    suffix = f"; last_pattern={last_pattern}" if last_pattern else ""
    raise RuntimeError(f"Failed to produce valid grok pipeline: {last_error}{suffix}")


def generate(samples_file: str, pipeline_name: str, model: str | None = None) -> dict[str, Any]:
    if model is None:
        model = choose_model()
    if not model:
        raise RuntimeError("No suitable 7B/8B Ollama model found. Install one (e.g.: ollama pull qwen2.5-coder:7b)")

    lines = read_samples(samples_file)
    if not lines:
        raise ValueError("No sample lines in file")

    try:
        return generate_grok_pipeline(lines, pipeline_name, model)
    finally:
        unload_model(model)
