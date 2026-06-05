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
    ):
        assert key in text, key
