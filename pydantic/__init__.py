"""Extremely small pydantic-compatible facade for local testing."""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable


ConfigDict = dict


def Field(default: Any = ..., **kwargs: Any) -> Any:  # pragma: no cover - metadata ignored
    return default


class BaseModel:
    def __init__(self, **data: Any) -> None:
        self.__dict__.update(data)

    def model_dump(self, mode: str = "python") -> Dict[str, Any]:
        return dict(self.__dict__)

    def model_dump_json(self) -> str:  # pragma: no cover - convenience
        return json.dumps(self.model_dump())

    @classmethod
    def model_validate(cls, data: Dict[str, Any]) -> "BaseModel":  # pragma: no cover - compatibility
        return cls(**data)


class RootModel(BaseModel):
    def __init__(self, root: Any) -> None:
        super().__init__(root=root)

    @property
    def root(self) -> Any:  # pragma: no cover - convenience
        return self.__dict__.get("root")


__all__ = ["BaseModel", "ConfigDict", "Field", "RootModel"]
