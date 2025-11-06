"""Search and RAG connectors."""

from __future__ import annotations

from typing import Any, Dict, List

import requests

from .base import BaseDataSource, DataSourceResult


class SerpApiDataSource(BaseDataSource):
    """Fetch search results using the SerpAPI service."""

    API_URL = "https://serpapi.com/search.json"

    def __init__(self, api_key: str, engine: str = "google") -> None:
        super().__init__(name="serpapi")
        self.api_key = api_key
        self.engine = engine

    def fetch(self, startup: Dict[str, Any]) -> DataSourceResult:
        query = startup.get("query") or startup.get("name")
        params = {"q": query, "engine": self.engine, "api_key": self.api_key, "num": 5}
        response = requests.get(self.API_URL, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        metrics = self._normalize(payload)
        return DataSourceResult(raw=payload, metrics=metrics)

    @staticmethod
    def _normalize(payload: Dict[str, Any]) -> Dict[str, Any]:
        organic_results = payload.get("organic_results", [])
        summaries: List[str] = [res.get("snippet", "") for res in organic_results]
        return {"serp_snippets": summaries}
