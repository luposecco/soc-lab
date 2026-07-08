from __future__ import annotations

import re
from pathlib import Path

from core.settings import repo_root

_SCHEDULE_RE = re.compile(r"^([1-9]\d*)([smhd])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_ENRICHMENTS_ROOT = repo_root() / "data" / "enrichments"
_SCRIPTS_ROOT = _ENRICHMENTS_ROOT / "scripts"


def parse_interval_seconds(value: str) -> int:
    raw = (value or "").strip().lower()
    match = _SCHEDULE_RE.fullmatch(raw)
    if not match:
        raise ValueError("Schedule must use interval format like 30s, 15m, 2h, or 1d")
    amount = int(match.group(1))
    unit = match.group(2)
    return amount * _UNIT_SECONDS[unit]


def normalize_schedule(value: str) -> str:
    raw = (value or "").strip().lower()
    if not raw:
        return ""
    parse_interval_seconds(raw)
    return raw


def normalize_script_path(value: str, *, must_exist: bool = False) -> str:
    raw = (value or "").strip().replace("\\", "/")
    if not raw:
        raise ValueError("Script path is required")
    path = Path(raw)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Script path must be relative to data/enrichments/scripts")
    if path.suffix != ".py":
        raise ValueError("Script path must point to a .py file")
    if not raw.startswith("scripts/"):
        raw = f"scripts/{raw}"
        path = Path(raw)
    full = (_ENRICHMENTS_ROOT / path).resolve()
    scripts_root = _SCRIPTS_ROOT.resolve()
    if full != scripts_root and scripts_root not in full.parents:
        raise ValueError("Script path must stay under data/enrichments/scripts")
    if must_exist and not full.exists():
        raise FileNotFoundError(f"Enrichment script not found: {raw}")
    return raw


def resolve_script_file(value: str, *, must_exist: bool = False) -> Path:
    return (_ENRICHMENTS_ROOT / normalize_script_path(value, must_exist=must_exist)).resolve()
