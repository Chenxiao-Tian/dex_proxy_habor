"""Pipeline for founder segmentation and Founder-Idea Fit."""

from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any, Dict, Iterable, List

import numpy as np
import pandas as pd

from ..models import FounderProfile
from ..sources.linkedin import LinkedInDataSource


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""

    if not a or not b:
        return 0.0
    vec_a = np.array(a)
    vec_b = np.array(b)
    denom = np.linalg.norm(vec_a) * np.linalg.norm(vec_b)
    return float(vec_a.dot(vec_b) / denom) if denom else 0.0


class FounderSegmentationPipeline:
    """Produces founder segmentation features."""

    def __init__(self, linkedin: LinkedInDataSource, embedding_client: "EmbeddingClient") -> None:
        self.linkedin = linkedin
        self.embedding_client = embedding_client

    def run(self, founders: Iterable[Dict[str, Any]]) -> pd.DataFrame:
        records: List[Dict[str, Any]] = []
        for founder in founders:
            payload = {"founder": founder}
            linkedin_metrics = self.linkedin.enrich(payload)["linkedin"]
            fit_score = self._founder_idea_fit(founder)
            profile = self._to_profile(founder, linkedin_metrics, fit_score)
            records.append(asdict(profile))
        return pd.DataFrame(records)

    def _to_profile(self, founder: Dict[str, Any], linkedin_metrics: Dict[str, Any], fit_score: float) -> FounderProfile:
        level = self._classify_founder_level(founder, linkedin_metrics)
        normalized = float(max(min(fit_score, 1.0), -1.0))
        return FounderProfile(
            identifier=founder["identifier"],
            name=founder.get("name", founder["identifier"]),
            founder_level=level,
            education_level=linkedin_metrics.get("education_level", "Unknown"),
            education_institution=linkedin_metrics.get("education_institution"),
            top_company_experience=linkedin_metrics.get("top_company_experience", False),
            leadership_experience=linkedin_metrics.get("leadership_experience", False),
            prior_exits=founder.get("prior_exits", 0),
            founder_idea_fit=fit_score,
            normalized_fifs=normalized,
        )

    def _founder_idea_fit(self, founder: Dict[str, Any]) -> float:
        resume_vector = self.embedding_client.embed_text(founder.get("bio", ""))
        idea_vector = self.embedding_client.embed_text(founder.get("startup_description", ""))
        return cosine_similarity(resume_vector, idea_vector)

    @staticmethod
    def _classify_founder_level(founder: Dict[str, Any], metrics: Dict[str, Any]) -> str:
        score = 0
        if metrics.get("top_company_experience"):
            score += 1
        if metrics.get("leadership_experience"):
            score += 1
        score += min(founder.get("prior_exits", 0), 2)
        degree = metrics.get("education_level", "").lower()
        if "phd" in degree or "mba" in degree:
            score += 1
        levels = {0: "L1", 1: "L2", 2: "L3", 3: "L4"}
        return levels.get(score, "L5")


class EmbeddingClient:
    """Minimal interface for embedding providers."""

    def __init__(self, provider: str, api_key: str) -> None:
        self.provider = provider
        self.api_key = api_key

    def embed_text(self, text: str) -> List[float]:
        """Dummy embedding implementation to be replaced with provider SDK."""

        if not text:
            return [0.0, 0.0, 0.0]
        # Simple hashing-based embedding fallback
        seeds = [sum(bytearray(text.encode("utf-8"))) % 101, len(text), text.count("AI")]
        norm = math.sqrt(sum(value ** 2 for value in seeds)) or 1.0
        return [value / norm for value in seeds]
