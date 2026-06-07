from __future__ import annotations

from fastapi import APIRouter

from core.elastic.aliases import list_aliases, list_indices
from core.stack.docker import list_services
from api.utils import bad

router = APIRouter(prefix="/api/overview")


@router.get("/summary")
def overview_summary() -> dict:
    try:
        services = list_services()
        return {
            "service_count": len(services),
            "running_services": sum(1 for row in services if row.get("State") == "running"),
            "indices": list_indices(show_all=False),
            "aliases": list_aliases(show_all=False),
        }
    except Exception as exc:
        raise bad(exc)
