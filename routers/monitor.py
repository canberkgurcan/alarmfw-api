from fastapi import APIRouter, Query
from typing import Any, Dict, List, Optional, Set, Tuple
import json
import os
import sqlite3
import requests
import yaml
from pathlib import Path
from config import ALARMFW_CONFIG, ALARMFW_STATE

router = APIRouter(prefix="/api/monitor", tags=["monitor"])

OCP_CONF_DIR = ALARMFW_CONFIG / "generated"
STATE_DB     = ALARMFW_STATE / "alarmfw.sqlite"


def _config_ns_clusters() -> List[Tuple[str, str]]:
    """
    generated/ altındaki yaml'lardan (namespace, cluster) çiftlerini döner.
    ocp_pod_health ve ocp_cluster_snapshot tiplerini destekler.
    """
    pairs: List[Tuple[str, str]] = []
    if not OCP_CONF_DIR.exists():
        return pairs
    for f in OCP_CONF_DIR.glob("*.yaml"):
        try:
            data = yaml.safe_load(f.read_text()) or {}
        except Exception:
            continue
        for check in data.get("checks", []) or []:
            if not check.get("enabled", True):
                continue
            ctype  = check.get("type", "")
            params = check.get("params", {}) or {}
            cl     = params.get("cluster", "")
            if not cl:
                continue
            if ctype == "ocp_pod_health":
                ns = params.get("namespace", "")
                if ns:
                    pairs.append((ns, cl))
            elif ctype == "ocp_cluster_snapshot":
                for ns_entry in params.get("namespaces", []) or []:
                    ns = ns_entry.get("namespace", "")
                    if ns:
                        pairs.append((ns, cl))
    return pairs


def _read_sqlite_alarms() -> List[Dict[str, Any]]:
    """SQLite alarm_state tablosundan son payload'ları okur."""
    if not STATE_DB.exists():
        return []
    try:
        conn = sqlite3.connect(str(STATE_DB), timeout=5)
        conn.execute("PRAGMA journal_mode=WAL;")
        cur = conn.execute(
            "SELECT last_status, payload_json FROM alarm_state WHERE payload_json IS NOT NULL"
        )
        results = []
        for status, pjson in cur.fetchall():
            try:
                data = json.loads(pjson)
                ev   = data.get("evidence") or {}
                results.append({
                    "namespace":     ev.get("namespace", ""),
                    "cluster":       ev.get("cluster", ""),
                    "status":        data.get("status", status),
                    "timestamp_utc": data.get("timestamp_utc", ""),
                    "pods":          ev.get("pods", []),
                    "alarm_name":    data.get("alarm_name", ""),
                    "severity":      data.get("severity", ""),
                })
            except Exception:
                continue
        conn.close()
        return results
    except Exception:
        return []


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.get("/pods")
def get_pods(
    cluster:   Optional[str] = Query(None),
    namespace: Optional[str] = Query(None),
) -> List[Dict[str, Any]]:
    """
    ?cluster=X   → o cluster'daki tüm namespace'lerin son snapshot'ı
    ?namespace=X → tüm cluster'lardaki o namespace'in snapshot'ı
    İkisi birden verilirse cluster + namespace filtresi uygulanır.
    Sadece PROBLEM veya ERROR statüsleri döner.
    """
    alarms = _read_sqlite_alarms()
    results = []

    for item in alarms:
        ns = item["namespace"]
        cl = item["cluster"]

        if cluster and namespace:
            if cl != cluster or ns != namespace:
                continue
        elif cluster:
            if cl != cluster:
                continue
        elif namespace:
            if ns != namespace:
                continue

        results.append(item)

    # Sadece aktif problem/error
    results = [r for r in results if r.get("status") in ("PROBLEM", "ERROR")]

    results.sort(key=lambda r: (r["namespace"], r["cluster"]))
    return results


@router.get("/namespaces")
def list_monitor_namespaces() -> List[str]:
    """Config + SQLite'tan tüm namespace'leri döner."""
    from_config: Set[str] = {ns for ns, _ in _config_ns_clusters()}
    from_db: Set[str] = {r["namespace"] for r in _read_sqlite_alarms() if r["namespace"]}
    return sorted(from_config | from_db)


@router.get("/clusters")
def list_monitor_clusters() -> List[str]:
    """Config + SQLite'tan tüm cluster'ları döner."""
    from_config: Set[str] = {cl for _, cl in _config_ns_clusters()}
    from_db: Set[str] = {r["cluster"] for r in _read_sqlite_alarms() if r["cluster"]}
    return sorted(from_config | from_db)


@router.post("/promql")
def run_promql(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prometheus'a PromQL sorgusu gönderir.
    PROMETHEUS_URL env tanımlı değilse boş sonuç döner.
    body: { query: str, time?: str }
    """
    prom_url = os.getenv("PROMETHEUS_URL", "").rstrip("/")
    if not prom_url:
        return {"ok": False, "error": "PROMETHEUS_URL tanımlanmamış", "result": []}

    query = body.get("query", "").strip()
    if not query:
        return {"ok": False, "error": "Sorgu boş", "result": []}

    params: Dict[str, str] = {"query": query}
    if body.get("time"):
        params["time"] = body["time"]

    try:
        r = requests.get(
            f"{prom_url}/api/v1/query",
            params=params,
            timeout=15,
            verify=False,
        )
        r.raise_for_status()
        data = r.json()
        return {
            "ok":     True,
            "result": data.get("data", {}).get("result", []),
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "result": []}
