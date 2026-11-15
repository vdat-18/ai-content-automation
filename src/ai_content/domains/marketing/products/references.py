"""Reference search profiles: one product type maps to Pinterest search keywords."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Everyday scenes that fit any product; a product type without references of its own uses them.
# Its search profile is added by a migration.
GENERAL_TYPE = "cảnh đời thường chung"


@dataclass
class ReferenceProfile:
    product_type: str
    keywords: list[str] = field(default_factory=list)
    status: str = "draft"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProfileGenerationError(RuntimeError):
    pass


