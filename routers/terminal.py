import os
import subprocess
import yaml
from fastapi import APIRouter
from pathlib import Path
from typing import Any, Dict, List

router = APIRouter(prefix="/api/terminal", tags=["terminal"])

# Kubeconfig container içinde kalıcı olarak bu path'te tutulur
_KUBECONFIG  = "/root/.kube/config"
_ENV         = {**os.environ, "HOME": "/root", "KUBECONFIG": _KUBECONFIG}

ALARMFW_CONFIG  = Path(os.getenv("ALARMFW_CONFIG",  "/home/cnbrkgrcn/projects/alarmfw/config"))
ALARMFW_SECRETS = Path(os.getenv("ALARMFW_SECRETS", "/home/cnbrkgrcn/alarmfw-secrets"))
OCP_CONF_DIR    = ALARMFW_CONFIG / "generated"


def _get_clusters() -> Dict[str, Dict[str, Any]]:
    clusters: Dict[str, Dict[str, Any]] = {}
    if not OCP_CONF_DIR.exists():
        return clusters
    for f in OCP_CONF_DIR.glob("*.yaml"):
        try:
            data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            for check in data.get("checks", []) or []:
                if not check.get("enabled", True):
                    continue
                if check.get("type") not in ("ocp_pod_health", "ocp_cluster_snapshot"):
                    continue
                params = check.get("params", {}) or {}
                name = params.get("cluster", "")
                if not name or name in clusters:
                    continue
                clusters[name] = {
                    "name":     name,
                    "ocp_api":  params.get("ocp_api", "").rstrip("/"),
                    "insecure": str(params.get("ocp_insecure", "false")).lower() == "true",
                }
        except Exception:
            pass
    return clusters


def _run(cmd: str, timeout: int = 30) -> Dict[str, Any]:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, env=_ENV)
        return {"ok": r.returncode == 0, "stdout": r.stdout, "stderr": r.stderr, "exit_code": r.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"Timeout ({timeout}s)", "exit_code": -1}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e), "exit_code": -1}


# ── Exec ──────────────────────────────────────────────────────────────────────

@router.post("/exec")
def exec_command(body: Dict[str, Any]) -> Dict[str, Any]:
    """Verilen shell komutunu çalıştırır, stdout/stderr döner."""
    cmd = body.get("command", "").strip()
    if not cmd:
        return {"ok": False, "stdout": "", "stderr": "Komut boş.", "exit_code": 1}
    return _run(cmd)


# ── Whoami ────────────────────────────────────────────────────────────────────

@router.get("/whoami")
def oc_whoami() -> Dict[str, Any]:
    """Aktif oc oturumunu döner."""
    try:
        r = subprocess.run(["oc", "whoami"], capture_output=True, text=True, timeout=10, env=_ENV)
        user = r.stdout.strip()
        return {"logged_in": bool(user and r.returncode == 0), "user": user or None}
    except Exception:
        return {"logged_in": False, "user": None}


# ── Clusters ──────────────────────────────────────────────────────────────────

@router.get("/clusters")
def list_clusters() -> List[Dict[str, Any]]:
    """Login için mevcut cluster listesi."""
    return [
        {"name": c["name"], "ocp_api": c["ocp_api"]}
        for c in _get_clusters().values()
        if c.get("ocp_api")
    ]


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login")
def oc_login(body: Dict[str, Any]) -> Dict[str, Any]:
    """Cluster adına göre token dosyasını okuyup oc login çalıştırır."""
    cluster_name = body.get("cluster", "").strip()
    if not cluster_name:
        return {"ok": False, "stdout": "", "stderr": "Cluster adı gerekli.", "exit_code": 1}

    clusters = _get_clusters()
    if cluster_name not in clusters:
        return {"ok": False, "stdout": "", "stderr": f"Cluster '{cluster_name}' bulunamadı.", "exit_code": 1}

    c = clusters[cluster_name]
    ocp_api = c.get("ocp_api", "")
    if not ocp_api:
        return {"ok": False, "stdout": "", "stderr": f"Cluster '{cluster_name}' için OCP API URL tanımlanmamış.", "exit_code": 1}

    token_path = ALARMFW_SECRETS / f"{cluster_name}.token"
    if not token_path.exists():
        return {"ok": False, "stdout": "", "stderr": f"Token dosyası bulunamadı: {token_path}", "exit_code": 1}

    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        return {"ok": False, "stdout": "", "stderr": "Token dosyası boş.", "exit_code": 1}

    cmd = f"oc login {ocp_api} --token={token} --insecure-skip-tls-verify=true"
    return _run(cmd)
