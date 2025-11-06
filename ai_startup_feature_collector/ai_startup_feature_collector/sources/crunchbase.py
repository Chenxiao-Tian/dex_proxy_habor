"""Crunchbase data source wrapper."""

from __future__ import annotations

from typing import Any, Dict

import requests

from .base import BaseDataSource, DataSourceResult


class CrunchbaseDataSource(BaseDataSource):
    """Fetch funding and investor metrics from Crunchbase."""

    API_URL = "https://api.crunchbase.com/api/v4/entities/organizations"

    def __init__(self, user_key: str) -> None:
        super().__init__(name="crunchbase")
        self.user_key = user_key

    def fetch(self, startup: Dict[str, Any]) -> DataSourceResult:
        params = {
            "user_key": self.user_key,
            "field_ids": "name,short_description,announced_on,rank,investors,funding_rounds",
            "query": startup.get("name"),
        }
        response = requests.get(self.API_URL, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        metrics = self._normalize(payload)
        return DataSourceResult(raw=payload, metrics=metrics)

    @staticmethod
    def _normalize(payload: Dict[str, Any]) -> Dict[str, Any]:
        entities = payload.get("entities", [])
        if not entities:
            return {
                "funding_level": "Unknown",
                "valuation_trend": "Unknown",
                "investor_quality": "Unknown",
            }
        entity = entities[0]
        total_funding = entity.get("properties", {}).get("total_funding_usd", 0)
        investors = entity.get("cards", {}).get("investors", {}).get("items", [])
        investor_quality = "Unknown"
        if investors:
            top_tier = any(
                inv.get("properties", {}).get("name", "").lower() in {"sequoia", "a16z", "benchmark"}
                for inv in investors
            )
            investor_quality = "Top-tier" if top_tier else "Recognized"
        return {
            "funding_level": "Above" if total_funding and total_funding > 5_000_000 else "Below",
            "valuation_trend": "Increased" if entity.get("properties", {}).get("rank", 0) < 5000 else "Stable",
            "investor_quality": investor_quality,
            "total_funding_usd": total_funding,
        }
