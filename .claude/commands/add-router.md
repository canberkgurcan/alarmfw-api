# Yeni Router Oluştur

**Kullanım:** `/new-router <router adı> <kapsamı>`

## Karar: mevcut router'a mı, yeni mi?

| Durum | Karar |
|---|---|
| Check YAML işi | `checks.py` |
| Namespace/cluster config | `config.py` |
| Token/secret | `secrets.py` |
| SQLite alarm okuması | `alarms.py` / `monitor.py` |
| **Gerçekten yeni domain** (yeni dış sistem, yeni dosya tipi) | Yeni router |

Yeni router için geçerli sebep: ayrı URL prefix, ayrı dış bağımlılık, mantıksal olarak bağımsız kaynak grubu.

## Adımlar

**1.** `routers/<isim>.py`:
```python
from fastapi import APIRouter, HTTPException, Depends
from typing import Any, Dict, List
from config import ALARMFW_CONFIG, ALARMFW_SECRETS, ALARMFW_STATE
from auth import require_admin

router = APIRouter(prefix="/api/<isim>", tags=["<isim>"])

@router.get("")
async def list_items() -> List[Dict[str, Any]]:
    ...
```

`prefix` her zaman `/api/<isim>`; `tags` Swagger gruplaması — tutarlı tut.

**2.** `main.py`'ye ekle:
```python
from routers import checks, ..., <isim>
app.include_router(<isim>.router)
```

`routers/__init__.py` boş — dokunma.

## Mevcut Router'lar

| Dosya | Prefix | Kapsam | Kaynak |
|---|---|---|---|
| `checks.py` | `/api/checks` | Check CRUD | `config/checks/`, `generated/` |
| `config.py` | `/api/config` | Namespace + cluster + generate | `conf.d/`, `observe.yaml` |
| `secrets.py` | `/api/secrets` | Token dosyaları | `{SECRETS}/*.token` |
| `alarms.py` | `/api/alarms` | Alarm geçmişi/metrik | SQLite `alarm_state` |
| `monitor.py` | `/api/monitor` | Pod snapshot | SQLite + `generated/` |
| `runner.py` | `/api/run` | Runner tetikleme | `docker run` |
| `policies.py` | `/api/policies` | Maintenance/dedup + audit | `policies/*.yaml` |
| `terminal.py` | `/api/terminal` | oc shell | `subprocess` |
| `admin.py` | `/api/admin` | Zabbix test | dış HTTP |
| `notifiers.py` | `/api/notifiers` | Notifier config | `notifiers/*.yaml` |

## Yardımcılar

- Legacy `.conf` okuma/yazma: `routers._conf` (`read_conf`, `write_conf`, `is_true`, `bool_str`)
- Bloklayan IO: `async_utils.run_blocking`
- Path sabitleri: `config.py` (`ALARMFW_CONFIG/STATE/SECRETS`)
- Yazma endpoint'leri → `Depends(require_admin)`; config değiştiren → `_generate_yaml()`.
