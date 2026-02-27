from fastapi import APIRouter, HTTPException
from typing import Any, Dict, List
import yaml
from config import ALARMFW_CONFIG

router = APIRouter(prefix="/api/checks", tags=["checks"])


def _check_files() -> List[Any]:
    """config/checks/ ve config/generated/ altındaki tüm yaml'lardan check listesi döner."""
    checks = []
    for subdir in ("checks", "generated"):
        d = ALARMFW_CONFIG / subdir
        if not d.exists():
            continue
        for f in sorted(d.glob("*.yaml")):
            try:
                data = yaml.safe_load(f.read_text())
                for chk in (data or {}).get("checks") or []:
                    chk["_source_file"] = str(f.relative_to(ALARMFW_CONFIG))
                    checks.append(chk)
            except Exception as e:
                checks.append({"_error": str(e), "_source_file": str(f)})
    return checks


def _find_check(name: str):
    """Verilen isimde check'i ve bulunduğu dosyayı döner."""
    for subdir in ("checks", "generated"):
        d = ALARMFW_CONFIG / subdir
        if not d.exists():
            continue
        for f in sorted(d.glob("*.yaml")):
            try:
                data = yaml.safe_load(f.read_text()) or {}
                checks = data.get("checks") or []
                for i, chk in enumerate(checks):
                    if chk.get("name") == name:
                        return f, data, i
            except Exception:
                pass
    return None, None, None


@router.get("")
def list_checks() -> List[Dict[str, Any]]:
    return _check_files()


@router.get("/{name}")
def get_check(name: str) -> Dict[str, Any]:
    f, data, idx = _find_check(name)
    if f is None:
        raise HTTPException(404, f"Check '{name}' not found")
    chk = data["checks"][idx]
    chk["_source_file"] = str(f.relative_to(ALARMFW_CONFIG))
    return chk


@router.put("/{name}")
def update_check(name: str, body: Dict[str, Any]) -> Dict[str, Any]:
    f, data, idx = _find_check(name)
    if f is None:
        raise HTTPException(404, f"Check '{name}' not found")
    body.pop("_source_file", None)
    data["checks"][idx] = body
    f.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False))
    return {"ok": True, "name": name}


@router.post("")
def create_check(body: Dict[str, Any]) -> Dict[str, Any]:
    name = body.get("name")
    if not name:
        raise HTTPException(400, "name is required")
    # Eğer generated/ yoksa checks/ altına yaz
    target_dir = ALARMFW_CONFIG / "checks"
    target_dir.mkdir(exist_ok=True)
    fname = target_dir / f"{name}.yaml"
    if fname.exists():
        raise HTTPException(409, f"File {fname.name} already exists")
    body.pop("_source_file", None)
    fname.write_text(yaml.dump({"checks": [body]}, allow_unicode=True, default_flow_style=False))
    return {"ok": True, "name": name, "file": fname.name}


@router.delete("/{name}")
def delete_check(name: str) -> Dict[str, Any]:
    f, data, idx = _find_check(name)
    if f is None:
        raise HTTPException(404, f"Check '{name}' not found")
    data["checks"].pop(idx)
    if data["checks"]:
        f.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False))
    else:
        f.unlink()
    return {"ok": True, "name": name}
