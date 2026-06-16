from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_docker_compose_production_has_required_services() -> None:
    text = (ROOT / "docker-compose.production.yml").read_text()
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


def test_docker_compose_production_api_not_published_on_host() -> None:
    text = (ROOT / "docker-compose.production.yml").read_text()
    api_block = text.split("  api:", 1)[1].split("\n\n", 1)[0]
    assert "ports:" not in api_block
    assert "expose:" in api_block


def test_docker_compose_production_pins_minio_image() -> None:
    text = (ROOT / "docker-compose.production.yml").read_text()
    assert "minio/minio:latest" not in text
    assert "minio/minio:RELEASE." in text


def test_docker_compose_production_restricts_forwarded_allow_ips() -> None:
    text = (ROOT / "docker-compose.production.yml").read_text()
    assert "--forwarded-allow-ips=*" not in text
    assert "--forwarded-allow-ips=10.0.0.0/8" in text


def test_caddyfile_proxies_exports_to_minio() -> None:
    text = (ROOT / "deploy" / "caddy" / "Caddyfile").read_text()
    assert "handle_path /exports/*" in text
    assert "reverse_proxy minio:9000" in text
    assert "{$S3_BUCKET}" in text


def test_caddyfile_serves_static_site_with_hardening() -> None:
    text = (ROOT / "deploy" / "caddy" / "Caddyfile").read_text()
    assert "encode zstd gzip" in text
    assert "root * /srv/www" in text
    assert "file_server" in text
    assert "handle_errors" in text
    assert "Strict-Transport-Security" in text
    assert "X-Content-Type-Options" in text
    assert "Content-Security-Policy" in text
    assert "request_body" in text
    # The API is routed explicitly so unknown paths fall through to the static 404.
    assert "path /v1/*" in text


def test_caddyfile_does_not_expose_internal_docs_publicly() -> None:
    text = (ROOT / "deploy" / "caddy" / "Caddyfile").read_text()
    assert "/internal/*" not in text


def test_caddyfile_proxies_app_routes_and_serves_static_assets() -> None:
    text = (ROOT / "deploy" / "caddy" / "Caddyfile").read_text()
    # SSR dashboard/admin pages are proxied to the API…
    assert "reverse_proxy api:8000" in text
    # …while first-party static assets keep being served by Caddy.
    assert "/assets/*" in text


def test_smoke_test_checks_admin_login_surface() -> None:
    text = (ROOT / "scripts" / "deploy" / "smoke-test.sh").read_text()
    assert "/admin/login" in text


def test_env_example_documents_session_secret_key() -> None:
    text = (ROOT / ".env.example").read_text()
    assert "SESSION_SECRET_KEY" in text


def test_production_compose_mounts_static_site() -> None:
    text = (ROOT / "docker-compose.production.yml").read_text()
    assert "./web/public:/srv/www:ro" in text


def test_static_site_has_required_pages() -> None:
    web = ROOT / "web" / "public"
    for rel in (
        "index.html",
        "docs/index.html",
        "data/index.html",
        "404.html",
        "robots.txt",
        "sitemap.xml",
        "favicon.svg",
        "assets/site.css",
        "assets/data.js",
        "assets/vendor/scalar.standalone.js",
    ):
        assert (web / rel).is_file(), rel


def test_docs_page_points_at_public_openapi_spec() -> None:
    text = (ROOT / "web" / "public" / "docs" / "index.html").read_text()
    assert 'data-url="/v1/openapi.json"' in text
    assert "/assets/vendor/scalar.standalone.js" in text


def test_deploy_scripts_exist_and_are_executable() -> None:
    script_dir = ROOT / "scripts" / "deploy"
    for name in (
        "compose-args.sh",
        "migrate.sh",
        "backup-postgres.sh",
        "backup-minio.sh",
        "smoke-test.sh",
        "deploy.sh",
    ):
        path = script_dir / name
        assert path.is_file(), name
        assert path.stat().st_mode & 0o111, f"{name} should be executable"


def test_compose_args_includes_local_override_when_present() -> None:
    text = (ROOT / "scripts" / "deploy" / "compose-args.sh").read_text()
    assert "docker-compose.production.yml" in text
    assert "docker-compose.local.yml" in text


def test_smoke_test_asserts_readiness_response_fields() -> None:
    text = (ROOT / "scripts" / "deploy" / "smoke-test.sh").read_text()
    assert '"status":"ok"' in text
    assert '"database":"ok"' in text
    assert '"ready"' not in text


def test_smoke_test_checks_public_surface() -> None:
    text = (ROOT / "scripts" / "deploy" / "smoke-test.sh").read_text()
    # No stale compose-file default that points at a non-existent file.
    assert "docker-compose.vps.yml" not in text
    assert "/v1/openapi.json" in text
    assert "<html" in text
    assert "strict-transport-security" in text


def test_deploy_script_order_matches_checklist() -> None:
    deploy = (ROOT / "scripts" / "deploy" / "deploy.sh").read_text()
    backup_idx = deploy.index("backup-postgres.sh")
    pull_idx = deploy.index("pull api worker beat")
    migrate_idx = deploy.index("migrate.sh")
    smoke_idx = deploy.index("smoke-test.sh")
    assert backup_idx < pull_idx < migrate_idx < smoke_idx
    assert "health_ok" in deploy
    assert "SKIP_BACKUP" in deploy and "WARNING" in deploy
    assert "compose-args.sh" in deploy


def test_deploy_script_pulls_image_and_does_not_build() -> None:
    deploy = (ROOT / "scripts" / "deploy" / "deploy.sh").read_text()
    assert "IMAGE_TAG" in deploy
    assert "build " not in deploy


def test_production_compose_uses_ghcr_image_not_build() -> None:
    text = (ROOT / "docker-compose.production.yml").read_text()
    assert "ghcr.io/silenthacks/uk-jamaat-directory" in text
    assert "${IMAGE_TAG:-latest}" in text
    assert "build: ." not in text


def test_production_compose_has_log_rotation_and_worker_healthcheck() -> None:
    text = (ROOT / "docker-compose.production.yml").read_text()
    assert "max-size" in text and "max-file" in text
    assert "inspect ping" in text  # worker healthcheck is no longer disabled
    assert "/data/celerybeat-schedule" in text  # beat schedule persisted off /tmp


def test_env_example_documents_production_keys() -> None:
    text = (ROOT / ".env.example").read_text()
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
        "MUSLIMSINBRITAIN_ENABLED",
    ):
        assert key in text, key


def test_env_example_export_base_url_is_public_origin_not_doubled_prefix() -> None:
    text = (ROOT / ".env.example").read_text()
    for line in text.splitlines():
        if line.startswith("# EXPORT_BASE_URL=https://"):
            value = line.split("=", 1)[1].strip()
            assert not value.endswith("/exports"), (
                "EXPORT_BASE_URL should be the public origin; "
                "export_s3_prefix adds /exports/... in generated URLs"
            )
            break
    else:
        raise AssertionError("commented production EXPORT_BASE_URL not found in .env.example")


def test_local_overrides_doc_exists() -> None:
    path = ROOT / "docs" / "deploy" / "local-overrides.md"
    assert path.is_file()
    text = path.read_text()
    assert "docker-compose.local.yml" in text
    assert "bundled-caddy" in text
