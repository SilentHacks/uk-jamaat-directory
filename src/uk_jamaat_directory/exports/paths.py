from __future__ import annotations


def export_prefix(version: str, *, base_prefix: str = "exports") -> str:
    return f"{base_prefix}/{version}"


def export_object_key(version: str, filename: str, *, base_prefix: str = "exports") -> str:
    return f"{export_prefix(version, base_prefix=base_prefix)}/{filename}"


def export_public_url(
    version: str,
    filename: str,
    *,
    base_url: str,
    base_prefix: str = "exports",
) -> str:
    base = base_url.rstrip("/")
    return f"{base}/{base_prefix}/{version}/{filename}"
