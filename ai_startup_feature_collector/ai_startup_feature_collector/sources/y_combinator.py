"""YC directory integration."""

from __future__ import annotations

from typing import Any, Dict

import requests

from .base import BaseDataSource, DataSourceResult


class YCombinatorDataSource(BaseDataSource):
    """Fetch data from YC directory for comparative analysis."""

    API_URL = "https://www.ycombinator.com/launches/export.json"

    def __init__(self) -> None:
        super().__init__(name="y_combinator")

    def fetch(self, startup: Dict[str, Any]) -> DataSourceResult:
        response = requests.get(self.API_URL, timeout=30)
        response.raise_for_status()
        payload = response.json()
        metrics = self._normalize(payload, startup)
        return DataSourceResult(raw=payload, metrics=metrics)

    @staticmethod
    def _normalize(payload: Dict[str, Any], startup: Dict[str, Any]) -> Dict[str, Any]:
        launches = payload.get("launches", [])
        relevant = [launch for launch in launches if launch.get("company_name", "").lower() in {name.lower() for name in startup.get("competitors", [])}]
        return {
            "competitor_count": len(relevant),
            "launch_activity": [launch.get("launch_title") for launch in relevant[:5]],
        }
