# alarmfw-api

AlarmFW yönetim API'si. FastAPI tabanlı, port 8000.

## Endpoints

| Grup | Prefix | Açıklama |
|---|---|---|
| Alarms | `/api/alarms` | Alarm listesi, durum |
| Checks | `/api/checks` | Check YAML yönetimi |
| Secrets | `/api/secrets` | Token dosyası yönetimi |
| Runner | `/api/run` | Manuel alarm run tetikleme |
| Env | `/api/env` | Ortam değişkeni yönetimi |
| Config | `/api/config` | Cluster/namespace config |
| Terminal | `/api/terminal` | OCP shell (exec, login, whoami) |
| Monitor | `/api/monitor` | Pod snapshot verileri |

Swagger UI: `http://localhost:8000/docs`

## Ortam Değişkenleri

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `ALARMFW_CONFIG` | `/config` | Config YAML dizini |
| `ALARMFW_SECRETS` | `/secrets` | Token dosyaları dizini |

## Geliştirme

```bash
pip install fastapi uvicorn pyyaml python-dotenv
uvicorn main:app --reload --port 8000
```

## Docker

```bash
docker build -t alarmfw-api:latest .
docker run -p 8000:8000 \
  -e ALARMFW_CONFIG=/config \
  -e ALARMFW_SECRETS=/secrets \
  -v /path/to/config:/config \
  -v /path/to/secrets:/secrets \
  alarmfw-api:latest
```

## OCP Deploy

```bash
# PVC'lerin oluşturulmuş olması gerekir (alarmfw reposundaki ocp/pvc.yaml)
oc apply -f ocp/deployment.yaml -n alarmfw-prod
```

Pipeline: `Jenkinsfile`
