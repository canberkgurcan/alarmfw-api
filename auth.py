import os
from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

_API_KEY = os.getenv("ALARMFW_API_KEY", "")
_header  = APIKeyHeader(name="X-API-Key", auto_error=False)


def _check(key: str | None) -> str:
    if not _API_KEY:
        return "anonymous"
    if key != _API_KEY:
        raise HTTPException(403, "Invalid or missing API key")
    return key or "anonymous"


async def require_operator(key: str | None = Security(_header)) -> str:
    return _check(key)


async def require_admin(key: str | None = Security(_header)) -> str:
    return _check(key)
