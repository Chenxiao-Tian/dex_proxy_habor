"""GitHub activity data source."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

import requests

from .base import BaseDataSource, DataSourceResult


class GitHubDataSource(BaseDataSource):
    """Fetch GitHub activity metrics for execution ability signals."""

    API_URL = "https://api.github.com/orgs/{org}/repos"

    def __init__(self, token: str | None = None) -> None:
        super().__init__(name="github")
        self.token = token

    def fetch(self, startup: Dict[str, Any]) -> DataSourceResult:
        org = startup.get("github_org") or startup.get("name", "").replace(" ", "")
        headers = {"Accept": "application/vnd.github+json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        response = requests.get(self.API_URL.format(org=org), headers=headers, timeout=30)
        response.raise_for_status()
        repos = response.json()
        metrics = self._normalize(repos)
        return DataSourceResult(raw={"repos": repos}, metrics=metrics)

    @staticmethod
    def _normalize(repos: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not repos:
            return {
                "execution_ability": "Unknown",
                "commit_frequency": 0,
                "active_repos": 0,
            }
        pushes = [repo.get("pushed_at") for repo in repos if repo.get("pushed_at")]
        active_repos = sum(
            1
            for push in pushes
            if (datetime.utcnow() - datetime.fromisoformat(push.replace("Z", "+00:00"))).days < 30
        )
        execution = "Excellent" if active_repos >= 3 else "Average" if active_repos else "Poor"
        return {
            "execution_ability": execution,
            "commit_frequency": len(pushes),
            "active_repos": active_repos,
        }
