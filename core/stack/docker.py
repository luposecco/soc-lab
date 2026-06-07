from __future__ import annotations

import json
import subprocess
from typing import Any

from core.settings import repo_root


def list_services() -> list[dict[str, Any]]:
    result = subprocess.run(
        ["docker", "compose", "ps", "--all", "--format", "json"],
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    rows = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows
