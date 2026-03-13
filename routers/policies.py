from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from config import ALARMFW_CONFIG, ALARMFW_STATE
from auth import require_admin

router = APIRouter(prefix="/api/policies", tags=["policies"])

_DEDUP_FILE       = ALARMFW_CONFIG / "policies/dedup.yaml"
_MAINTENANCE_FILE = ALARMFW_CONFIG / "policies/maintenance.yaml"
_POLICIES_DB      = ALARMFW_STATE  / "policies.sqlite"
_ALARM_DB         = ALARMFW_STATE  / "alarmfw.sqlite"


# ── SQLite helpers ─────────────────────────────────────

def _open_policies_db() -> sqlite3.Connection:
    _POLICIES_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_POLICIES_DB), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS policy_audit (
            id           TEXT PRIMARY KEY,
            ts_utc       TEXT NOT NULL,
            actor        TEXT NOT NULL,
            client_ip    TEXT,
            policy       TEXT NOT NULL,
            action       TEXT NOT NULL,
            resource     TEXT NOT NULL,
            summary      TEXT NOT NULL,
            changes_json TEXT
        );
        CREATE TABLE IF NOT EXISTS policy_versions (
            id              TEXT PRIMARY KEY,
            policy          TEXT NOT NULL,
            created_at_utc  TEXT NOT NULL,
            source_action   TEXT NOT NULL,
            actor           TEXT NOT NULL,
            meta_json       TEXT,
            content_json    TEXT NOT NULL
        );
    """)
    return conn


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _actor_from_request(request: Request) -> str:
    return request.headers.get("X-Actor", "unknown")


# ── Dedup (legacy, kept for compat) ───────────────────

@router.get("/dedup")
def get_dedup() -> Dict[str, Any]:
    if not _DEDUP_FILE.exists():
        raise HTTPException(404, "dedup.yaml not found")
    data = yaml.safe_load(_DEDUP_FILE.read_text()) or {}
    return data.get("dedup_policy") or data


@router.put("/dedup")
def update_dedup(body: Dict[str, Any]) -> Dict[str, Any]:
    if not _DEDUP_FILE.exists():
        raise HTTPException(404, "dedup.yaml not found")
    data = yaml.safe_load(_DEDUP_FILE.read_text()) or {}
    if "dedup_policy" in data:
        data["dedup_policy"].update(body)
    else:
        data.update(body)
    _DEDUP_FILE.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False))
    return {"ok": True}


# ── Maintenance YAML helpers ───────────────────────────

def _read_maintenance() -> Dict[str, Any]:
    if not _MAINTENANCE_FILE.exists():
        return {"silences": []}
    raw = yaml.safe_load(_MAINTENANCE_FILE.read_text()) or {}
    policy = raw.get("maintenance") or raw
    if "silences" not in policy:
        policy["silences"] = []
    return policy


def _write_maintenance(policy: Dict[str, Any]) -> None:
    _MAINTENANCE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _MAINTENANCE_FILE.write_text(
        yaml.dump({"maintenance": policy}, allow_unicode=True, default_flow_style=False)
    )


def _save_audit(
    conn: sqlite3.Connection,
    *,
    actor: str,
    client_ip: Optional[str],
    policy: str,
    action: str,
    resource: str,
    summary: str,
    changes: Optional[Any] = None,
) -> str:
    entry_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO policy_audit(id,ts_utc,actor,client_ip,policy,action,resource,summary,changes_json) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (
            entry_id, _utc_now(), actor, client_ip, policy,
            action, resource, summary,
            json.dumps(changes) if changes is not None else None,
        ),
    )
    conn.commit()
    return entry_id


def _save_version(
    conn: sqlite3.Connection,
    *,
    policy: str,
    source_action: str,
    actor: str,
    content: Any,
    meta: Optional[Any] = None,
) -> str:
    ver_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO policy_versions(id,policy,created_at_utc,source_action,actor,meta_json,content_json) "
        "VALUES(?,?,?,?,?,?,?)",
        (
            ver_id, policy, _utc_now(), source_action, actor,
            json.dumps(meta) if meta is not None else None,
            json.dumps(content),
        ),
    )
    conn.commit()
    return ver_id


# ── Maintenance Policy CRUD ────────────────────────────

@router.get("/maintenance")
def get_maintenance() -> Dict[str, Any]:
    return _read_maintenance()


@router.put("/maintenance", dependencies=[Depends(require_admin)])
def update_maintenance(body: Dict[str, Any], request: Request) -> Dict[str, Any]:
    actor     = _actor_from_request(request)
    client_ip = request.client.host if request.client else None

    old = _read_maintenance()
    new_policy: Dict[str, Any] = {"silences": body.get("silences", [])}
    _write_maintenance(new_policy)

    conn = _open_policies_db()
    try:
        ver_id = _save_version(conn, policy="maintenance", source_action="put", actor=actor, content=new_policy)
        _save_audit(
            conn, actor=actor, client_ip=client_ip,
            policy="maintenance", action="update", resource="silences",
            summary=f"Updated maintenance policy ({len(new_policy['silences'])} silences)",
            changes={"old": old, "new": new_policy},
        )
    finally:
        conn.close()

    return {"ok": True, "silences": len(new_policy["silences"]), "version_id": ver_id}


@router.post("/maintenance/silences", dependencies=[Depends(require_admin)])
def create_silence(body: Dict[str, Any], request: Request) -> Dict[str, Any]:
    actor     = _actor_from_request(request)
    client_ip = request.client.host if request.client else None

    silence_id = body.get("id") or str(uuid.uuid4())
    silence = {**body, "id": silence_id}

    policy = _read_maintenance()
    policy["silences"].append(silence)
    _write_maintenance(policy)

    conn = _open_policies_db()
    try:
        ver_id = _save_version(conn, policy="maintenance", source_action="create_silence", actor=actor, content=policy)
        _save_audit(
            conn, actor=actor, client_ip=client_ip,
            policy="maintenance", action="create", resource=f"silence:{silence_id}",
            summary=f"Created silence {silence_id}",
            changes={"silence": silence},
        )
    finally:
        conn.close()

    return {"ok": True, "id": silence_id, "version_id": ver_id}


@router.delete("/maintenance/silences/{silence_id}", dependencies=[Depends(require_admin)])
def delete_silence(silence_id: str, request: Request) -> Dict[str, Any]:
    actor     = _actor_from_request(request)
    client_ip = request.client.host if request.client else None

    policy = _read_maintenance()
    before = len(policy["silences"])
    policy["silences"] = [s for s in policy["silences"] if s.get("id") != silence_id]
    if len(policy["silences"]) == before:
        raise HTTPException(404, f"Silence '{silence_id}' not found")
    _write_maintenance(policy)

    conn = _open_policies_db()
    try:
        ver_id = _save_version(conn, policy="maintenance", source_action="delete_silence", actor=actor, content=policy)
        _save_audit(
            conn, actor=actor, client_ip=client_ip,
            policy="maintenance", action="delete", resource=f"silence:{silence_id}",
            summary=f"Deleted silence {silence_id}",
        )
    finally:
        conn.close()

    return {"ok": True, "id": silence_id, "version_id": ver_id}


# ── Dry-run ────────────────────────────────────────────

def _match(expected: Any, actual: Optional[str]) -> bool:
    if expected in (None, "", "*"):
        return True
    return str(expected).strip() == (actual or "").strip()


def _parse_utc(value: Any):
    if value is None:
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@router.post("/maintenance/silences/dry-run")
def dry_run_silence(body: Dict[str, Any]) -> Dict[str, Any]:
    silence  = body.get("silence") or {}
    at_utc   = body.get("at_utc")
    now      = _parse_utc(at_utc) if at_utc else datetime.now(timezone.utc)
    evaluated_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    start = _parse_utc(silence.get("starts_at_utc"))
    end   = _parse_utc(silence.get("ends_at_utc"))
    active = bool(start and end and start <= now < end)

    matches: List[Dict[str, Any]] = []
    total_candidates = 0

    if _ALARM_DB.exists():
        conn = sqlite3.connect(str(_ALARM_DB), timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT alarm_name, payload_json FROM alarm_state WHERE payload_json IS NOT NULL"
            ).fetchall()
        finally:
            conn.close()

        total_candidates = len(rows)
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except Exception:
                continue

            alarm_name = payload.get("alarm_name", row["alarm_name"] or "")
            cluster    = payload.get("cluster", "")
            namespace  = payload.get("namespace", "")

            if not (
                _match(silence.get("alarm_name"), alarm_name)
                and _match(silence.get("cluster"),    cluster)
                and _match(silence.get("namespace"),  namespace)
            ):
                continue

            matches.append({
                "alarm_name":  alarm_name or "",
                "cluster":     cluster or "",
                "namespace":   namespace or "",
                "check_name":  alarm_name or "",
                "check_type":  payload.get("tags", {}).get("type", ""),
                "source_file": "",
            })

    return {
        "ok": True,
        "active": active,
        "evaluated_at_utc": evaluated_at,
        "total_candidates": total_candidates,
        "matched": len(matches),
        "matches": matches,
    }


# ── Audit ──────────────────────────────────────────────

@router.get("/audit")
def get_audit(
    policy: str = "maintenance",
    limit: int = 50,
) -> Dict[str, Any]:
    conn = _open_policies_db()
    try:
        rows = conn.execute(
            "SELECT id,ts_utc,actor,client_ip,policy,action,resource,summary,changes_json "
            "FROM policy_audit WHERE policy=? ORDER BY ts_utc DESC LIMIT ?",
            (policy, limit),
        ).fetchall()
    finally:
        conn.close()

    entries = []
    for r in rows:
        entry = dict(r)
        raw_changes = entry.pop("changes_json", None)
        if raw_changes:
            try:
                entry["changes"] = json.loads(raw_changes)
            except Exception:
                pass
        entries.append(entry)

    return {"entries": entries, "count": len(entries)}


# ── Versions ───────────────────────────────────────────

@router.get("/versions")
def get_versions(
    policy: str = "maintenance",
    limit: int = 25,
) -> Dict[str, Any]:
    conn = _open_policies_db()
    try:
        rows = conn.execute(
            "SELECT id,policy,created_at_utc,source_action,actor,meta_json "
            "FROM policy_versions WHERE policy=? ORDER BY created_at_utc DESC LIMIT ?",
            (policy, limit),
        ).fetchall()
    finally:
        conn.close()

    entries = []
    for r in rows:
        entry = dict(r)
        raw_meta = entry.pop("meta_json", None)
        if raw_meta:
            try:
                entry["meta"] = json.loads(raw_meta)
            except Exception:
                pass
        entries.append(entry)

    return {"policy": policy, "entries": entries, "count": len(entries)}


# ── Rollback ───────────────────────────────────────────

@router.post("/rollback", dependencies=[Depends(require_admin)])
def rollback_version(body: Dict[str, Any], request: Request) -> Dict[str, Any]:
    policy     = body.get("policy", "maintenance")
    version_id = body.get("version_id", "")
    actor      = _actor_from_request(request)
    client_ip  = request.client.host if request.client else None

    if not version_id:
        raise HTTPException(400, "version_id required")

    conn = _open_policies_db()
    try:
        row = conn.execute(
            "SELECT content_json, created_at_utc FROM policy_versions WHERE id=? AND policy=?",
            (version_id, policy),
        ).fetchone()
        if not row:
            raise HTTPException(404, f"Version '{version_id}' not found for policy '{policy}'")

        content          = json.loads(row["content_json"])
        rolled_back_from = row["created_at_utc"]

        if policy == "maintenance":
            _write_maintenance(content)

        new_ver_id = _save_version(
            conn, policy=policy, source_action="rollback", actor=actor,
            content=content, meta={"rolled_back_to_version": version_id},
        )
        _save_audit(
            conn, actor=actor, client_ip=client_ip,
            policy=policy, action="rollback", resource=f"version:{version_id}",
            summary=f"Rolled back to version {version_id} (originally from {rolled_back_from})",
        )
    finally:
        conn.close()

    return {
        "ok": True,
        "policy": policy,
        "rolled_back_from": rolled_back_from,
        "version_id": new_ver_id,
    }
