from fastapi import APIRouter, HTTPException
from typing import Any, Dict
from config import ALARMFW_ENV

router = APIRouter(prefix="/api/env", tags=["env"])

_SENSITIVE_KEYS = {"TOKEN", "PASS", "PASSWORD", "SECRET", "KEY"}


def _is_sensitive(key: str) -> bool:
    return any(s in key.upper() for s in _SENSITIVE_KEYS)


def _read_env() -> Dict[str, str]:
    if not ALARMFW_ENV.exists():
        return {}
    result = {}
    for line in ALARMFW_ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip()
    return result


def _write_env(data: Dict[str, str]) -> None:
    lines = []
    for k, v in data.items():
        lines.append(f"{k}={v}")
    ALARMFW_ENV.write_text("\n".join(lines) + "\n")


@router.get("")
def get_env() -> Dict[str, Any]:
    env = _read_env()
    return {
        k: ("***" if _is_sensitive(k) and v else v)
        for k, v in env.items()
    }


@router.put("")
def update_env(body: Dict[str, str]) -> Dict[str, Any]:
    existing = _read_env()
    for k, v in body.items():
        if v == "***":
            continue  # masked değeri güncelleme
        existing[k] = v
    _write_env(existing)
    return {"ok": True, "updated_keys": [k for k, v in body.items() if v != "***"]}


@router.put("/{key}")
def set_env_key(key: str, body: Dict[str, Any]) -> Dict[str, Any]:
    value = body.get("value")
    if value is None:
        raise HTTPException(400, "value is required")
    existing = _read_env()
    existing[key] = str(value)
    _write_env(existing)
    return {"ok": True, "key": key}
