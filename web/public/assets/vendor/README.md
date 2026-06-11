# Vendored third-party assets

These files are committed verbatim so the docs page has no CDN/runtime dependency
and works under a strict `script-src 'self'` CSP.

## scalar.standalone.js

- **Package:** `@scalar/api-reference`
- **Version:** 1.25.0
- **License:** MIT
- **Source:** https://cdn.jsdelivr.net/npm/@scalar/api-reference@1.25.0/dist/browser/standalone.js

To update, download the new pinned version, replace the file, bump the version
above, and verify `/docs/` renders with the production CSP (browser console clean).
