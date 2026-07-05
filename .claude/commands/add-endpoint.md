# Yeni Endpoint Ekle

**Kullanım:** `/add-endpoint <ne yapacağını açıkla>`

## Önce: yazma mı, okuma mı?

| Tür | Kurallar |
|---|---|
| **Okuma** (GET) | Auth opsiyonel; hata → `HTTPException` |
| **Yazma** (PUT/POST/DELETE) | `dependencies=[Depends(require_admin)]` ekle; config'i değiştiriyorsa `_generate_yaml()` çağır |

## İskelet — mevcut bir router'a ekle

```python
from fastapi import APIRouter, HTTPException, Depends
from typing import Any, Dict, List
from config import ALARMFW_CONFIG
from auth import require_admin

# router zaten dosyada tanımlı: APIRouter(prefix="/api/<grup>", tags=["<grup>"])

@router.post("/yeni", dependencies=[Depends(require_admin)])   # yazma → admin
async def yeni_endpoint(body: Dict[str, Any]) -> Dict[str, Any]:
    name = body.get("name")
    if not name:
        raise HTTPException(400, "name is required")
    # ... dosya/SQLite işi ...
    return {"ok": True, "name": name}
```

## Hata kodları (tutarlı kullan)

| Kod | Ne zaman |
|---|---|
| `400` | Geçersiz/eksik girdi |
| `403` | (auth dependency otomatik) |
| `404` | Kaynak bulunamadı |
| `409` | Çakışma — dosya zaten var / işlem zaten sürüyor |

`alarmfw-observe`'in `{"ok": False}`+200 soft-error modelini **kullanma**; bu serviste hatada exception fırlat.

## Config yazıyorsan → generate'i unutma

Namespace (`conf.d/*.conf`) veya cluster (`observe.yaml`) değiştiren her yazma, sonunda:

```python
from routers.config import _generate_yaml
count = _generate_yaml()
return {"ok": True, "generated_checks": count}
```

Aksi halde UI'da değişiklik görünür ama `alarmfw` runner eski `generated/ocp_pod_health.yaml`'ı çalıştırır.

## Bloklayan IO → run_blocking

`subprocess`, büyük dosya, ağ çağrısı varsa event loop'u dondurma:

```python
from async_utils import run_blocking

def _heavy() -> Dict[str, Any]:
    ...   # subprocess / file / sqlite
    return result

return await run_blocking(_heavy)
```

`subprocess` çağıran her şey (docker, oc) için zorunlu.

## Secret/dosya yazıyorsan

- Token dosyaları: `dest.write_*`, ardından `os.chmod(dest, 0o600)`
- Kullanıcıdan gelen path bileşenini doğrula: `name.replace("-","").replace("_","").isalnum()` (path traversal önlemi)

## Test

```bash
uvicorn main:app --reload --port 8000   # /docs ile elle dene
python -m pytest tests/
```
