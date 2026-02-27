from fastapi import APIRouter, HTTPException
from typing import Any, Dict
import subprocess
import threading
import time
from config import ALARMFW_ROOT, COMPOSE_RUN_CONFIG

router = APIRouter(prefix="/api/run", tags=["runner"])

# Son run sonucunu bellekte tut
_last_run: Dict[str, Any] = {}
_run_lock = threading.Lock()


def _do_run(config: str) -> None:
    global _last_run
    cmd = [
        "docker", "compose",
        "-f", str(ALARMFW_ROOT / "docker-compose.yml"),
        "run", "--rm", "alarmfw",
        "run", "--config", config,
    ]
    started = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(ALARMFW_ROOT),
        )
        _last_run = {
            "status": "done",
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-8000:],  # son 8KB
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
