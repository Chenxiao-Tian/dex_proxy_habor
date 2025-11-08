"""LinkedIn scraping utilities for founder profiling."""

from __future__ import annotations

from typing import Any, Dict

import requests

from .base import BaseDataSource, DataSourceResult


class LinkedInDataSource(BaseDataSource):
    """Fetch founder profile data from LinkedIn public endpoints."""

    PROFILE_URL = "https://www.linkedin.com/voyager/api/identity/profiles/{slug}/profileView"

    def __init__(self, session_cookie: str) -> None:
        super().__init__(name="linkedin")
        self.session_cookie = session_cookie

    def fetch(self, startup: Dict[str, Any]) -> DataSourceResult:
        founder = startup.get("founder")
        slug = founder.get("linkedin_slug") if founder else None
        if not slug:
            raise ValueError("Founder linkedin_slug missing")
        headers = {
            "Csrf-Token": "ajax:1234567890",
            "Cookie": f"li_at={self.session_cookie}",
            "Accept": "application/json",
        }
        response = requests.get(self.PROFILE_URL.format(slug=slug), headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
        metrics = self._normalize(payload)
        return DataSourceResult(raw=payload, metrics=metrics)

    @staticmethod
    def _normalize(payload: Dict[str, Any]) -> Dict[str, Any]:
        experience = payload.get("positionView", {}).get("elements", [])
        education = payload.get("educationView", {}).get("elements", [])
        top_company = any(
            pos.get("companyName", "").lower() in {"google", "mckinsey", "openai", "meta"}
            for pos in experience
        )
        leadership = any(pos.get("title", "").lower() in {"ceo", "cto", "founder", "vp"} for pos in experience)
        highest_degree = "Unknown"
        institution = None
        if education:
            item = education[0]
            highest_degree = item.get("degreeName", "Unknown")
            institution = item.get("school", {}).get("name") if isinstance(item.get("school"), dict) else None
        return {
            "top_company_experience": top_company,
            "leadership_experience": leadership,
            "education_level": highest_degree,
            "education_institution": institution,
        }
