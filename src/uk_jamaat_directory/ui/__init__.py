"""Server-rendered dashboard and admin UI (Jinja2 + HTMX).

This package is the HTML surface of the application. The JSON API under
``/v1`` stays a pure machine contract; all human-facing pages live here and
call the existing ``services`` layer directly rather than round-tripping JSON.
"""
