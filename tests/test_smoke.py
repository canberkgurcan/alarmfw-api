"""
alarmfw-api smoke tests
Gerçek DB/dosya olmadan ASGI transport üzerinden temel endpoint'leri kontrol eder.
Çalıştır: cd alarmfw-api && .venv/bin/pytest tests/test_smoke.py -v
"""
import os
import sys
import asyncio
from pathlib import Path

import httpx
import pytest

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
def app(_tmp_dirs):
    from main import app
    return app


async def _request_async(app, method: str, path: str, **kwargs):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.request(method, path, **kwargs)


def _request(app, method: str, path: str, **kwargs):
    return asyncio.run(_request_async(app, method, path, **kwargs))


def test_health(app):
    r = _request(app, "GET", "/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

# ── 2. Alarms — boş DB'de liste boş döner ─────────────────────────────────────
def test_alarms_list_empty(app):
    r = _request(app, "GET", "/api/alarms")
    assert r.status_code == 200
    assert r.json() == []


# ── 3. Alarm history — boş DB'de boş döner ────────────────────────────────────
def test_alarm_history_empty(app):
    r = _request(app, "GET", "/api/alarms/history")
    assert r.status_code == 200
    assert r.json() == []


# ── 4. Alarm metrics — DB yokken varsayılan sıfır değerler döner ──────────────
def test_alarm_metrics_schema(app):
    r = _request(app, "GET", "/api/alarms/metrics")
    assert r.status_code == 200
    data = r.json()
    assert "rules_evaluated_total" in data
    assert "evaluation_latency_ms_avg" in data
    assert isinstance(data["rules_evaluated_total"], int)


# ── 5. Config clusters — observe.yaml boş olduğunda boş liste ─────────────────
def test_config_clusters_empty(app):
    r = _request(app, "GET", "/api/config/clusters")
    assert r.status_code == 200
    assert r.json() == []


# ── 6. Maintenance policy — silences listesi döner ────────────────────────────
def test_maintenance_policy_schema(app):
    r = _request(app, "GET", "/api/policies/maintenance")
    assert r.status_code == 200
    data = r.json()
    assert "silences" in data
    assert isinstance(data["silences"], list)


# ── 7. Admin zabbix — olmayan namespace 404 vermeli ───────────────────────────
def test_admin_zabbix_send_missing_namespace(app):
    r = _request(app, "POST", "/api/admin/zabbix-send", json={"namespace": "missing", "type": "1"})
    assert r.status_code == 404


# ── 8. Cluster upsert + delete round-trip ─────────────────────────────────────
def test_cluster_upsert_and_delete(app):
    payload = {"ocp_api": "https://api.test.example.com:6443", "insecure": True}

    # Ekle
    r = _request(app, "PUT", "/api/config/clusters/smoke-cluster", json=payload)
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # Listede görünmeli
    r = _request(app, "GET", "/api/config/clusters")
    names = [c["name"] for c in r.json()]
    assert "smoke-cluster" in names

    # Sil
    r = _request(app, "DELETE", "/api/config/clusters/smoke-cluster")
    assert r.status_code == 200
    assert r.json()["ok"] is True

    # Listeden çıkmış olmalı
    r = _request(app, "GET", "/api/config/clusters")
    names = [c["name"] for c in r.json()]
    assert "smoke-cluster" not in names
