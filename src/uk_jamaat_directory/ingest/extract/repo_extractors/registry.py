from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass

from uk_jamaat_directory.ingest.extract.repo_extractors.contract import (
    BaseMosqueWebsiteExtractor,
)

_SCRIPT_PACKAGE = "uk_jamaat_directory.ingest.extract.repo_extractors.scripts"


@dataclass(frozen=True)
class RegisteredExtractor:
    module_name: str
    extractor: BaseMosqueWebsiteExtractor


def iter_script_modules() -> list[str]:
    package = importlib.import_module(_SCRIPT_PACKAGE)
    names: list[str] = []
    for module_info in pkgutil.iter_modules(package.__path__):
        if module_info.name.startswith("_"):
            continue
        names.append(f"{_SCRIPT_PACKAGE}.{module_info.name}")
    return names


def load_all_extractors() -> list[RegisteredExtractor]:
    registered: list[RegisteredExtractor] = []
    for module_name in iter_script_modules():
        module = importlib.import_module(module_name)
        extractor_cls = getattr(module, "Extractor", None)
        if extractor_cls is None:
            continue
        instance = extractor_cls()
        if not isinstance(instance, BaseMosqueWebsiteExtractor):
            continue
        registered.append(RegisteredExtractor(module_name=module_name, extractor=instance))
    return registered


def find_extractor_for_source(
    *,
    domain: str | None,
    mosque_name: str | None,
) -> list[RegisteredExtractor]:
    matches: list[RegisteredExtractor] = []
    for entry in load_all_extractors():
        if entry.extractor.source_match.matches(domain=domain, name=mosque_name):
            matches.append(entry)
    return matches
