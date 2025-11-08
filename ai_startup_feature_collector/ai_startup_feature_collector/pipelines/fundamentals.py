"""Pipeline for generating startup fundamentals."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Iterable, List

import pandas as pd

from ..models import StartupFundamentalFeatures
from ..sources.base import BaseDataSource, CompositeDataSource
from ..sources.crunchbase import CrunchbaseDataSource
from ..sources.github import GitHubDataSource
from ..sources.open_corporates import OpenCorporatesDataSource
from ..sources.product_hunt import ProductHuntDataSource
from ..sources.social import SocialSentimentDataSource
from ..sources.y_combinator import YCombinatorDataSource


def build_fundamental_sources(params: Dict[str, Any]) -> Iterable[BaseDataSource]:
    """Factory constructing data sources based on params."""

    sources: List[BaseDataSource] = []
    if token := params.get("product_hunt_token"):
        sources.append(ProductHuntDataSource(token=token))
    if key := params.get("crunchbase_user_key"):
        sources.append(CrunchbaseDataSource(user_key=key))
    if params.get("use_open_corporates", True):
        sources.append(OpenCorporatesDataSource())
    if params.get("use_github", True):
        sources.append(GitHubDataSource(token=params.get("github_token")))
    if params.get("use_social", True):
        sources.append(SocialSentimentDataSource())
    if params.get("use_yc", True):
        sources.append(YCombinatorDataSource())
    return sources


class StartupFundamentalsPipeline:
    """Generate SSFF categorical features for each startup."""

    def __init__(self, sources: Iterable[BaseDataSource]) -> None:
        self.source = CompositeDataSource(sources)

    def run(self, startups: Iterable[Dict[str, Any]]) -> pd.DataFrame:
        records: List[Dict[str, Any]] = []
        for startup in startups:
            enriched = self.source.enrich(startup)
            record = self._to_features(startup, enriched)
            records.append(asdict(record))
        return pd.DataFrame(records)

    def _to_features(self, startup: Dict[str, Any], enriched: Dict[str, Any]) -> StartupFundamentalFeatures:
        ph = enriched.get("product_hunt", {})
        cb = enriched.get("crunchbase", {})
        gh = enriched.get("github", {})
        oc = enriched.get("open_corporates", {})
        social = enriched.get("social", {})
        yc = enriched.get("y_combinator", {})
        return StartupFundamentalFeatures(
            startup_name=startup["name"],
            industry_growth=ph.get("industry_growth", "N/A"),
            market_size=cb.get("market_size", "Medium"),
            relative_growth_speed="Faster" if gh.get("active_repos", 0) > 2 else "Same",
            market_adaptability="High" if ph.get("recent_launch") else "Medium",
            execution_ability=gh.get("execution_ability", "Unknown"),
            funding_level=cb.get("funding_level", "Unknown"),
            valuation_trend=cb.get("valuation_trend", "Unknown"),
            investor_quality=cb.get("investor_quality", "Unknown"),
            pmf_signal="Strong" if ph.get("product_votes", 0) > 200 else "Moderate",
            innovation_mentions="Often" if "AI" in startup.get("description", "") else "Sometimes",
            frontier_tech_usage="Emphasized" if "foundation" in startup.get("description", "").lower() else "Mentioned",
            timing_window="JustRight" if oc.get("compliance_status") == "Compliant" else "TooEarly",
            sentiment=social.get("sentiment", "Neutral"),
            external_reviews="Positive" if social.get("sentiment_score", 0) > 0 else "Mixed",
        )
