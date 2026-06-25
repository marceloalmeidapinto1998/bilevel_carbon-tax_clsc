from __future__ import annotations

from dataclasses import dataclass
from typing import Any

@dataclass(slots=True)
class GeneratedInstance:
    name: str
    metadata: dict[str, Any]
    sets: dict[str, Any]
    parameters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "metadata": self.metadata,
            "sets": self.sets,
            "parameters": self.parameters,
        }
