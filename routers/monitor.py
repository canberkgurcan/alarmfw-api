from fastapi import APIRouter, Query
from typing import Any, Dict, List, Optional, Set, Tuple
import json
import os
import re
import requests
import yaml
from pathlib import Path
from config import ALARMFW_CONFIG, ALARMFW_STATE

router = APIRouter(prefix="/api/monitor", tags=["monitor"])

OUTBOX_DIR   = ALARMFW_STATE / "outbox"
CONF_D       = Path(ALARMFW_CONFIG).parent / "legacy/podhealthalarm/conf.d"
OCP_CONF_DIR = ALARMFW_CONFIG / "generated"


def _config_ns_clusters() -> List[Tuple[str, str]]:
    """
    generated/ altındaki tüm yaml'lardan (ocp_pod_health tipi) (namespace, cluster) çiftlerini döner.
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
            if check.get("type") != "ocp_pod_health":
                continue
            params = check.get("params", {}) or {}
            ns = params.get("namespace", "")
            cl = params.get("cluster", "")
            if ns and cl:
                pairs.append((ns, cl))
    return pairs

# alarm_name: ocp_pod_health__webstore__esy2-digital
_NAME_RE = re.compile(r"ocp_pod_health__([^_].+)__([^_].+)$")


def _parse_alarm_name(alarm_name: str):
    """ocp_pod_health__webstore__esy2-digital → (webstore, esy2-digital)"""
    m = _NAME_RE.match(alarm_name)
    return (m.group(1), m.group(2)) if m else (None, None)


def _ns_clusters(namespace: str) -> List[str]:
    """conf.d'den namespace'in bağlı olduğu cluster listesini döner."""
    f = CONF_D / f"{namespace}.conf"
    if not f.exists():
        return []
    for line in f.read_text().splitlines():
        line = line.strip()
        if line.startswith("CLUSTERS="):
            val = line.partition("=")[2].strip().strip('"').strip("'")
            return [c.strip() for c in val.split(",") if c.strip()]
    return []


def _latest_outbox_files() -> Dict[str, Path]:
    """
    Her (namespace, cluster) çifti için en son outbox dosyasını döner.
    key: "namespace__cluster"
    """
    if not OUTBOX_DIR.exists():
        return {}
    latest: Dict[str, Path] = {}
    for f in OUTBOX_DIR.glob("*.json"):
        # alarmfw_{ts}_{alarm_name}_{status}_{dedup}.json
        parts = f.stem.split("_", 2)  # ["alarmfw", ts, rest]
        if len(parts) < 3:
            continue
        rest = parts[2]  # "ocp_pod_health__webstore__esy2-digital_PROBLEM_abc"
        # alarm_name ends before _PROBLEM/_OK/_ERROR
        m = re.match(r"(ocp_pod_health__\S+?)_(PROBLEM|OK|ERROR)_", rest)
        if not m:
            continue
        alarm_name = m.group(1)
        ns, cl = _parse_alarm_name(alarm_name)
        if not ns:
            continue
        key = f"{ns}__{cl}"
        # ts bölümünden sırala: en büyük ts = en yeni
        if key not in latest or f.stat().st_mtime > latest[key].stat().st_mtime:
            latest[key] = f
    return latest


def _read_pods(path: Path) -> Dict[str, Any]:
    """Outbox JSON'dan namespace, cluster, timestamp ve pod listesini döner."""
    try:
        data = json.loads(path.read_text())
    except Exception:
        return {}
    ev = data.get("evidence") or {}
    return {
        "namespace":     ev.get("namespace", ""),
        "cluster":       ev.get("cluster", ""),
        "status":        data.get("status", ""),
        "timestamp_utc": data.get("timestamp_utc", ""),
        "pods":          ev.get("pods", []),
    }


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.get("/pods")
def get_pods(
    cluster:   Optional[str] = Query(None),
    namespace: Optional[str] = Query(None),
) -> List[Dict[str, Any]]:
    """
    ?cluster=X   → o cluster'daki tüm namespace'lerin son snapshot'ı
    ?namespace=X → conf.d'den alınan tüm cluster'lardaki o namespace'in snapshot'ı
    İkisi birden verilirse cluster + namespace filtresi uygulanır.
    """
    latest = _latest_outbox_files()
    results = []

    for key, path in latest.items():
        data = _read_pods(path)
        if not data:
            continue
        ns = data["namespace"]
        cl = data["cluster"]

        if cluster and namespace:
            if cl != cluster or ns != namespace:
                continue
        elif cluster:
            if cl != cluster:
                continue
        elif namespace:
            # conf.d'den bu namespace'in cluster listesini kontrol et
            allowed = _ns_clusters(namespace)
            if ns != namespace or (allowed and cl not in allowed):
                continue

        results.append(data)

    # namespace+cluster sırala
    results.sort(key=lambda r: (r["namespace"], r["cluster"]))
    return results


@router.get("/namespaces")
def list_monitor_namespaces() -> List[str]:
    """Config + outbox'tan tüm namespace'leri döner."""
    from_config: Set[str] = {ns for ns, _ in _config_ns_clusters()}
    latest = _latest_outbox_files()
    from_outbox: Set[str] = {_read_pods(p)["namespace"] for p in latest.values() if _read_pods(p)}
    return sorted(from_config | from_outbox)


@router.get("/clusters")
def list_monitor_clusters() -> List[str]:
    """Config + outbox'tan tüm cluster'ları döner."""
    from_config: Set[str] = {cl for _, cl in _config_ns_clusters()}
    latest = _latest_outbox_files()
    from_outbox: Set[str] = {_read_pods(p)["cluster"] for p in latest.values() if _read_pods(p)}
    return sorted(from_config | from_outbox)


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
