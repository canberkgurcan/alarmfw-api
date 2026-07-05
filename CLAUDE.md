# alarmfw-api

AlarmFW kontrol-düzlemi API'si. FastAPI, port 8000. Kendi başına monitoring yapmaz — `alarmfw` runner'ının config'ini (check YAML'ları, cluster listesi, secret'lar) üretip yönetir, runner'ı tetikler ve runner'ın SQLite state'ini okur.

## İstek Akışı

```
HTTP Request (X-API-Key)
    │
    ├─ Yapılandırma yazımı   config.py     → conf.d/*.conf + observe.yaml → _generate_yaml() → generated/
    ├─ Check CRUD            checks.py     → config/checks/ + config/generated/ *.yaml
    ├─ Secret yönetimi       secrets.py    → {ALARMFW_SECRETS}/*.token (chmod 600)
    ├─ Alarm çalıştırma      runner.py     → docker run alarmfw:latest (mount'lar docker inspect'ten)
    ├─ Durum okuma           monitor.py    → SQLite alarm_state (alarmfw'in yazdığı)
    │                        alarms.py     → SQLite alarm geçmişi/metrikleri
    ├─ Politika              policies.py   → policies/maintenance.yaml + audit/versions
    └─ OCP shell             terminal.py   → oc exec/login
```

Bu servis **dosya sistemini ve SQLite'ı** kaynak-of-truth olarak kullanır; veritabanı katmanı yoktur. Yazdığı her şeyi `alarmfw` runner'ı okur.

## Auth Kontratı — `X-API-Key`

`auth.py`: tek mekanizma, `APIKeyHeader(name="X-API-Key")`.

```python
require_operator / require_admin   # ikisi de aynı _check()'i çağırır
```

- `ALARMFW_API_KEY` env **boşsa** → auth kapalı, herkes `"anonymous"` (dev modu)
- Doluysa → header eşleşmezse `403`
- Yazma/yönetim endpoint'leri `dependencies=[Depends(require_admin)]` ile korunur (ör. `config.py`'deki tüm PUT/DELETE/generate). Yeni yazma endpoint'i eklerken bu dependency'yi unutma.

> Rol ayrımı (admin/operator/readonly) gerçekte UI tarafında, farklı API key'lerle yapılır (bkz. `alarmfw-ui`). API tarafı sadece "doğru key mi" kontrol eder.

## Merkezi Veri Modeli — Üç Ayrı Kaynak

Config tek dosyada değil, üç ayrı yerde tutulur ve birbirine **generate** ile bağlanır:

| Varlık | Nerede | Format |
|---|---|---|
| Namespace ayarları | `legacy/podhealthalarm/conf.d/<ns>.conf` | `KEY="value"` (legacy) |
| Cluster + OCP/Prometheus URL | `config/observe.yaml` → `clusters[]` | YAML (alarmfw-observe ile paylaşılır) |
| Üretilmiş check'ler | `config/generated/ocp_pod_health.yaml` | YAML (runner okur) |
| Elle yazılmış check'ler | `config/checks/*.yaml` | YAML |

**`_generate_yaml()` (config.py:16) değişmezi:** namespace `.conf` dosyaları × `observe.yaml` cluster'ları çarpımından `generated/ocp_pod_health.yaml` üretilir. Bir namespace veya cluster her değiştiğinde (PUT/DELETE) `_generate_yaml()` **mutlaka** yeniden çağrılmalı — aksi halde UI'da değişiklik görünür ama runner eski config'i çalıştırır. Mevcut namespace endpoint'leri bunu zaten yapıyor; yeni yazma yolu eklersen sen de çağır.

Notify yönlendirmesi de burada belirlenir: `ZABBIX_ENABLED`/`MAIL_ENABLED` bayraklarına göre `primary`/`fallback` notifier listeleri kurulur.

## Hata Modeli

Düz FastAPI: hatada `raise HTTPException(<code>, msg)`. Yaygın kodlar:

| Kod | Durum |
|---|---|
| `400` | Geçersiz girdi (boş name, geçersiz cluster adı) |
| `403` | API key yok/yanlış |
| `404` | Kaynak yok (check/namespace/cluster bulunamadı) |
| `409` | Çakışma (dosya zaten var, run zaten devam ediyor) |

`alarmfw-observe`'in "soft error" (`{"ok": False}` + 200) modelini **burada kullanma** — bu servis hard-fail eder.

## Bloklayan İşler — `run_blocking`

`async_utils.run_blocking(func, *args)` bloklayan IO'yu (subprocess, dosya, SQLite) `ThreadPoolExecutor`'a (8 worker) atar; event loop'u dondurmaz. Router'lar çoğunlukla iç senkron `_func()` tanımlayıp doğrudan çağırıyor — ağır/uzun IO eklediğinde `await run_blocking(_func)` ile sar. Özellikle `subprocess` (runner, terminal) için zorunlu.

## Router Haritası

```
main.py  (CORS: CORS_ORIGINS env, varsayılan http://localhost:3000)
├── checks.py     /api/checks      Check YAML CRUD (checks/ + generated/)
├── notifiers.py  /api/notifiers   Notifier config
├── secrets.py    /api/secrets     Token dosyaları (chmod 600, cluster adı doğrulama)
├── alarms.py     /api/alarms      Alarm listesi/geçmişi/metrikleri (SQLite)
├── runner.py     /api/run         docker run alarmfw:latest tetikleme
├── policies.py   /api/policies    maintenance/dedup + audit + versions + rollback
├── config.py     /api/config      namespaces + clusters + generate  ← çekirdek
├── monitor.py    /api/monitor     Pod snapshot (SQLite alarm_state'ten)
├── terminal.py   /api/terminal    oc exec/login/whoami
└── admin.py      /api/admin        Zabbix test gönderimi
```

`/api/health` auth'suz health probe.

## Korunması Gereken Değişmezler

**`config.py:_generate_yaml()`** — namespace/cluster yazımının ardından her zaman çağrılmalı (yukarı bak).

**`secrets.py` güvenliği** — token dosyaları `0o600` ile yazılır; cluster adı `isalnum()` (+ `-_`) ile doğrulanır (path traversal önlemi). Yeni secret yolu eklerken ikisini de koru.

**`runner.py` mount keşfi** — `docker inspect <hostname>` ile current container'ın `/config`, `/secrets`, `/state` mount'larını alıp yeni `alarmfw:latest` container'ına aynısını verir. Docker socket erişimi şart; mount alınamazsa run hata döner. `_last_run` bellekte tutulur, `_run_lock` ile aynı anda tek run.

**`monitor.py`/`alarms.py` SQLite okuması** — `alarm_state` tablosunu salt-okunur tüketir (`PRAGMA journal_mode=WAL`). Şema `alarmfw/dedup/store_sqlite.py`'de tanımlı; orada değişiklik buradaki okuyucuları etkiler.

## Ortam Değişkenleri

| Değişken | Varsayılan |
|---|---|
| `ALARMFW_ROOT` | `/home/cnbrkgrcn/projects/alarmfw` |
| `ALARMFW_CONFIG` | `{ROOT}/config` |
| `ALARMFW_STATE` | `{ROOT}/state` |
| `ALARMFW_SECRETS` | `/home/cnbrkgrcn/alarmfw-secrets` |
| `COMPOSE_RUN_CONFIG` | `/config/run_local.yaml` |
| `ALARMFW_API_KEY` | — (boşsa auth kapalı) |
| `CORS_ORIGINS` | `http://localhost:3000` |

## Çalıştırma & Test

```bash
uvicorn main:app --reload --port 8000     # Swagger: /docs
python -m pytest tests/
```
