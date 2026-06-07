from __future__ import annotations

from fastapi import APIRouter

from core.stack.docker import list_services
from core.stack.health import stack_health_summary, stack_service_cards
from core.stack.runtime import compose_down, compose_restart_service, compose_stop_service, compose_up, compose_up_service, service_logs
from api.utils import bad

router = APIRouter(prefix="/api/stack")


@router.get("/services")
def stack_services() -> dict:
    try:
        services = list_services()
        return {"services": services, "summary": stack_health_summary(services), "cards": stack_service_cards(services)}
    except Exception as exc:
        raise bad(exc)


@router.post("/start")
def stack_start() -> dict:
    try:
        return compose_up()
    except Exception as exc:
        raise bad(exc)


@router.post("/stop")
def stack_stop() -> dict:
    try:
        return compose_down(remove_volumes=False)
    except Exception as exc:
        raise bad(exc)


@router.post("/reset")
def stack_reset() -> dict:
    try:
        return compose_down(remove_volumes=True)
    except Exception as exc:
        raise bad(exc)


@router.post("/services/{service}/start")
def stack_service_start(service: str) -> dict:
    try:
        return compose_up_service(service)
    except Exception as exc:
        raise bad(exc)


@router.post("/services/{service}/stop")
def stack_service_stop(service: str) -> dict:
    try:
        return compose_stop_service(service)
    except Exception as exc:
        raise bad(exc)


@router.post("/services/{service}/restart")
def stack_service_restart(service: str) -> dict:
    try:
        return compose_restart_service(service)
    except Exception as exc:
        raise bad(exc)


def _format_logs(raw: str, service: str) -> str:
    import json as _json
    lines = raw.splitlines()
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # filebeat / beats: NDJSON with log.level + @timestamp + message
        if line.startswith("{") and '"log.level"' in line:
            try:
                obj = _json.loads(line)
                ts = obj.get("@timestamp", "")[:19].replace("T", " ")
                level = obj.get("log.level", "info").upper()
                msg = obj.get("message", line)
                out.append(f"{ts} [{level}] {msg}")
                continue
            except Exception:
                pass
        out.append(line)
    return "\n".join(out)


@router.get("/logs/{service}")
def stack_logs(service: str, tail: int = 50) -> dict:
    try:
        raw = service_logs(service, tail=tail)
        return {"service": service, "tail": tail, "logs": _format_logs(raw, service)}
    except Exception as exc:
        raise bad(exc)
