import json
import sqlite3
import time
from fastapi import APIRouter, Query
from typing import Any, Dict, List, Optional
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


def _list_alarms(limit: int, status: Optional[str]) -> List[Dict[str, Any]]:
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


@router.get("")
async def list_alarms(
    limit: int = Query(50, ge=1, le=500),
    status: Optional[str] = Query(None),
) -> List[Dict[str, Any]]:
    return _list_alarms(limit, status)


def _get_alarm_state() -> List[Dict[str, Any]]:
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


@router.get("/state")
async def get_alarm_state() -> List[Dict[str, Any]]:
    return _get_alarm_state()


def _get_alarm_history(
    limit: int,
    status: Optional[str],
    cluster: Optional[str],
    namespace: Optional[str],
    alarm_name: Optional[str],
    dedup_key: Optional[str],
    since_ts: Optional[int],
    hours: Optional[int],
) -> List[Dict[str, Any]]:
    """alarm_history tablosundan event log döner. Tablo yoksa boş liste."""
    conn = _open_db()
    if conn is None:
        return []
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alarm_history (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                event_ts      INTEGER NOT NULL,
                timestamp_utc TEXT,
                event_type    TEXT NOT NULL,
                dedup_key     TEXT NOT NULL,
                alarm_name    TEXT,
                status        TEXT NOT NULL,
                prev_status   TEXT,
                severity      TEXT,
                cluster       TEXT,
                namespace     TEXT,
                message       TEXT,
                payload_json  TEXT
            )
        """)
        conn.commit()

        where: List[str] = []
        params: List[Any] = []

        if status:
            where.append("status = ?")
            params.append(status.upper())
        if cluster:
            where.append("cluster = ?")
            params.append(cluster)
        if namespace:
            where.append("namespace = ?")
            params.append(namespace)
        if alarm_name:
            where.append("alarm_name = ?")
            params.append(alarm_name)
        if dedup_key:
            where.append("dedup_key = ?")
            params.append(dedup_key)
        if since_ts is not None:
            where.append("event_ts >= ?")
            params.append(since_ts)
        elif hours is not None:
            cutoff = int(time.time()) - hours * 3600
            where.append("event_ts >= ?")
            params.append(cutoff)

        sql = "SELECT * FROM alarm_history"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY event_ts DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    result = []
    for row in rows:
        entry = dict(row)
        raw_payload = entry.pop("payload_json", None)
        if raw_payload:
            try:
                entry["payload"] = json.loads(raw_payload)
            except Exception:
                pass
        result.append(entry)
    return result


@router.get("/history")
async def get_alarm_history(
    limit: int = Query(100, ge=1, le=1000),
    status: Optional[str] = Query(None),
    cluster: Optional[str] = Query(None),
    namespace: Optional[str] = Query(None),
    alarm_name: Optional[str] = Query(None),
    dedup_key: Optional[str] = Query(None),
    since_ts: Optional[int] = Query(None),
    hours: Optional[int] = Query(None),
) -> List[Dict[str, Any]]:
    return _get_alarm_history(limit, status, cluster, namespace, alarm_name, dedup_key, since_ts, hours)


def _get_alarm_metrics() -> Dict[str, Any]:
    """alarm_state tablosundan türetilmiş runtime metrikleri döner."""
    conn = _open_db()
    if conn is None:
        return {
            "version": 0,
            "updated_at_utc": "",
            "rules_evaluated_total": 0,
            "notifications_sent_total": 0,
            "notifications_suppressed_total": 0,
            "evaluation_count_total": 0,
            "evaluation_latency_ms_last": 0,
            "evaluation_latency_ms_sum": 0,
            "evaluation_latency_ms_avg": 0,
            "last_exit_code": 0,
        }
    try:
        total = conn.execute("SELECT COUNT(*) FROM alarm_state").fetchone()[0]
        problems = conn.execute(
            "SELECT COUNT(*) FROM alarm_state WHERE last_status IN ('PROBLEM','ERROR')"
        ).fetchone()[0]
        last_ts_row = conn.execute(
            "SELECT MAX(last_change_ts) FROM alarm_state"
        ).fetchone()[0]
    finally:
        conn.close()

    from datetime import datetime, timezone
    updated = (
        datetime.fromtimestamp(last_ts_row, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if last_ts_row else ""
    )

    return {
        "version": 1,
        "updated_at_utc": updated,
        "rules_evaluated_total": total,
        "notifications_sent_total": 0,
        "notifications_suppressed_total": 0,
        "evaluation_count_total": total,
        "evaluation_latency_ms_last": 0,
        "evaluation_latency_ms_sum": 0,
        "evaluation_latency_ms_avg": 0,
        "last_exit_code": 1 if problems > 0 else 0,
    }


@router.get("/metrics")
async def get_alarm_metrics() -> Dict[str, Any]:
    return _get_alarm_metrics()


def _clear_outbox() -> Dict[str, Any]:
    """Outbox klasörünü temizle (eski compat)."""
    outbox = ALARMFW_STATE / "outbox"
    if not outbox.exists():
        return {"deleted": 0}
    files = list(outbox.glob("*.json"))
    for f in files:
        f.unlink()
    return {"deleted": len(files)}


@router.delete("/outbox")
async def clear_outbox() -> Dict[str, Any]:
    return _clear_outbox()
