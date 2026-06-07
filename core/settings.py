from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def es_url() -> str:
    return os.environ.get("SOC_LAB_ES_URL", "http://localhost:9200")


def kibana_url() -> str:
    return os.environ.get("SOC_LAB_KIBANA_URL", "http://localhost:5601")


def api_url() -> str:
    return os.environ.get("SOC_LAB_API_URL", "http://127.0.0.1:8000")


def api_host() -> str:
    return os.environ.get("SOC_LAB_API_HOST", "127.0.0.1")


def api_port() -> int:
    return int(os.environ.get("SOC_LAB_API_PORT", "8000"))


def dash_host() -> str:
    return os.environ.get("SOC_LAB_DASH_HOST", "127.0.0.1")


def dash_port() -> int:
    return int(os.environ.get("SOC_LAB_DASH_PORT", "8050"))
