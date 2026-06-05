from __future__ import annotations

import hashlib


def sha256_digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def sha256_prefixed(body: bytes) -> str:
    return f"sha256:{sha256_digest(body)}"
