from fastapi import APIRouter, Query
from typing import Any, Dict, List, Optional
import json
import sqlite3
from config import ALARMFW_STATE

router = APIRouter(prefix="/api/alarms", tags=["alarms"])


@router.get("")
def list_alarms(
    limit: int = Query(50, ge=1, le=500),
    status: Optional[str] = Query(None),
) -> List[Dict[str, Any]]:
    """Outbox klasöründeki alarm JSON dosyalarını döner (en yeniden eskiye)."""
    outbox = ALARMFW_STATE / "outbox"
    if not outbox.exists():
        return []

    files = sorted(outbox.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    result = []
    for f in files:
        try:
            data = json.loads(f.read_text())
            if status and data.get("status") != status.upper():
                continue
            data["_filename"] = f.name
            result.append(data)
            if len(result) >= limit:
                break
        except Exception:
            pass
    return result


@router.get("/state")
def get_alarm_state() -> List[Dict[str, Any]]:
    """SQLite state tablosunu döner."""
    db_path = ALARMFW_STATE / "alarmfw.sqlite"
    if not db_path.exists():
        return []
    try:
        con = sqlite3.connect(str(db_path))
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT dedup_key, last_status, last_sent_ts, last_change_ts FROM alarm_state ORDER BY last_change_ts DESC"
        ).fetchall()
        con.close()
        return [dict(r) for r in rows]
    except Exception as e:
        return [{"error": str(e)}]


@router.delete("/outbox")
def clear_outbox() -> Dict[str, Any]:
    """Outbox klasörünü temizle."""
    outbox = ALARMFW_STATE / "outbox"
    if not outbox.exists():
        return {"deleted": 0}
    files = list(outbox.glob("*.json"))
    for f in files:
        f.unlink()
    return {"deleted": len(files)}
