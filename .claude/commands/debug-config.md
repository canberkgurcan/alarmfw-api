# Config / Generate Akışını Hata Ayıkla

**Kullanım:** `/debug-config <UI'da/runner'da görünen tutarsızlık>`

Çoğu "değişiklik etkisiz" şikâyeti, üç kaynağın (`conf.d`, `observe.yaml`, `generated/`) senkron olmamasıdır.

## Veri akışı

```
conf.d/<ns>.conf   (namespace ayarları)  ─┐
                                          ├─→ _generate_yaml() ─→ generated/ocp_pod_health.yaml ─→ alarmfw runner
observe.yaml clusters[]  (cluster+URL)   ─┘
```

## 1. "Namespace ekledim ama runner görmüyor"

`_generate_yaml()` çağrılmamış demektir. Üretim şartları (`config.py:_generate_yaml`):
- `NAMESPACE_ENABLED="true"` (değilse atlanır)
- `CLUSTERS` boş değil
- Her cluster `observe.yaml`'da **var olmalı** ve `ocp_api` dolu olmalı — yoksa o (ns, cluster) çifti atlanır

`POST /api/config/generate` ile elle tetikle, dönen `generated_checks` sayısını kontrol et. 0 ise yukarıdaki şartlardan biri sağlanmıyor.

## 2. "Cluster ekledim ama check üretilmiyor"

Cluster `observe.yaml clusters[]`'de olmalı ve `ocp_api` dolu olmalı. `GET /api/config/clusters` ile bak; `ocp_api` boşsa `_generate_yaml` o cluster'ı atlar (`if not ocp_api: continue`).

## 3. "Token var ama runner okuyamıyor"

Generate edilen check `ocp_token_file: /secrets/<cluster>.token` yazar (container içi path). `GET /api/secrets` ile `<cluster>.token` var mı bak. `secrets.py` dosyaları `0o600` ile yazar; cluster adı `isalnum()+-_` doğrulamasından geçmezse `400`.

## 4. "Notify yanlış kanaldan gidiyor"

`_generate_yaml` notify listesini namespace bayraklarından kurar:

| ZABBIX_ENABLED | MAIL_ENABLED | primary | fallback |
|---|---|---|---|
| ✓ | ✓ | zabbix | dev_smtp, smtp, dev_outbox |
| ✓ | ✗ | zabbix | dev_smtp, dev_outbox |
| ✗ | ✓ | smtp | dev_smtp, dev_outbox |
| ✗ | ✗ | dev_outbox | — |

Beklenmedik kanal → `conf.d/<ns>.conf` içindeki bu iki bayrağı kontrol et.

## 5. "Run başlamıyor / 409"

`runner.py`: aynı anda tek run (`_run_lock`, `_last_run.status == "running"` ise `409`). `GET /api/run/last` ile son durumu gör. Mount alınamadıysa (`docker inspect <hostname>` başarısız) `stderr: "Container mount bilgisi alınamadı"` — Docker socket erişimi yok demektir.

## 6. Üretilen dosyayı doğrula

```bash
cat config/generated/ocp_pod_health.yaml
```
Bu dosya `alarmfw` runner'ının `base.yaml` includes'ı üzerinden okuduğu nihai check listesidir. Elle düzenleme — bir sonraki generate ezer; kaynağı (`conf.d`, `observe.yaml`) düzelt.
