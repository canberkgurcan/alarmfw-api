#!/bin/bash
# =============================================================================
# AlarmFW — İnteraktif Bootstrap Çalıştırıcı
#
# Kullanım:
#   bash scripts/run_bootstrap.sh                    # mod sorar
#   bash scripts/run_bootstrap.sh --mode docker      # Docker Compose
#   bash scripts/run_bootstrap.sh --mode ocp         # OpenShift
#
# Docker modunda: alarmfw-api container'ını otomatik bulur
# OCP modunda   : oc exec <pod> kullanır — önceden oc login gerekir
# =============================================================================

set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

ask()      { echo -en "${CYAN}?${NC}  ${BOLD}$1${NC} "; read -r "$2"; }
ask_pass() { echo -en "${CYAN}?${NC}  ${BOLD}$1${NC} "; read -rs "$2"; echo; }
ask_opt()  { echo -en "${CYAN}?${NC}  ${BOLD}$1${NC}${YELLOW} [Enter = atla]${NC} "; read -r "$2"; }
ok()       { echo -e "${GREEN}✔${NC}  $*"; }
sep()      { echo -e "${YELLOW}────────────────────────────────────────${NC}"; }

# ── Mod seçimi ────────────────────────────────────────────────────────────────
MODE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode) MODE="$2"; shift 2 ;;
        *) echo "Bilinmeyen flag: $1"; exit 1 ;;
    esac
done

echo ""
echo -e "${BOLD}${CYAN}AlarmFW Bootstrap — İnteraktif Kurulum${NC}"
sep

if [[ -z "$MODE" ]]; then
    echo -e "  ${BOLD}1)${NC} Docker Compose  (local linux host)"
    echo -e "  ${BOLD}2)${NC} OpenShift       (oc exec)"
    echo ""
    echo -en "${BOLD}Mod seçin [1/2]:${NC} "
    read -r MOD_SEC
    case "$MOD_SEC" in
        1) MODE="docker" ;;
        2) MODE="ocp" ;;
        *) echo "Geçersiz seçim."; exit 1 ;;
    esac
fi

# ── Docker modu: container adını otomatik bul ─────────────────────────────────
DOCKER_CONTAINER=""
if [[ "$MODE" == "docker" ]]; then
    sep
    echo -e "${CYAN}..${NC}  alarmfw-api container'ı aranıyor..."
    DOCKER_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E 'alarmfw.?api' | head -1 || true)
    if [[ -z "$DOCKER_CONTAINER" ]]; then
        echo -e "${YELLOW}Container otomatik bulunamadı.${NC}"
        ask "Container adı (docker ps ile kontrol et):" DOCKER_CONTAINER
    else
        ok "Container bulundu: ${DOCKER_CONTAINER}"
    fi
fi

# ── OCP modu: ek bilgiler ─────────────────────────────────────────────────────
OCP_NAMESPACE=""
OCP_POD=""
if [[ "$MODE" == "ocp" ]]; then
    sep
    echo -e "${BOLD}OpenShift Bağlantısı${NC}"
    sep
    echo -e "${YELLOW}Not: oc login yapılmış olmalı.${NC}"
    ask "Namespace  (örn: alarmfw-prod):" OCP_NAMESPACE
    echo -e "${CYAN}..${NC}  alarmfw-api pod'u aranıyor..."
    OCP_POD=$(oc get pods -n "$OCP_NAMESPACE" \
        --field-selector=status.phase=Running \
        -l app=alarmfw-api \
        -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
    if [[ -z "$OCP_POD" ]]; then
        echo -e "${YELLOW}Pod otomatik bulunamadı.${NC}"
        ask "Pod adı (oc get pods ile kontrol et):" OCP_POD
    else
        ok "Pod bulundu: ${OCP_POD}"
    fi
fi

# ── SMTP — bir kez sor, tüm cluster'larda kullanılır ─────────────────────────
sep
echo -e "${BOLD}SMTP  ${YELLOW}(atlamak için host'u boş bırak — tüm cluster'lar için ortak)${NC}"
sep

ask_opt "SMTP host  (örn: mailrelay.internal):"  SMTP_HOST
if [[ -n "${SMTP_HOST:-}" ]]; then
    ask      "SMTP port  [25]:"                   SMTP_PORT
    SMTP_PORT="${SMTP_PORT:-25}"
    ask_opt  "SMTP kullanıcı:"                    SMTP_USER
    ask_pass "SMTP şifre  [boş bırakılabilir]:"   SMTP_PASS
    ask      "SMTP alıcı  (örn: ops@sirket.com):" SMTP_TO
else
    SMTP_PORT=""; SMTP_USER=""; SMTP_PASS=""; SMTP_TO=""
fi

# ── Zabbix — bir kez sor ──────────────────────────────────────────────────────
sep
echo -e "${BOLD}Zabbix  ${YELLOW}(atlamak için URL'yi boş bırak — tüm cluster'lar için ortak)${NC}"
sep

ask_opt "Zabbix URL   (örn: https://zabbix.internal):" ZABBIX_URL
if [[ -n "${ZABBIX_URL:-}" ]]; then
    ask_pass "Zabbix token:" ZABBIX_TOKEN
else
    ZABBIX_TOKEN=""
fi

# ── Cluster döngüsü ───────────────────────────────────────────────────────────
run_bootstrap_for_cluster() {
    local CLUSTER="$1" OCP_API="$2" OCP_TOKEN="$3" PROMETHEUS_URL="$4" PROMETHEUS_TOKEN="$5"

    CMD=(bash /app/scripts/bootstrap.sh
        --cluster   "$CLUSTER"
        --ocp-api   "$OCP_API"
        --ocp-token "$OCP_TOKEN"
    )
    [[ -n "$PROMETHEUS_URL" ]]   && CMD+=(--prometheus-url   "$PROMETHEUS_URL")
    [[ -n "$PROMETHEUS_TOKEN" ]] && CMD+=(--prometheus-token "$PROMETHEUS_TOKEN")
    [[ -n "${SMTP_HOST:-}" ]]    && CMD+=(--smtp-host "$SMTP_HOST" --smtp-port "$SMTP_PORT" --smtp-to "$SMTP_TO")
    [[ -n "${SMTP_USER:-}" ]]    && CMD+=(--smtp-user "$SMTP_USER")
    [[ -n "${SMTP_PASS:-}" ]]    && CMD+=(--smtp-pass "$SMTP_PASS")
    [[ -n "${ZABBIX_URL:-}" ]]   && CMD+=(--zabbix-url "$ZABBIX_URL")
    [[ -n "${ZABBIX_TOKEN:-}" ]] && CMD+=(--zabbix-token "$ZABBIX_TOKEN")

    if [[ "$MODE" == "docker" ]]; then
        docker exec -i "$DOCKER_CONTAINER" "${CMD[@]}"
    else
        oc exec -n "$OCP_NAMESPACE" "$OCP_POD" -i -- "${CMD[@]}"
    fi
}

CLUSTER_COUNT=0
while true; do
    CLUSTER_COUNT=$((CLUSTER_COUNT + 1))
    sep
    echo -e "${BOLD}Cluster #${CLUSTER_COUNT}${NC}"
    sep

    ask      "Cluster adı  (örn: izm-digital):"         CLUSTER
    ask      "OCP API URL  (örn: https://api.X:6443):"  OCP_API
    ask_pass "OCP token:"                                OCP_TOKEN

    sep
    echo -e "${BOLD}Prometheus — Cluster: ${CLUSTER}${NC}"
    sep
    ask_opt "Prometheus URL  (örn: https://thanos-querier.apps.X):" PROMETHEUS_URL
    if [[ -n "${PROMETHEUS_URL:-}" ]]; then
        ask_pass "Prometheus token:" PROMETHEUS_TOKEN
    else
        PROMETHEUS_TOKEN=""
    fi

    # Özet
    sep
    echo -e "${BOLD}Özet — Cluster #${CLUSTER_COUNT}${NC}"
    sep
    echo -e "  Mod        : ${MODE}"
    [[ "$MODE" == "docker" ]] && echo -e "  Container  : ${DOCKER_CONTAINER}"
    [[ "$MODE" == "ocp" ]]    && echo -e "  Pod        : ${OCP_NAMESPACE}/${OCP_POD}"
    echo -e "  Cluster    : ${CLUSTER}"
    echo -e "  OCP API    : ${OCP_API}"
    echo -e "  OCP token  : ${OCP_TOKEN:0:20}..."
    [[ -n "${PROMETHEUS_URL:-}" ]] && echo -e "  Prometheus : ${PROMETHEUS_URL}"
    [[ -n "${SMTP_HOST:-}" ]]      && echo -e "  SMTP       : ${SMTP_HOST}:${SMTP_PORT} → ${SMTP_TO}"
    [[ -n "${ZABBIX_URL:-}" ]]     && echo -e "  Zabbix     : ${ZABBIX_URL}"
    sep

    echo -en "${BOLD}Bu cluster için devam edilsin mi? [e/H]${NC} "
    read -r CONFIRM
    if [[ "$CONFIRM" =~ ^[eEyY]$ ]]; then
        sep
        echo -e "${CYAN}Bootstrap başlatılıyor [${CLUSTER}]...${NC}"
        sep
        run_bootstrap_for_cluster "$CLUSTER" "$OCP_API" "$OCP_TOKEN" "${PROMETHEUS_URL:-}" "${PROMETHEUS_TOKEN:-}"
        ok "Cluster ${CLUSTER} tamamlandı."
    else
        echo -e "${YELLOW}Bu cluster atlandı.${NC}"
    fi

    sep
    echo -en "${BOLD}Başka cluster eklenecek mi? [e/H]${NC} "
    read -r DEVAM
    [[ "$DEVAM" =~ ^[eEyY]$ ]] || break
done

sep
echo -e "${GREEN}${BOLD}Bootstrap tamamlandı. ${CLUSTER_COUNT} cluster işlendi.${NC}"
sep
