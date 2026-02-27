from fastapi import APIRouter, HTTPException
from typing import Any, Dict
import yaml
from config import ALARMFW_CONFIG

router = APIRouter(prefix="/api/policies", tags=["policies"])

_DEDUP_FILE = "policies/dedup.yaml"


@router.get("/dedup")
def get_dedup() -> Dict[str, Any]:
    f = ALARMFW_CONFIG / _DEDUP_FILE
    if not f.exists():
        raise HTTPException(404, "dedup.yaml not found")
    data = yaml.safe_load(f.read_text()) or {}
    return data.get("dedup_policy") or data


@router.put("/dedup")
def update_dedup(body: Dict[str, Any]) -> Dict[str, Any]:
    f = ALARMFW_CONFIG / _DEDUP_FILE
    if not f.exists():
        raise HTTPException(404, "dedup.yaml not found")
    data = yaml.safe_load(f.read_text()) or {}
    if "dedup_policy" in data:
        data["dedup_policy"].update(body)
    else:
        data.update(body)
    f.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False))
    return {"ok": True}
