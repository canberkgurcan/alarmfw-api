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
oc apply -f ocp/deployment.yaml -n alarmfw-prod
oc set image deployment/alarmfw-api alarmfw-api=REGISTRY/alarmfw-api:TAG -n alarmfw-prod
```

> PVC'lerin önceden oluşturulmuş olması gerekir: `oc apply -f ../alarmfw/ocp/pvc.yaml -n alarmfw-prod`

## Jenkins Pipeline

4 stage: **Checkout SCM → Docker Build → Nexus Push → OCP Deploy**

| Değişken | Açıklama |
|---|---|
| `REGISTRY_URL` | Nexus registry adresi |
| `REGISTRY_CREDS` | Jenkins credential ID (Docker kullanıcı/şifre) |
| `OCP_API_URL` | OpenShift API endpoint |
| `OCP_TOKEN_CREDS` | Jenkins credential ID (OCP service account token) |
| `DEPLOY_NAMESPACE` | Deploy namespace (ör: `alarmfw-prod`) |
