"""Dataclasses describing features exported by the pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass(slots=True)
class StartupFundamentalFeatures:
    """Categorical features used in the prediction block."""

    startup_name: str
    industry_growth: str
    market_size: str
    relative_growth_speed: str
    market_adaptability: str
    execution_ability: str
    funding_level: str
    valuation_trend: str
    investor_quality: str
    pmf_signal: str
    innovation_mentions: str
    frontier_tech_usage: str
    timing_window: str
    sentiment: str
    external_reviews: str
    collected_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True)
class FounderProfile:
    """Information about a founder."""

    identifier: str
    name: str
    founder_level: str
    education_level: str
    education_institution: Optional[str]
    top_company_experience: bool
    leadership_experience: bool
    prior_exits: int
    founder_idea_fit: float
    normalized_fifs: float


@dataclass(slots=True)
class ExternalKnowledgeFeatures:
    """Structured external knowledge attributes."""

    startup_name: str
    market_size_usd: Optional[float]
    cagr: Optional[float]
    market_share: Optional[str]
    competitor_count: Optional[int]
    consumer_sentiment: Optional[float]
    patent_count: Optional[int]
    compliance_signals: List[str] = field(default_factory=list)
    funding_diversity: Optional[str] = None
    source_documents: Dict[str, str] = field(default_factory=dict)
    collected_at: datetime = field(default_factory=datetime.utcnow)
