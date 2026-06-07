from __future__ import annotations

from fastapi import HTTPException


def bad(exc: Exception, status: int = 503) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


def human_size(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024  # type: ignore[assignment]
    return f"{size:.1f} TB"
