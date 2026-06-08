from __future__ import annotations

from uk_jamaat_directory.ingest.authoring.agent import (
    extract_python_block,
)


def test_extract_python_block_finds_python_fence() -> None:
    text = (
        "Here is the script:\n"
        "```python\n"
        "from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (\n"
        "    BaseMosqueWebsiteExtractor,\n"
        ")\n"
        "```\n"
        "Done."
    )
    block = extract_python_block(text)
    assert block is not None
    assert block.startswith("from uk_jamaat_directory")
    assert block.rstrip().endswith(")")


def test_extract_python_block_finds_py_fence() -> None:
    text = "```py\nprint('hi')\n```"
    assert extract_python_block(text) == "print('hi')"


def test_extract_python_block_returns_none_when_no_fence() -> None:
    assert extract_python_block("nothing here") is None


def test_extract_python_block_handles_unterminated_fence() -> None:
    text = "```python\nclass Extractor: pass"
    block = extract_python_block(text)
    assert block == "class Extractor: pass"
