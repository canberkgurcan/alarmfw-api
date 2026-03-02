from fastapi import APIRouter, HTTPException
from typing import Any, Dict, List
from pathlib import Path
from datetime import datetime
import os
import requests
from config import ALARMFW_CONFIG

router = APIRouter(prefix="/api/admin", tags=["admin"])

CONF_D = Path(ALARMFW_CONFIG).parent / "legacy/podhealthalarm/conf.d"
DEFAULT_ZABBIX_URL = "http://10.86.36.216:9000/webhook"


def _is_true(v: str | None) -> bool:
    return (v or "").strip().lower() == "true"


def _read_conf(path: Path) -> Dict[str, str]:
    d: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def _get_zabbix_url() -> str:
    return os.getenv("ZABBIX_URL", DEFAULT_ZABBIX_URL).strip()


@router.get("/zabbix-namespaces")
def list_zabbix_namespaces() -> List[Dict[str, Any]]:
    """ZABBIX_ENABLED=true olan namespace'leri döner."""
    if not CONF_D.exists():
        return []
    result = []
    for f in sorted(CONF_D.glob("*.conf")):
        raw = _read_conf(f)
        if not _is_true(raw.get("ZABBIX_ENABLED")):
            continue
        result.append({
            "name":       f.stem,
            "severity":   raw.get("SEVERITY", "5"),
            "alertgroup": raw.get("ALERTGROUP", ""),
            "alertkey":   raw.get("POD_HEALTH_ALERTKEY", "OCP_POD_HEALTH"),
            "node":       raw.get("NODE", ""),
            "department": raw.get("DEPARTMENT", ""),
        })
    return result


@router.post("/zabbix-send")
def send_zabbix(body: Dict[str, Any]) -> Dict[str, Any]:
    """Zabbix webhook'una alarm (type=1) veya clear (type=2) eventi gönderir."""
    namespace  = str(body.get("namespace", "")).strip()
    event_type = str(body.get("type", "")).strip()

    if not namespace:
        raise HTTPException(400, "namespace gerekli")
    if event_type not in ("1", "2"):
        raise HTTPException(400, "type '1' (alarm) veya '2' (clear) olmalı")

    f = CONF_D / f"{namespace}.conf"
    if not f.exists():
        raise HTTPException(404, f"Namespace '{namespace}' bulunamadı")

    ns_cfg = _read_conf(f)

    description = (
        "[ALARMFW][WARN] alarm active"
        if event_type == "1"
        else "[ALARMFW][WARN][OK] alarm clear"
    )

    payload = {
        "type":           event_type,
        "severity":       ns_cfg.get("SEVERITY", "5"),
        "alertgroup":     ns_cfg.get("ALERTGROUP", ""),
        "alertkey":       ns_cfg.get("POD_HEALTH_ALERTKEY", "OCP_POD_HEALTH"),
        "description":    description,
        "node":           ns_cfg.get("NODE", ""),
        "department":     ns_cfg.get("DEPARTMENT", ""),
        "occurrencedate": datetime.now().strftime("%d-%m-%Y %H:%M:%S"),
        "tablename":      "italarm",
    }

    zabbix_url = _get_zabbix_url()

    try:
        resp = requests.post(
            zabbix_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        try:
            response_body = resp.json()
        except Exception:
            response_body = resp.text
        return {
            "ok":          resp.ok,
            "status_code": resp.status_code,
            "response":    response_body,
            "payload":     payload,
        }
    except Exception as e:
        return {
            "ok":      False,
            "error":   str(e),
            "payload": payload,
        }
