from fastapi import APIRouter, HTTPException
from typing import Any, Dict
import subprocess
import threading
import time
import json
import socket
from config import COMPOSE_RUN_CONFIG

router = APIRouter(prefix="/api/run", tags=["runner"])

# Son run sonucunu bellekte tut
_last_run: Dict[str, Any] = {}
_run_lock = threading.Lock()


def _get_mount_args() -> list:
    """
    Current container'ın /config, /secrets, /state mount'larını docker inspect ile alır.
    Döner: docker run için ["-v", "src:dst:mode", ...] listesi
    """
    hostname = socket.gethostname()
    try:
        result = subprocess.run(
            ["docker", "inspect", hostname],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout)
        if not data:
            return []
        args = []
        for m in data[0].get("Mounts", []):
            dst = m.get("Destination", "")
            if dst not in ("/config", "/secrets", "/state"):
                continue
            if m["Type"] == "volume":
                src = m["Name"]
            else:
                src = m.get("Source", "")
            mode = "ro" if not m.get("RW", True) else "rw"
            if src:
                args += ["-v", f"{src}:{dst}:{mode}"]
        return args
    except Exception:
        return []


def _do_run(config: str) -> None:
    global _last_run
    started = time.time()
    try:
        vol_args = _get_mount_args()
        if not vol_args:
            _last_run = {
                "status": "error", "exit_code": -1, "stdout": "",
                "stderr": "Container mount bilgisi alınamadı (docker inspect başarısız)",
                "config": config, "started_at": started,
            }
            return

        cmd = ["docker", "run", "--rm"] + vol_args + [
            "alarmfw:latest", "run", "--config", config
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        _last_run = {
            "status": "done",
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-8000:],
            "stderr": proc.stderr[-2000:],
            "duration_sec": round(time.time() - started, 1),
            "config": config,
            "started_at": started,
        }
    except subprocess.TimeoutExpired:
        _last_run = {"status": "timeout", "exit_code": -1, "stdout": "", "stderr": "Timeout", "config": config}
    except Exception as e:
        _last_run = {"status": "error", "exit_code": -1, "stdout": "", "stderr": str(e), "config": config}


@router.post("")
def trigger_run(body: Dict[str, Any] = {}) -> Dict[str, Any]:
    global _last_run
    with _run_lock:
        if _last_run.get("status") == "running":
            raise HTTPException(409, "A run is already in progress")
        config = body.get("config", COMPOSE_RUN_CONFIG)
        _last_run = {"status": "running", "config": config}

    t = threading.Thread(target=_do_run, args=(config,), daemon=True)
    t.start()
    return {"ok": True, "message": "Run started", "config": config}


@router.get("/last")
def get_last_run() -> Dict[str, Any]:
    return _last_run or {"status": "never_run"}
