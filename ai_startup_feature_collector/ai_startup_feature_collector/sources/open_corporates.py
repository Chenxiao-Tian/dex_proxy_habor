"""OpenCorporates filings extraction."""

from __future__ import annotations

from typing import Any, Dict

import requests

from .base import BaseDataSource, DataSourceResult


class OpenCorporatesDataSource(BaseDataSource):
    """Query OpenCorporates for filings and compliance signals."""

    API_URL = "https://api.opencorporates.com/v0.4/companies/search"

    def __init__(self) -> None:
        super().__init__(name="open_corporates")

    def fetch(self, startup: Dict[str, Any]) -> DataSourceResult:
        params = {"q": startup.get("name"), "order": "score"}
        response = requests.get(self.API_URL, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        metrics = self._normalize(payload)
        return DataSourceResult(raw=payload, metrics=metrics)

    @staticmethod
    def _normalize(payload: Dict[str, Any]) -> Dict[str, Any]:
        results = payload.get("results", {}).get("companies", [])
        if not results:
            return {"compliance_status": "Unknown", "latest_filings": []}
        company = results[0].get("company", {})
        filings = company.get("filings", [])
        compliance_status = "Compliant" if filings else "Unknown"
        return {
            "compliance_status": compliance_status,
            "latest_filings": [filing.get("title") for filing in filings[:5]],
        }
