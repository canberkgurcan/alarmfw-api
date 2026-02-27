import os
from pathlib import Path

# Alarmfw proje kök dizini (env ile override edilebilir)
ALARMFW_ROOT    = Path(os.getenv("ALARMFW_ROOT",    "/home/cnbrkgrcn/projects/alarmfw"))
ALARMFW_CONFIG  = Path(os.getenv("ALARMFW_CONFIG",  str(ALARMFW_ROOT / "config")))
ALARMFW_STATE   = Path(os.getenv("ALARMFW_STATE",   str(ALARMFW_ROOT / "state")))
ALARMFW_SECRETS = Path(os.getenv("ALARMFW_SECRETS", "/home/cnbrkgrcn/alarmfw-secrets"))
ALARMFW_ENV     = Path(os.getenv("ALARMFW_ENV",     str(ALARMFW_ROOT / ".env")))

# Docker compose komutu (runner için)
COMPOSE_CMD = os.getenv("COMPOSE_CMD", f"docker compose -f {ALARMFW_ROOT}/docker-compose.yml")
COMPOSE_RUN_CONFIG = os.getenv("COMPOSE_RUN_CONFIG", "/config/run_local.yaml")
