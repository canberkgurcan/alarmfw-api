#!/bin/bash
# =============================================================================
# AlarmFW Bootstrap Script — İlk Kurulum
# =============================================================================
# Admin Console'dan çalıştır:
#   bash /app/scripts/bootstrap.sh [FLAG'LAR]
#
# Minimum kullanım (tek cluster):
#   bash /app/scripts/bootstrap.sh \
#     --cluster izm-digital \
#     --ocp-api https://api.izm-digital.vodafone.local:6443 \
#     --ocp-token eyJhbGc... \
#     --prometheus-url https://thanos-querier.apps.izm-digital.vodafone.local \
#     --prometheus-token eyJhbGc...
#
# Tam kullanım (SMTP + Zabbix da dahil):
#   bash /app/scripts/bootstrap.sh \
#     --cluster izm-digital \
#     --ocp-api https://api.izm-digital.vodafone.local:6443 \
#     --ocp-token eyJhbGc... \
#     --prometheus-url https://thanos-querier... \
#     --prometheus-token eyJhbGc... \
#     --smtp-host mailrelay.internal \
#     --smtp-port 25 \
#     --smtp-user alarmfw@company.com \
#     --smtp-pass "" \
#     --smtp-to ops@company.com \
#     --zabbix-url https://zabbix.internal \
#     --zabbix-token abc123
#
# Script tekrar çalıştırılabilir (idempotent) — mevcut dosyaları üzerine yazar.
# =============================================================================

set -euo pipefail

# ── Renk kodları ──────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}  $*"; }
info() { echo -e "${CYAN}[..]${NC}  $*"; }
warn() { echo -e "${YELLOW}[!!]${NC}  $*"; }
err()  { echo -e "${RED}[ERR]${NC} $*"; exit 1; }

# ── Değişkenler (flag'larla doldurulur) ───────────────────────────────────────
CLUSTER=""
OCP_API=""
OCP_TOKEN=""
PROMETHEUS_URL=""
PROMETHEUS_TOKEN=""
SMTP_HOST=""
SMTP_PORT="25"
SMTP_USER=""
SMTP_PASS=""
SMTP_TO=""
ZABBIX_URL=""
ZABBIX_TOKEN=""

CONFIG_DIR="${ALARMFW_CONFIG:-/config}"
SECRETS_DIR="${ALARMFW_SECRETS:-/secrets}"
API_BASE="http://localhost:8000"

# ── Flag parse ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --cluster)          CLUSTER="$2";          shift 2 ;;
        --ocp-api)          OCP_API="$2";           shift 2 ;;
        --ocp-token)        OCP_TOKEN="$2";         shift 2 ;;
        --prometheus-url)   PROMETHEUS_URL="$2";    shift 2 ;;
        --prometheus-token) PROMETHEUS_TOKEN="$2";  shift 2 ;;
        --smtp-host)        SMTP_HOST="$2";         shift 2 ;;
        --smtp-port)        SMTP_PORT="$2";         shift 2 ;;
        --smtp-user)        SMTP_USER="$2";         shift 2 ;;
        --smtp-pass)        SMTP_PASS="$2";         shift 2 ;;
        --smtp-to)          SMTP_TO="$2";           shift 2 ;;
        --zabbix-url)       ZABBIX_URL="$2";        shift 2 ;;
        --zabbix-token)     ZABBIX_TOKEN="$2";      shift 2 ;;
        --help|-h)
            sed -n '3,30p' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) err "Bilinmeyen flag: $1. --help ile kullanıma bakın." ;;
    esac
done

# ── Zorunlu alan kontrolü ─────────────────────────────────────────────────────
[[ -z "$CLUSTER" ]]    && err "--cluster zorunlu"
[[ -z "$OCP_API" ]]    && err "--ocp-api zorunlu"
[[ -z "$OCP_TOKEN" ]]  && err "--ocp-token zorunlu"

echo ""
echo -e "${CYAN}AlarmFW Bootstrap — Cluster: ${CLUSTER}${NC}"
echo "========================================"

# ── 1. Dizin kontrolü ─────────────────────────────────────────────────────────
info "Dizinler kontrol ediliyor..."
mkdir -p "${CONFIG_DIR}/notifiers" "${CONFIG_DIR}/generated" "${SECRETS_DIR}"
ok "Dizinler hazır: ${CONFIG_DIR}, ${SECRETS_DIR}"

# ── 2. OCP token kaydet ───────────────────────────────────────────────────────
info "OCP token kaydediliyor → ${SECRETS_DIR}/${CLUSTER}.token"
printf '%s' "${OCP_TOKEN}" > "${SECRETS_DIR}/${CLUSTER}.token"
chmod 600 "${SECRETS_DIR}/${CLUSTER}.token"
ok "OCP token kaydedildi"

# ── 3. Prometheus token kaydet ────────────────────────────────────────────────
if [[ -n "$PROMETHEUS_TOKEN" ]]; then
    info "Prometheus token kaydediliyor → ${SECRETS_DIR}/${CLUSTER}-prometheus.token"
    printf '%s' "${PROMETHEUS_TOKEN}" > "${SECRETS_DIR}/${CLUSTER}-prometheus.token"
    chmod 600 "${SECRETS_DIR}/${CLUSTER}-prometheus.token"
    ok "Prometheus token kaydedildi"
fi

# ── 4. observe.yaml — cluster tanımı ─────────────────────────────────────────
info "observe.yaml güncelleniyor..."
OBSERVE_YAML="${CONFIG_DIR}/observe.yaml"

# Dosya yoksa oluştur, varsa cluster'ı güncelle/ekle
if [[ ! -f "$OBSERVE_YAML" ]]; then
    cat > "$OBSERVE_YAML" << YAML
clusters: []
YAML
fi

# Python ile YAML güncelle (mevcut kodu bozmadan)
python3 - << PYEOF
import yaml

path = "${OBSERVE_YAML}"
with open(path) as f:
    data = yaml.safe_load(f) or {}

# clusters her zaman list of dict olmalı — bozuk formatlarda sıfırla
raw = data.get("clusters", [])
clusters = [c for c in raw if isinstance(c, dict)] if isinstance(raw, list) else []

entry = {
    "name":                  "${CLUSTER}",
    "ocp_api":               "${OCP_API}",
    "insecure":              True,
    "prometheus_url":        "${PROMETHEUS_URL}",
    "prometheus_token_file": "${SECRETS_DIR}/${CLUSTER}-prometheus.token",
}

# Mevcut cluster'ı güncelle veya ekle
found = False
for i, c in enumerate(clusters):
    if c.get("name") == "${CLUSTER}":
        clusters[i] = entry
        found = True
        break
if not found:
    clusters.append(entry)

data["clusters"] = clusters
with open(path, "w") as f:
    yaml.dump(data, f, allow_unicode=True, default_flow_style=False)

print("OK")
PYEOF
ok "observe.yaml güncellendi"

# ── 5. Cluster config — API üzerinden doğrula ────────────────────────────────
# (observe.yaml step 4'te zaten yazıldı; bu adım API'yi tetikleyerek sync sağlar)
info "Cluster config API'ye bildiriliyor (${CLUSTER})..."
CLUSTER_PAYLOAD=$(cat << JSON
{
  "name": "${CLUSTER}",
  "ocp_api": "${OCP_API}",
  "insecure": true,
  "prometheus_url": "${PROMETHEUS_URL}"
}
JSON
)
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X PUT "${API_BASE}/api/config/observe-clusters/${CLUSTER}" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${ALARMFW_API_KEY:-}" \
    -d "${CLUSTER_PAYLOAD}" 2>/dev/null)
if [[ "$HTTP_CODE" == "200" ]]; then
    ok "Cluster API kaydı tamam (HTTP 200)"
else
    warn "Cluster API yanıtı: HTTP ${HTTP_CODE} (observe.yaml zaten güncel, devam ediliyor)"
fi

# ── 6. Config generate et ────────────────────────────────────────────────────
info "Config oluşturuluyor (check YAML'ları)..."
HTTP_CODE=$(curl -s -o /tmp/gen_out.json -w "%{http_code}" \
    -X POST "${API_BASE}/api/config/generate" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${ALARMFW_API_KEY:-}" 2>/dev/null)
if [[ "$HTTP_CODE" == "200" ]]; then
    CHECKS=$(python3 -c "import json; d=json.load(open('/tmp/gen_out.json')); print(d.get('generated_checks',0))" 2>/dev/null || echo "?")
    ok "Config üretildi — ${CHECKS} check"
else
    warn "Config üretme yanıtı: HTTP ${HTTP_CODE}"
fi

# ── 7. SMTP notifier ─────────────────────────────────────────────────────────
if [[ -n "$SMTP_HOST" ]]; then
    info "SMTP notifier yapılandırılıyor..."
    cat > "${CONFIG_DIR}/notifiers/smtp.yaml" << YAML
notifiers:
  smtp:
    type: "smtp_mail"
    host: "${SMTP_HOST}"
    port: ${SMTP_PORT}
    user: "${SMTP_USER}"
    password: "${SMTP_PASS}"
    from: "${SMTP_USER:-alarmfw@localhost}"
    to: ["${SMTP_TO}"]
    subject_prefix: "[ALARMFW]"
    use_tls: false
YAML
    ok "SMTP yapılandırıldı (${SMTP_HOST}:${SMTP_PORT})"
fi

# ── 8. Zabbix notifier ────────────────────────────────────────────────────────
if [[ -n "$ZABBIX_URL" ]]; then
    info "Zabbix notifier yapılandırılıyor..."
    cat > "${CONFIG_DIR}/notifiers/zabbix.yaml" << YAML
notifiers:
  zabbix:
    type: "zabbix_http"
    url: "${ZABBIX_URL}"
    timeout_sec: 10
    headers:
      Content-Type: "application/json"
    auth:
      type: "bearer"
      token: "${ZABBIX_TOKEN}"
YAML
    ok "Zabbix yapılandırıldı (${ZABBIX_URL})"
fi

# ── 9. Özet ──────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}========================================"
echo -e "Bootstrap tamamlandı!"
echo -e "========================================${NC}"
echo ""
echo "  Cluster  : ${CLUSTER}"
echo "  OCP API  : ${OCP_API}"
[[ -n "$PROMETHEUS_URL" ]]  && echo "  Prometheus: ${PROMETHEUS_URL}"
[[ -n "$SMTP_HOST" ]]       && echo "  SMTP     : ${SMTP_HOST}:${SMTP_PORT}"
[[ -n "$ZABBIX_URL" ]]      && echo "  Zabbix   : ${ZABBIX_URL}"
echo ""
echo "Sonraki adım: UI üzerinden Monitor veya Observe sayfasını kontrol et."
echo ""
