"""
alarmfw-api smoke tests
Gerçek DB/dosya olmadan FastAPI TestClient üzerinden temel endpoint'leri kontrol eder.
Çalıştır: cd alarmfw-api && .venv/bin/pytest tests/test_smoke.py -v
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# alarmfw-api kök dizinini path'e ekle
sys.path.insert(0, str(Path(__file__).parent.parent))

# Env'i test için ayarla — gerçek dosyalara dokunmadan çalışsın
@pytest.fixture(scope="session", autouse=True)
def _tmp_dirs(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("alarmfw_test")
    state = tmp / "state"
    config = tmp / "config"
    secrets = tmp / "secrets"
    for d in (state, config, secrets, config / "generated", config / "policies",
              config / "notifiers", tmp / "legacy" / "podhealthalarm" / "conf.d"):
        d.mkdir(parents=True, exist_ok=True)

    # Minimal observe.yaml
    (config / "observe.yaml").write_text("clusters: []\n")
    # Minimal maintenance.yaml
    (config / "policies" / "maintenance.yaml").write_text("silences: []\n")

    os.environ["ALARMFW_ROOT"]    = str(tmp)
    os.environ["ALARMFW_CONFIG"]  = str(config)
    os.environ["ALARMFW_STATE"]   = str(state)
    os.environ["ALARMFW_SECRETS"] = str(secrets)
    os.environ["ALARMFW_API_KEY"] = ""   # auth kapalı


@pytest.fixture(scope="session")
def client(_tmp_dirs):
    from main import app
    return TestClient(app)


# ── 1. Health ──────────────────────────────────────────────────────────────────

def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


# ── 2. Alarms — boş DB'de liste boş döner ─────────────────────────────────────

def test_alarms_list_empty(client):
    r = client.get("/api/alarms")
    assert r.status_code == 200
    assert r.json() == []


# ── 3. Alarm history — boş DB'de boş döner ────────────────────────────────────

def test_alarm_history_empty(client):
    r = client.get("/api/alarms/history")
    assert r.status_code == 200
    assert r.json() == []


# ── 4. Alarm metrics — DB yokken varsayılan sıfır değerler döner ──────────────

def test_alarm_metrics_schema(client):
    r = client.get("/api/alarms/metrics")
    assert r.status_code == 200
    data = r.json()
    assert "rules_evaluated_total" in data
    assert "evaluation_latency_ms_avg" in data
    assert isinstance(data["rules_evaluated_total"], int)


# ── 5. Config clusters — observe.yaml boş olduğunda boş liste ─────────────────

def test_config_clusters_empty(client):
    r = client.get("/api/config/clusters")
    assert r.status_code == 200
    assert r.json() == []


# ── 6. Maintenance policy — silences listesi döner ────────────────────────────

def test_maintenance_policy_schema(client):
    r = client.get("/api/policies/maintenance")
    assert r.status_code == 200
    data = r.json()
    assert "silences" in data
    assert isinstance(data["silences"], list)


# ── 7. Cluster upsert + delete round-trip ─────────────────────────────────────

def test_cluster_upsert_and_delete(client):
    payload = {"ocp_api": "https://api.test.example.com:6443", "insecure": True}

    # Ekle
    r = client.put("/api/config/clusters/smoke-cluster", json=payload)
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # Listede görünmeli
    r = client.get("/api/config/clusters")
    names = [c["name"] for c in r.json()]
    assert "smoke-cluster" in names

    # Sil
    r = client.delete("/api/config/clusters/smoke-cluster")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # Listeden çıkmış olmalı
    r = client.get("/api/config/clusters")
    names = [c["name"] for c in r.json()]
    assert "smoke-cluster" not in names
