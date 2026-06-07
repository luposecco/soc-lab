from __future__ import annotations

import gzip
import json
import re
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def preprocess(file: Path) -> tuple[Path, bool]:
    """Return (work_path, is_tmp). Caller must delete work_path if is_tmp."""
    ext = file.suffix.lower()
    if ext == ".gz":
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
        with gzip.open(file, "rb") as gz:
            tmp.write(gz.read())
        tmp.close()
        return Path(tmp.name), True
    if ext == ".zip":
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
        with zipfile.ZipFile(file) as zf:
            names = zf.namelist()
            if names:
                tmp.write(zf.read(names[0]))
        tmp.close()
        return Path(tmp.name), True
    if ext == ".evtx":
        try:
            import evtx  # type: ignore[import-untyped]
        except ImportError:
            raise RuntimeError("python-evtx not installed; install with: pip install python-evtx")
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".log", mode="w")
        for record in evtx.PyEvtxParser(str(file)).records_json():
            tmp.write(record["data"] + "\n")
        tmp.close()
        return Path(tmp.name), True
    return file, False


def detect_format(file: Path) -> str:
    first_line = ""
    with open(file, errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                first_line = stripped
                break
    try:
        json.loads(first_line)
        return "json"
    except Exception:
        pass
    sample = ""
    with open(file, errors="replace") as f:
        for i, line in enumerate(f):
            if i >= 5:
                break
            sample += line
    if re.search(r"CEF:[0-9]+\|", sample):
        return "cef"
    return "other"


def convert_cef(file: Path) -> tuple[Path, bool]:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w")
    with open(file, errors="replace") as fi:
        for line in fi:
            line = line.rstrip()
            if not line:
                continue
            doc = _parse_cef_line(line)
            tmp.write(json.dumps(doc) + "\n")
    tmp.close()
    return Path(tmp.name), True


def _parse_cef_line(line: str) -> dict[str, Any]:
    idx = line.find("CEF:")
    if idx == -1:
        return {"message": line}
    parts = line[idx:].split("|", 7)
    if len(parts) < 7:
        return {"message": line}
    doc: dict[str, Any] = {
        "cef.version": parts[0].replace("CEF:", "").strip(),
        "cef.device_vendor": parts[1],
        "cef.device_product": parts[2],
        "cef.device_version": parts[3],
        "cef.device_event_class_id": parts[4],
        "cef.name": parts[5],
        "cef.severity": parts[6],
        "@timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if len(parts) == 8:
        for m in re.finditer(r"(\w+)=((?:[^\\=]|\\.)*?)(?=\s+\w+=|$)", parts[7]):
            doc[f"cef.extensions.{m.group(1)}"] = m.group(2).replace("\\=", "=").strip()
    return doc
