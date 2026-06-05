# Host-local compose overrides

Production deploys use `docker-compose.production.yml`. When a VPS already has
its own reverse proxy (shared Caddy, nginx, etc.) or other host-specific
networking, add **`docker-compose.local.yml`** in the repo root on that server
only. This file is gitignored — never commit operator paths, usernames,
container names, or site filenames.

Deploy scripts (`make deploy`, `scripts/deploy/*`) automatically append
`-f docker-compose.local.yml` when the file exists.

## External reverse proxy owns ports 80/443

Disable the bundled `caddy` service and attach the API to the proxy Docker
network. Adjust `aliases` and `web.name` to match the host.

```yaml
services:
  caddy:
    profiles: [bundled-caddy]

  api:
    networks:
      default: {}
      web:
        aliases:
          - directory-api

networks:
  web:
    external: true
    name: web
```

Install the TLS site block in the host proxy (not in this repo), then reload
that proxy. The bundled `deploy/caddy/Caddyfile` is for the default
single-app VPS path only.

## Host nginx terminates TLS

Publish the API on localhost for nginx to reach:

```yaml
services:
  caddy:
    profiles: [bundled-caddy]

  api:
    ports:
      - "127.0.0.1:8000:8000"
```

Use [deploy/nginx/directory.conf](../../deploy/nginx/directory.conf) as a
starting point on the host.

## Operator notes

Host-specific runbooks (exact proxy paths, reload commands, existing site
files) may live under `.local/` on the server. That directory is also
gitignored.
