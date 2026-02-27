from fastapi import APIRouter, HTTPException
from typing import Any, Dict, List
import yaml
from pathlib import Path
from config import ALARMFW_CONFIG, ALARMFW_ENV

router = APIRouter(prefix="/api/config", tags=["config"])

CONF_D    = Path(ALARMFW_CONFIG).parent / "legacy/podhealthalarm/conf.d"
CLUSTER_D = Path(ALARMFW_CONFIG).parent / "legacy/podhealthalarm/clusters.d"
GENERATED = ALARMFW_CONFIG / "generated/ocp_pod_health.yaml"


# ── helpers ───────────────────────────────────────────

def _read_conf(path: Path) -> Dict[str, str]:
    d: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def _write_conf(path: Path, data: Dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'{k}="{v}"' for k, v in data.items() if v is not None]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_env_file() -> Dict[str, str]:
    if not ALARMFW_ENV.exists():
        return {}
    result: Dict[str, str] = {}
    for line in ALARMFW_ENV.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        result[k.strip()] = v.strip()
    return result


def _write_env_file(data: Dict[str, str]) -> None:
    lines = [f"{k}={v}" for k, v in data.items()]
    ALARMFW_ENV.write_text("\n".join(lines) + "\n")


def _resolve(value: str, env: Dict[str, str]) -> str:
    """${VAR_NAME} referansını gerçek değere çevirir."""
    if value.startswith("${") and value.endswith("}"):
        return env.get(value[2:-1], value)
    return value


def _cluster_env_key(name: str) -> str:
    """esy2-digital  →  OCP_API_ESY2_DIGITAL"""
    return "OCP_API_" + name.upper().replace("-", "_")


def _is_true(v: str | None) -> bool:
    return (v or "").strip().lower() == "true"


def _bool_str(v: bool) -> str:
    return "true" if v else "false"


def _generate_yaml() -> int:
    """Regenerate config/generated/ocp_pod_health.yaml from conf.d + clusters.d"""
    checks = []
    env = _read_env_file()

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
            cl_conf = CLUSTER_D / f"{cl}.conf"
            if not cl_conf.exists():
                continue
            cl_cfg = _read_conf(cl_conf)
            ocp_api   = _resolve(cl_cfg.get("OCP_API", ""), env)
            ocp_token_file = f"/secrets/{cl}.token"
            insecure  = cl_cfg.get("OCP_INSECURE", "true")

            if not ocp_api:
                continue

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


@router.put("/namespaces/{name}")
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


@router.delete("/namespaces/{name}")
def delete_namespace(name: str) -> Dict[str, Any]:
    f = CONF_D / f"{name}.conf"
    if not f.exists():
        raise HTTPException(404, f"Namespace '{name}' not found")
    f.unlink()
    count = _generate_yaml()
    return {"ok": True, "name": name, "generated_checks": count}


# ── Clusters ──────────────────────────────────────────

@router.get("/clusters")
def list_clusters() -> List[Dict[str, Any]]:
    if not CLUSTER_D.exists():
        return []
    env = _read_env_file()
    result = []
    for f in sorted(CLUSTER_D.glob("*.conf")):
        raw = _read_conf(f)
        result.append({
            "name":     f.stem,
            "ocp_api":  _resolve(raw.get("OCP_API", ""), env),
            "insecure": _is_true(raw.get("OCP_INSECURE", "true")),
            "has_token_file": (Path(ALARMFW_CONFIG).parent.parent /
                               "alarmfw-secrets" / f"{f.stem}.token").exists(),
        })
    return result


@router.get("/clusters/{name}")
def get_cluster(name: str) -> Dict[str, Any]:
    f = CLUSTER_D / f"{name}.conf"
    if not f.exists():
        raise HTTPException(404, f"Cluster '{name}' not found")
    env = _read_env_file()
    raw = _read_conf(f)
    return {
        "name":     name,
        "ocp_api":  _resolve(raw.get("OCP_API", ""), env),
        "insecure": _is_true(raw.get("OCP_INSECURE", "true")),
    }


@router.put("/clusters/{name}")
def upsert_cluster(name: str, body: Dict[str, Any]) -> Dict[str, Any]:
    f = CLUSTER_D / f"{name}.conf"
    ocp_api = str(body.get("ocp_api", ""))
    data = {
        "OCP_API":      ocp_api,
        "OCP_INSECURE": _bool_str(body.get("insecure", True)),
    }
    _write_conf(f, data)
    # Gerçek URL ise .env'e de yaz
    if ocp_api and not (ocp_api.startswith("${") and ocp_api.endswith("}")):
        env = _read_env_file()
        env[_cluster_env_key(name)] = ocp_api
        _write_env_file(env)
    return {"ok": True, "name": name}


@router.delete("/clusters/{name}")
def delete_cluster(name: str) -> Dict[str, Any]:
    f = CLUSTER_D / f"{name}.conf"
    if not f.exists():
        raise HTTPException(404, f"Cluster '{name}' not found")
    f.unlink()
    count = _generate_yaml()
    return {"ok": True, "name": name, "generated_checks": count}


@router.post("/generate")
def generate() -> Dict[str, Any]:
    count = _generate_yaml()
    return {"ok": True, "generated_checks": count}
