from pathlib import Path


def test_backend_service_has_dedicated_identity_and_port() -> None:
    service = Path("infra/systemd/riri-emerald-api.service").read_text(encoding="utf-8")
    assert "User=riri-emerald" in service
    assert "WorkingDirectory=/opt/riri-emerald/current" in service
    assert "EnvironmentFile=/etc/riri-emerald/emerald.env" in service
    assert "--port 8010" in service
    assert "--workers 1" in service
    assert "WorkingDirectory=/opt/riri/" not in service
    assert "riri-api.service" not in service


def test_nginx_uses_only_emerald_hostname_and_upstream() -> None:
    nginx = Path("infra/nginx/api-emerald.albiagent.com.conf").read_text(encoding="utf-8")
    assert "server_name api-emerald.albiagent.com;" in nginx
    assert "proxy_pass http://127.0.0.1:8010;" in nginx
    assert "api-riri.albiagent.com" not in nginx
    assert "127.0.0.1:8000" not in nginx


def test_deployment_scripts_guard_existing_riri_paths_and_demo_lock() -> None:
    bootstrap = Path("infra/vps/bootstrap-emerald.sh").read_text(encoding="utf-8")
    deploy = Path("infra/vps/deploy-emerald.sh").read_text(encoding="utf-8")
    for source in (bootstrap, deploy):
        assert '"${project_root}" == "/opt/riri"' in source
        assert "/opt/riri-emerald" in source
    assert "EMERALD_ENVIRONMENT=demo" in deploy
    assert "EMERALD_ALLOW_REAL_TRADING=false" in deploy
    assert "EMERALD_PROBABILITY_MODEL_READY=false" in deploy


def test_vercel_configuration_keeps_secrets_server_side() -> None:
    env_example = Path("apps/dashboard/.env.example").read_text(encoding="utf-8")
    guide = Path("infra/vercel/README.md").read_text(encoding="utf-8")
    assert "EMERALD_API_BASE_URL=https://api-emerald.albiagent.com" in env_example
    assert "EMERALD_API_TOKEN=" in env_example
    assert "EMERALD_SESSION_SECRET=" in env_example
    assert "NEXT_PUBLIC_" not in env_example
    assert "riri-emerald-dashboard" in guide
    assert "emerald.albiagent.com" in guide
