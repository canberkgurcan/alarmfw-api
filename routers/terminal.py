import os
import shlex
import subprocess
from fastapi import APIRouter, Depends
from pathlib import Path
from typing import Any, Dict, List
import yaml
from async_utils import run_blocking
from auth import require_operator

router = APIRouter(prefix="/api/terminal", tags=["terminal"])

# Kubeconfig container içinde kalıcı olarak bu path'te tutulur
_KUBECONFIG  = "/root/.kube/config"
_ENV         = {**os.environ, "HOME": "/root", "KUBECONFIG": _KUBECONFIG}

ALARMFW_CONFIG  = Path(os.getenv("ALARMFW_CONFIG",  "/home/cnbrkgrcn/projects/alarmfw/config"))
ALARMFW_SECRETS = Path(os.getenv("ALARMFW_SECRETS", "/home/cnbrkgrcn/alarmfw-secrets"))
ALLOWED_COMMANDS = {"oc"}


def _get_clusters() -> Dict[str, Dict[str, Any]]:
    """Cluster listesini observe.yaml'dan okur (tek kaynak)."""
    p = ALARMFW_CONFIG / "observe.yaml"
    if not p.exists():
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    clusters: Dict[str, Dict[str, Any]] = {}
    for c in data.get("clusters", []):
        if not isinstance(c, dict) or not c.get("name") or not c.get("ocp_api"):
            continue
        name = c["name"]
        clusters[name] = {
            "name":     name,
            "ocp_api":  c["ocp_api"].rstrip("/"),
            "insecure": bool(c.get("insecure", True)),
        }
    return clusters


def _run(args: list, timeout: int = 30) -> Dict[str, Any]:
    try:
        r = subprocess.run(args, shell=False, capture_output=True, text=True, timeout=timeout, env=_ENV)
        return {"ok": r.returncode == 0, "stdout": r.stdout, "stderr": r.stderr, "exit_code": r.returncode}
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"Timeout ({timeout}s)", "exit_code": -1}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e), "exit_code": -1}


# ── Exec ──────────────────────────────────────────────────────────────────────

@router.post("/exec", dependencies=[Depends(require_operator)])
async def exec_command(body: Dict[str, Any]) -> Dict[str, Any]:
    """Verilen komutu çalıştırır, stdout/stderr döner. Sadece izin verilen komutlar çalışır."""
    cmd_str = body.get("command", "").strip()
    if not cmd_str:
        return {"ok": False, "stdout": "", "stderr": "Komut boş.", "exit_code": 1}
    try:
        args = shlex.split(cmd_str)
    except ValueError as e:
        return {"ok": False, "stdout": "", "stderr": f"Geçersiz komut: {e}", "exit_code": 1}
    if not args or args[0] not in ALLOWED_COMMANDS:
        allowed = ", ".join(sorted(ALLOWED_COMMANDS))
        return {"ok": False, "stdout": "", "stderr": f"İzin verilmeyen komut. Sadece şunlar kullanılabilir: {allowed}", "exit_code": 1}
    return await run_blocking(_run, args)


# ── Whoami ────────────────────────────────────────────────────────────────────

@router.get("/whoami")
async def oc_whoami() -> Dict[str, Any]:
    """Aktif oc oturumunu döner."""
    def _oc_whoami() -> Dict[str, Any]:
        try:
            r = subprocess.run(["oc", "whoami"], capture_output=True, text=True, timeout=10, env=_ENV)
            user = r.stdout.strip()
            return {"logged_in": bool(user and r.returncode == 0), "user": user or None}
        except Exception:
            return {"logged_in": False, "user": None}

    return await run_blocking(_oc_whoami)


# ── Clusters ──────────────────────────────────────────────────────────────────

@router.get("/clusters")
async def list_clusters() -> List[Dict[str, Any]]:
    """Login için mevcut cluster listesi."""
    return [
        {"name": c["name"], "ocp_api": c["ocp_api"]}
        for c in _get_clusters().values()
        if c.get("ocp_api")
    ]


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login", dependencies=[Depends(require_operator)])
async def oc_login(body: Dict[str, Any]) -> Dict[str, Any]:
    """Cluster adına göre token dosyasını okuyup oc login çalıştırır."""
    cluster_name = body.get("cluster", "").strip()
    if not cluster_name:
        return {"ok": False, "stdout": "", "stderr": "Cluster adı gerekli.", "exit_code": 1}

    def _oc_login() -> Dict[str, Any]:
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

        args = ["oc", "login", ocp_api, f"--token={token}"]
        if c.get("insecure"):
            args.append("--insecure-skip-tls-verify=true")
        return _run(args)

    return await run_blocking(_oc_login)
