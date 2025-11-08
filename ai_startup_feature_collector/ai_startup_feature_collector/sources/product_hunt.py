"""Product Hunt data source."""

from __future__ import annotations

import logging
from typing import Any, Dict

import requests

from .base import BaseDataSource, DataSourceResult

LOGGER = logging.getLogger(__name__)
API_URL = "https://api.producthunt.com/v2/api/graphql"


class ProductHuntDataSource(BaseDataSource):
    """Pull Product Hunt metadata for a startup."""

    def __init__(self, token: str) -> None:
        super().__init__(name="product_hunt")
        self.token = token

    def fetch(self, startup: Dict[str, Any]) -> DataSourceResult:
        query = """
        query ProductSearch($term: String!) {
          posts(search: $term, first: 5) {
            nodes {
              name
              tagline
              votesCount
              reviewsCount
              createdAt
              topics { edges { node { name } } }
            }
          }
        }
        """
        variables = {"term": startup.get("name")}
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        response = requests.post(API_URL, json={"query": query, "variables": variables}, headers=headers, timeout=30)
        response.raise_for_status()
        payload = response.json()
        nodes = payload.get("data", {}).get("posts", {}).get("nodes", [])
        metrics = self._to_metrics(nodes)
        return DataSourceResult(raw={"nodes": nodes}, metrics=metrics)

    @staticmethod
    def _to_metrics(nodes: Any) -> Dict[str, Any]:
        if not nodes:
            return {
                "industry_growth": "N/A",
                "product_votes": 0,
                "recent_launch": False,
                "topics": [],
            }
        node = nodes[0]
        return {
            "industry_growth": "Yes" if node.get("votesCount", 0) > 100 else "No",
            "product_votes": node.get("votesCount", 0),
            "recent_launch": node.get("createdAt"),
            "topics": [edge["node"]["name"] for edge in node.get("topics", {}).get("edges", [])],
        }
