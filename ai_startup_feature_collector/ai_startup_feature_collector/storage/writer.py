"""Output writer abstractions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


class StorageWriter:
    """Simple interface for writing tabular data."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def write_parquet(self, name: str, dataframe: pd.DataFrame) -> Path:
        path = self.base_dir / f"{name}.parquet"
        dataframe.to_parquet(path, index=False)
        return path

    def write_json(self, name: str, records: Iterable[Any]) -> Path:
        path = self.base_dir / f"{name}.json"
        Path(path).write_text(json.dumps(list(records), indent=2, ensure_ascii=False), encoding="utf-8")
        return path
