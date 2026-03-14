import os
from fastapi import APIRouter, HTTPException, UploadFile, File
from typing import Any, Dict, List
from config import ALARMFW_SECRETS

router = APIRouter(prefix="/api/secrets", tags=["secrets"])


@router.get("")
async def list_secrets() -> List[Dict[str, Any]]:
    def _list_secrets() -> List[Dict[str, Any]]:
        if not ALARMFW_SECRETS.exists():
            return []
        result = []
        for f in sorted(ALARMFW_SECRETS.glob("*.token")):
            stat = f.stat()
            result.append({
                "name": f.name,
                "cluster": f.stem,
                "size_bytes": stat.st_size,
                "modified": stat.st_mtime,
            })
        return result

    return _list_secrets()


@router.put("/{cluster}")
async def upload_secret(cluster: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    if not cluster.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "Invalid cluster name")
    content = await file.read()

    def _write_secret() -> Dict[str, Any]:
        ALARMFW_SECRETS.mkdir(parents=True, exist_ok=True)
        dest = ALARMFW_SECRETS / f"{cluster}.token"
        dest.write_bytes(content)
        os.chmod(dest, 0o600)
        return {"ok": True, "cluster": cluster, "file": dest.name}

    return _write_secret()


@router.put("/{cluster}/text")
async def upload_secret_text(cluster: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Token'ı text olarak yükle (multipart yerine JSON body)."""
    token = body.get("token", "").strip()
    if not token:
        raise HTTPException(400, "token is required")
    if not cluster.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "Invalid cluster name")

    def _write_secret_text() -> Dict[str, Any]:
        ALARMFW_SECRETS.mkdir(parents=True, exist_ok=True)
        dest = ALARMFW_SECRETS / f"{cluster}.token"
        dest.write_text(token)
        os.chmod(dest, 0o600)
        return {"ok": True, "cluster": cluster, "file": dest.name}

    return _write_secret_text()


@router.delete("/{cluster}")
async def delete_secret(cluster: str) -> Dict[str, Any]:
    def _delete_secret() -> Dict[str, Any]:
        dest = ALARMFW_SECRETS / f"{cluster}.token"
        if not dest.exists():
            raise HTTPException(404, f"{cluster}.token not found")
        dest.unlink()
        return {"ok": True, "cluster": cluster}

    return _delete_secret()
