from __future__ import annotations

import uuid

from uk_jamaat_directory.storage.s3 import artifact_object_key


def test_artifact_object_key_uses_hash_prefix_and_extension() -> None:
    source_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    key = artifact_object_key(
        source_id=source_id,
        artifact_id=artifact_id,
        content_hash="abcdef0123456789" * 4,
        content_type="application/json",
    )
    assert key.startswith(f"artifacts/{source_id}/{artifact_id}/abcdef0123456789")
    assert key.endswith(".json")
