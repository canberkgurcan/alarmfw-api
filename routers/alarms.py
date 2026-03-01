from fastapi import APIRouter, Query
from typing import Any, Dict, List, Optional
import json
import sqlite3
from config import ALARMFW_STATE

router = APIRouter(prefix="/api/alarms", tags=["alarms"])

STATE_DB = ALARMFW_STATE / "alarmfw.sqlite"


def _open_db():
    if not STATE_DB.exists():
        return None
    conn = sqlite3.connect(str(STATE_DB), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn


@router.get("")
def list_alarms(
    limit: int = Query(50, ge=1, le=500),
    status: Optional[str] = Query(None),
) -> List[Dict[str, Any]]:
    """SQLite alarm_state tablosundaki payload_json'ları döner (en yeniden eskiye)."""
    conn = _open_db()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT payload_json, last_change_ts FROM alarm_state "
            "WHERE payload_json IS NOT NULL "
            "ORDER BY last_change_ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        try:
            data = json.loads(row["payload_json"])
            if status and data.get("status") != status.upper():
                continue
            result.append(data)
        except Exception:
            pass
    return result


@router.get("/state")
def get_alarm_state() -> List[Dict[str, Any]]:
    """SQLite state tablosunu döner."""
    conn = _open_db()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT dedup_key, last_status, last_sent_ts, last_change_ts, alarm_name "
            "FROM alarm_state ORDER BY last_change_ts DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        return [{"error": str(e)}]
    finally:
        conn.close()


@router.delete("/outbox")
def clear_outbox() -> Dict[str, Any]:
    """Outbox klasörünü temizle (eski compat)."""
    outbox = ALARMFW_STATE / "outbox"
    if not outbox.exists():
        return {"deleted": 0}
    files = list(outbox.glob("*.json"))
    for f in files:
        f.unlink()
    return {"deleted": len(files)}
