import yaml
from fastapi import APIRouter, HTTPException
from typing import Any, Dict
from config import ALARMFW_CONFIG

router = APIRouter(prefix="/api/notifiers", tags=["notifiers"])

_SENSITIVE = {"password", "token", "pass", "secret"}


def _mask(cfg: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in cfg.items():
        if any(s in k.lower() for s in _SENSITIVE) and v:
            out[k] = "***"
        else:
            out[k] = v
    return out


def _notifier_files():
    d = ALARMFW_CONFIG / "notifiers"
    return sorted(d.glob("*.yaml")) if d.exists() else []


@router.get("")
async def list_notifiers() -> Dict[str, Any]:
    def _list_notifiers() -> Dict[str, Any]:
        result = {}
        for f in _notifier_files():
            data = yaml.safe_load(f.read_text()) or {}
            for name, cfg in (data.get("notifiers") or {}).items():
                result[name] = {**_mask(cfg or {}), "_source_file": f.name}
        return result

    return _list_notifiers()


@router.get("/{name}")
async def get_notifier(name: str) -> Dict[str, Any]:
    def _get_notifier() -> Dict[str, Any]:
        for f in _notifier_files():
            data = yaml.safe_load(f.read_text()) or {}
            notifiers = data.get("notifiers") or {}
            if name in notifiers:
                return {**_mask(notifiers[name] or {}), "_source_file": f.name}
        raise HTTPException(404, f"Notifier '{name}' not found")

    return _get_notifier()


@router.put("/{name}")
async def update_notifier(name: str, body: Dict[str, Any]) -> Dict[str, Any]:
    def _update_notifier() -> Dict[str, Any]:
        for f in _notifier_files():
            data = yaml.safe_load(f.read_text()) or {}
            notifiers = data.get("notifiers") or {}
            if name in notifiers:
                body.pop("_source_file", None)
                existing = notifiers[name] or {}
                for k, v in body.items():
                    if v != "***":
                        existing[k] = v
                data["notifiers"][name] = existing
                f.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False))
                return {"ok": True, "name": name}
        raise HTTPException(404, f"Notifier '{name}' not found")

    return _update_notifier()
