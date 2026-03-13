from fastapi import APIRouter, Depends, HTTPException
from typing import Any, Dict, List
import yaml
from pathlib import Path
from config import ALARMFW_CONFIG, ALARMFW_SECRETS
from auth import require_admin
from routers._conf import read_conf as _read_conf, write_conf as _write_conf, is_true as _is_true, bool_str as _bool_str

router = APIRouter(prefix="/api/config", tags=["config"])

CONF_D    = Path(ALARMFW_CONFIG).parent / "legacy/podhealthalarm/conf.d"
GENERATED = ALARMFW_CONFIG / "generated/ocp_pod_health.yaml"


def _generate_yaml() -> int:
    """Regenerate config/generated/ocp_pod_health.yaml from conf.d + observe.yaml clusters"""
    checks = []

    # Cluster bilgisini observe.yaml'dan al (isim → dict)
    obs_data = _read_observe_yaml()
    obs_clusters = {
        c["name"]: c
        for c in obs_data.get("clusters", [])
        if isinstance(c, dict) and c.get("name")
    }

    for ns_conf in sorted(CONF_D.glob("*.conf")):
        ns = ns_conf.stem
        ns_cfg = _read_conf(ns_conf)

        if not _is_true(ns_cfg.get("NAMESPACE_ENABLED")):
            continue

        clusters = [c.strip() for c in (ns_cfg.get("CLUSTERS", "")).split(",") if c.strip()]
        if not clusters:
            continue

        node       = ns_cfg.get("NODE", "OCP")
        department = ns_cfg.get("DEPARTMENT", "UNKNOWN")
        severity   = ns_cfg.get("SEVERITY", "5")
        alertgroup = ns_cfg.get("ALERTGROUP", f"{ns}AlertGroup")
        alertkey   = ns_cfg.get("POD_HEALTH_ALERTKEY", "OCP_POD_HEALTH")

        zbx  = _is_true(ns_cfg.get("ZABBIX_ENABLED"))
        mail = _is_true(ns_cfg.get("MAIL_ENABLED"))

        if zbx and mail:
            primary, fallback = ["zabbix"], ["dev_smtp", "smtp", "dev_outbox"]
        elif zbx:
            primary, fallback = ["zabbix"], ["dev_smtp", "dev_outbox"]
        elif mail:
            primary, fallback = ["smtp"], ["dev_smtp", "dev_outbox"]
        else:
            primary, fallback = ["dev_outbox"], []

        for cl in clusters:
            cl_data = obs_clusters.get(cl)
            if not cl_data:
                continue
            ocp_api = cl_data.get("ocp_api", "")
            if not ocp_api:
                continue
            ocp_token_file = f"/secrets/{cl}.token"
            insecure = "true" if cl_data.get("insecure", True) else "false"

            checks.append({
                "name": f"ocp_pod_health__{ns}__{cl}",
                "type": "ocp_pod_health",
                "enabled": True,
                "params": {
                    "namespace": ns,
                    "cluster": cl,
                    "ocp_api": ocp_api,
                    "ocp_token_file": ocp_token_file,
                    "ocp_insecure": insecure,
                    "timeout_sec": "30",
                    "node": node,
                    "department": department,
                    "severity": severity,
                    "alertgroup": alertgroup,
                    "alertkey": alertkey,
                },
                "notify": {"primary": primary, "fallback": fallback},
            })

    GENERATED.parent.mkdir(parents=True, exist_ok=True)
    GENERATED.write_text(
        yaml.dump({"checks": checks}, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    return len(checks)


# ── Namespaces ────────────────────────────────────────

@router.get("/namespaces")
def list_namespaces() -> List[Dict[str, Any]]:
    if not CONF_D.exists():
        return []
    result = []
    for f in sorted(CONF_D.glob("*.conf")):
        raw = _read_conf(f)
        result.append({
            "name":              f.stem,
            "namespace_enabled": _is_true(raw.get("NAMESPACE_ENABLED")),
            "clusters":          [c.strip() for c in raw.get("CLUSTERS", "").split(",") if c.strip()],
            "zabbix_enabled":    _is_true(raw.get("ZABBIX_ENABLED")),
            "mail_enabled":      _is_true(raw.get("MAIL_ENABLED")),
            "severity":          raw.get("SEVERITY", "5"),
            "node":              raw.get("NODE", ""),
            "department":        raw.get("DEPARTMENT", ""),
            "alertkey":          raw.get("POD_HEALTH_ALERTKEY", "OCP_POD_HEALTH"),
            "alertgroup":        raw.get("ALERTGROUP", ""),
            "mail_to":           raw.get("MAIL_TO", ""),
            "mail_cc":           raw.get("MAIL_CC", ""),
        })
    return result


@router.get("/namespaces/{name}")
def get_namespace(name: str) -> Dict[str, Any]:
    f = CONF_D / f"{name}.conf"
    if not f.exists():
        raise HTTPException(404, f"Namespace '{name}' not found")
    raw = _read_conf(f)
    return {
        "name":              name,
        "namespace_enabled": _is_true(raw.get("NAMESPACE_ENABLED")),
        "clusters":          [c.strip() for c in raw.get("CLUSTERS", "").split(",") if c.strip()],
        "zabbix_enabled":    _is_true(raw.get("ZABBIX_ENABLED")),
        "mail_enabled":      _is_true(raw.get("MAIL_ENABLED")),
        "severity":          raw.get("SEVERITY", "5"),
        "node":              raw.get("NODE", ""),
        "department":        raw.get("DEPARTMENT", ""),
        "alertkey":          raw.get("POD_HEALTH_ALERTKEY", "OCP_POD_HEALTH"),
        "alertgroup":        raw.get("ALERTGROUP", ""),
        "mail_to":           raw.get("MAIL_TO", ""),
        "mail_cc":           raw.get("MAIL_CC", ""),
    }


@router.put("/namespaces/{name}", dependencies=[Depends(require_admin)])
def upsert_namespace(name: str, body: Dict[str, Any]) -> Dict[str, Any]:
    f = CONF_D / f"{name}.conf"
    clusters = body.get("clusters", [])
    if isinstance(clusters, list):
        clusters_str = ",".join(clusters)
    else:
        clusters_str = str(clusters)

    data = {
        "CLUSTERS":            clusters_str,
        "NAMESPACE_ENABLED":   _bool_str(body.get("namespace_enabled", True)),
        "POD_HEALTH_ENABLED":  "true",
        "ZABBIX_ENABLED":      _bool_str(body.get("zabbix_enabled", False)),
        "MAIL_ENABLED":        _bool_str(body.get("mail_enabled", False)),
        "SEVERITY":            str(body.get("severity", "5")),
        "NODE":                str(body.get("node", "OCP")),
        "DEPARTMENT":          str(body.get("department", "")),
        "POD_HEALTH_ALERTKEY": str(body.get("alertkey", "OCP_POD_HEALTH")),
        "ALERTGROUP":          str(body.get("alertgroup", f"{name}AlertGroup")),
        "MAIL_TO":             str(body.get("mail_to", "")),
        "MAIL_CC":             str(body.get("mail_cc", "")),
    }
    _write_conf(f, data)
    count = _generate_yaml()
    return {"ok": True, "name": name, "generated_checks": count}


@router.delete("/namespaces/{name}", dependencies=[Depends(require_admin)])
def delete_namespace(name: str) -> Dict[str, Any]:
    f = CONF_D / f"{name}.conf"
    if not f.exists():
        raise HTTPException(404, f"Namespace '{name}' not found")
    f.unlink()
    count = _generate_yaml()
    return {"ok": True, "name": name, "generated_checks": count}


# ── Clusters ──────────────────────────────────────────
# Tek kaynak: observe.yaml (Secrets sayfasında eklenen cluster'lar burada görünür)

@router.get("/clusters")
def list_clusters() -> List[Dict[str, Any]]:
    data = _read_observe_yaml()
    result = []
    for c in data.get("clusters", []):
        if not isinstance(c, dict) or not c.get("name"):
            continue
        name = c["name"]
        result.append({
            "name":           name,
            "ocp_api":        c.get("ocp_api", ""),
            "insecure":       bool(c.get("insecure", True)),
            "has_token_file": (ALARMFW_SECRETS / f"{name}.token").exists(),
        })
    return result


@router.get("/clusters/{name}")
def get_cluster(name: str) -> Dict[str, Any]:
    data = _read_observe_yaml()
    for c in data.get("clusters", []):
        if isinstance(c, dict) and c.get("name") == name:
            return {
                "name":     name,
                "ocp_api":  c.get("ocp_api", ""),
                "insecure": bool(c.get("insecure", True)),
            }
    raise HTTPException(404, f"Cluster '{name}' not found")


@router.post("/generate", dependencies=[Depends(require_admin)])
def generate() -> Dict[str, Any]:
    count = _generate_yaml()
    return {"ok": True, "generated_checks": count}


# ── Observe clusters (observe.yaml) ───────────────────

def _observe_yaml_path() -> Path:
    return ALARMFW_CONFIG / "observe.yaml"

def _read_observe_yaml() -> Dict[str, Any]:
    p = _observe_yaml_path()
    if not p.exists():
        return {"clusters": []}
    with open(p) as f:
        data = yaml.safe_load(f) or {}
    raw = data.get("clusters", [])
    clusters = [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []
    data["clusters"] = clusters
    return data

def _write_observe_yaml(data: Dict[str, Any]) -> None:
    p = _observe_yaml_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)


@router.get("/observe-clusters")
def list_observe_clusters() -> List[Dict[str, Any]]:
    data = _read_observe_yaml()
    return data.get("clusters", [])


@router.put("/observe-clusters/{name}", dependencies=[Depends(require_admin)])
def upsert_observe_cluster(name: str, body: Dict[str, Any]) -> Dict[str, Any]:
    from config import ALARMFW_SECRETS
    entry: Dict[str, Any] = {
        "name":    name,
        "ocp_api": str(body.get("ocp_api", "")),
        "insecure": bool(body.get("insecure", True)),
        "prometheus_url":        str(body.get("prometheus_url", "")),
        "prometheus_token_file": str(ALARMFW_SECRETS / f"{name}-prometheus.token"),
    }
    data = _read_observe_yaml()
    clusters = data.get("clusters", [])
    found = False
    for i, c in enumerate(clusters):
        if isinstance(c, dict) and c.get("name") == name:
            clusters[i] = entry
            found = True
            break
    if not found:
        clusters.append(entry)
    data["clusters"] = clusters
    _write_observe_yaml(data)
    return {"ok": True, "name": name}


@router.delete("/observe-clusters/{name}", dependencies=[Depends(require_admin)])
def delete_observe_cluster(name: str) -> Dict[str, Any]:
    data = _read_observe_yaml()
    clusters = [c for c in data.get("clusters", []) if isinstance(c, dict) and c.get("name") != name]
    data["clusters"] = clusters
    _write_observe_yaml(data)
    return {"ok": True, "name": name}
