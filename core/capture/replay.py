from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.settings import repo_root
from core.elastic.client import client as es_client


def ensure_soc_alerts_alias() -> None:
    from core.elastic.aliases import ensure_soc_alerts_alias as ensure_reserved_soc_alerts_alias

    ensure_reserved_soc_alerts_alias()


def _delete_suricata_indices() -> None:
    es = es_client()
    rows = es.options(ignore_status=[404]).cat.indices(index="suricata-*", format="json", h="index")
    for row in rows or []:
        idx = row.get("index", "")
        if idx:
            es.options(ignore_status=[404]).indices.delete(index=idx)


def _clear_elastalert_indices() -> None:
    es = es_client()
    for idx in ["elastalert2_alerts", "elastalert2_alerts_status", "elastalert2_alerts_silence"]:
        es.options(ignore_status=[404]).delete_by_query(
            index=idx,
            body={"query": {"match_all": {}}},
        )


def _resolve_pcap(pcap_arg: str) -> Path:
    root = repo_root()
    pcap_dir = root / "data" / "pcap"
    p = Path(pcap_arg)
    if p.is_absolute():
        abs_path = p.resolve()
    elif str(p).startswith("data/pcap/") or str(p).startswith("./data/pcap/"):
        abs_path = (root / p).resolve()
    else:
        abs_path = (pcap_dir / p).resolve()

    if not abs_path.exists():
        raise FileNotFoundError(f"PCAP not found: {abs_path}")

    pcap_dir_real = pcap_dir.resolve()
    if not str(abs_path).startswith(str(pcap_dir_real) + "/"):
        raise ValueError(f"PCAP must be inside ./pcap (got: {abs_path})")

    return abs_path


def _shift_timestamps(eve_path: Path) -> None:
    events: list[Any] = []
    with open(eve_path) as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                events.append(json.loads(ln))
            except Exception:
                events.append(ln)

    earliest = None
    for e in events:
        if not isinstance(e, dict):
            continue
        try:
            ts = datetime.fromisoformat(e.get("timestamp", "").replace("+0000", "+00:00"))
            earliest = ts if earliest is None or ts < earliest else earliest
        except Exception:
            pass

    if earliest is not None:
        offset = datetime.now(timezone.utc) - earliest
        fmt = "%Y-%m-%dT%H:%M:%S.%f+0000"
        for e in events:
            if not isinstance(e, dict):
                continue
            try:
                ts = datetime.fromisoformat(e.get("timestamp", "").replace("+0000", "+00:00"))
                e["timestamp"] = (ts + offset).strftime(fmt)
            except Exception:
                pass

    with open(eve_path, "w") as f:
        for e in events:
            f.write((json.dumps(e) if isinstance(e, dict) else str(e)) + "\n")


def _wait_for_docs(timeout: int = 60) -> dict[str, int]:
    es = es_client()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            suri = es.options(ignore_status=[404]).count(index="suricata-*").get("count", 0)
            soc = es.options(ignore_status=[404]).count(index="soc-alerts").get("count", 0)
            if suri > 0 or soc > 0:
                return {"suricata_docs": suri, "soc_alerts_docs": soc}
        except Exception:
            pass
        time.sleep(1)
    return {
        "suricata_docs": 0,
        "soc_alerts_docs": 0,
        "warning": "No docs visible yet (Filebeat may still be shipping)",
    }


def replay(pcap_arg: str, *, keep: bool = False, now: bool = False) -> dict[str, Any]:
    abs_path = _resolve_pcap(pcap_arg)
    pcap_dir_real = (repo_root() / "data" / "pcap").resolve()
    pcap_rel = str(abs_path.relative_to(pcap_dir_real))

    # Pause Filebeat when clearing (keep=False) so it can't recreate suricata-*
    # from old eve.json data between the index delete and the clear.
    # Also pause when shifting timestamps (now=True) so it reads shifted events.
    pause_filebeat = not keep or now
    if pause_filebeat:
        subprocess.run(["docker", "stop", "filebeat"], capture_output=True)

    if not keep:
        _delete_suricata_indices()
        _clear_elastalert_indices()
        subprocess.run(["docker", "stop", "elastalert2"], capture_output=True)
        subprocess.run(
            ["docker", "exec", "suricata", "sh", "-c",
             ": > /var/log/suricata/eve.json; : > /var/log/suricata/suricata.log"],
            capture_output=True,
        )

    ensure_soc_alerts_alias()

    result = subprocess.run(
        ["docker", "exec", "suricata", "suricata",
         "-c", "/etc/suricata/suricata.yaml",
         "-r", f"/pcap/{pcap_rel}",
         "--pidfile", "/var/run/suricata-replay.pid",
         "-l", "/var/log/suricata",
         "-k", "none"],
        capture_output=True, text=True,
    )

    if now:
        eve = repo_root() / "runtime" / "logs" / "suricata" / "eve.json"
        if eve.exists():
            _shift_timestamps(eve)

    if pause_filebeat:
        subprocess.run(["docker", "start", "filebeat"], capture_output=True)

    if result.returncode != 0:
        raise RuntimeError(f"Suricata replay failed: {result.stderr.strip()}")

    ensure_soc_alerts_alias()
    from core.elastic.aliases import ensure_suricata_alias
    ensure_suricata_alias()

    if not keep:
        subprocess.run(["docker", "start", "elastalert2"], capture_output=True)

    docs = _wait_for_docs()
    return {"pcap": str(abs_path), "keep": keep, "now": now, **docs}
