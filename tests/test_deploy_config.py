from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_docker_compose_vps_has_required_services() -> None:
    text = (ROOT / "docker-compose.vps.yml").read_text()
    for service in (
        "api:",
        "worker:",
        "beat:",
        "postgres:",
        "redis:",
        "minio:",
        "caddy:",
    ):
        assert service in text, service


def test_docker_compose_vps_api_not_published_on_host() -> None:
    text = (ROOT / "docker-compose.vps.yml").read_text()
    api_block = text.split("  api:", 1)[1].split("\n\n", 1)[0]
    assert "ports:" not in api_block
    assert "expose:" in api_block


def test_docker_compose_vps_pins_minio_image() -> None:
    text = (ROOT / "docker-compose.vps.yml").read_text()
    assert "minio/minio:latest" not in text
    assert "minio/minio:RELEASE." in text


def test_docker_compose_vps_restricts_forwarded_allow_ips() -> None:
    text = (ROOT / "docker-compose.vps.yml").read_text()
    assert "--forwarded-allow-ips=*" not in text
    assert "--forwarded-allow-ips=10.0.0.0/8" in text


def test_caddyfile_proxies_exports_to_minio() -> None:
    text = (ROOT / "deploy" / "caddy" / "Caddyfile").read_text()
    assert "handle_path /exports/*" in text
    assert "reverse_proxy minio:9000" in text
    assert "{$S3_BUCKET}" in text


def test_deploy_scripts_exist_and_are_executable() -> None:
    script_dir = ROOT / "scripts" / "deploy"
    for name in (
        "migrate.sh",
        "backup-postgres.sh",
        "backup-minio.sh",
        "smoke-test.sh",
        "deploy.sh",
    ):
        path = script_dir / name
        assert path.is_file(), name
        assert path.stat().st_mode & 0o111, f"{name} should be executable"


def test_smoke_test_asserts_readiness_response_fields() -> None:
    text = (ROOT / "scripts" / "deploy" / "smoke-test.sh").read_text()
    assert '"status":"ok"' in text
    assert '"database":"ok"' in text
    assert '"ready"' not in text


def test_deploy_script_order_matches_checklist() -> None:
    deploy = (ROOT / "scripts" / "deploy" / "deploy.sh").read_text()
    backup_idx = deploy.index("backup-postgres.sh")
    build_idx = deploy.index("build api worker beat caddy")
    migrate_idx = deploy.index("migrate.sh")
    smoke_idx = deploy.index("smoke-test.sh")
    assert backup_idx < build_idx < migrate_idx < smoke_idx
    assert "health_ok" in deploy
    assert "SKIP_BACKUP" in deploy and "WARNING" in deploy


def test_vps_env_example_documents_required_keys() -> None:
    text = (ROOT / ".env.vps.example").read_text()
    for key in (
        "PUBLIC_DOMAIN",
        "ACME_EMAIL",
        "POSTGRES_PASSWORD",
        "ADMIN_API_KEY",
        "DATABASE_URL",
        "S3_BUCKET",
        "TRUST_PROXY_HEADERS",
        "EXPORT_BASE_URL",
        "EXPORT_ENABLED",
    ):
        assert key in text, key


def test_vps_env_export_base_url_is_public_origin_not_doubled_prefix() -> None:
    text = (ROOT / ".env.vps.example").read_text()
    for line in text.splitlines():
        if line.startswith("EXPORT_BASE_URL="):
            value = line.split("=", 1)[1].strip()
            assert not value.endswith("/exports"), (
                "EXPORT_BASE_URL should be the public origin; "
                "export_s3_prefix adds /exports/... in generated URLs"
            )
            break
    else:
        raise AssertionError("EXPORT_BASE_URL not found in .env.vps.example")


def test_nginx_override_publishes_api_on_localhost() -> None:
    text = (ROOT / "docker-compose.vps.nginx.yml").read_text()
    assert "127.0.0.1:8000:8000" in text
