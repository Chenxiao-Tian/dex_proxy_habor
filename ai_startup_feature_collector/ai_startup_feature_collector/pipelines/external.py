"""External knowledge aggregation pipeline."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd
from bs4 import BeautifulSoup

from ..models import ExternalKnowledgeFeatures
from ..sources.serp import SerpApiDataSource


class ExternalKnowledgePipeline:
    """Collect external market intelligence for startups."""

    def __init__(self, serp: SerpApiDataSource) -> None:
        self.serp = serp

    def run(self, startups: Iterable[Dict[str, Any]], output_dir: Path) -> pd.DataFrame:
        records: List[Dict[str, Any]] = []
        for startup in startups:
            enriched = self._collect(startup)
            features = self._to_features(startup, enriched)
            records.append(asdict(features))
            self._write_json(startup["name"], enriched, output_dir)
        return pd.DataFrame(records)

    def _collect(self, startup: Dict[str, Any]) -> Dict[str, Any]:
        query_payload = {"name": startup["name"], "query": f"{startup['name']} market size"}
        serp_results = self.serp.enrich(query_payload)
        return {
            "serp": serp_results.get("serpapi", {}),
            "parsed": self._parse_documents(serp_results.get("serpapi", {}).get("serp_snippets", [])),
        }

    def _parse_documents(self, snippets: List[str]) -> Dict[str, Any]:
        market_sizes = []
        cagr_values = []
        sentiment_scores = []
        for snippet in snippets:
            text = BeautifulSoup(snippet, "html.parser").get_text()
            market_sizes.extend(self._extract_numbers(text))
            if "cagr" in text.lower():
                cagr_values.extend(self._extract_numbers(text))
            sentiment_scores.append(len(text) % 3 - 1)
        return {
            "market_sizes": market_sizes,
            "cagr": cagr_values,
            "sentiment": sentiment_scores,
        }

    @staticmethod
    def _extract_numbers(text: str) -> List[float]:
        numbers: List[float] = []
        for token in text.split():
            token = token.replace("$", "").replace(",", "")
            try:
                numbers.append(float(token))
            except ValueError:
                continue
        return numbers

    def _to_features(self, startup: Dict[str, Any], enriched: Dict[str, Any]) -> ExternalKnowledgeFeatures:
        parsed = enriched.get("parsed", {})
        market_sizes = parsed.get("market_sizes", [])
        sentiment_scores = parsed.get("sentiment", [])
        return ExternalKnowledgeFeatures(
            startup_name=startup["name"],
            market_size_usd=max(market_sizes) if market_sizes else None,
            cagr=max(parsed.get("cagr", []), default=None),
            market_share="Fragmented" if len(market_sizes) > 3 else None,
            competitor_count=None,
            consumer_sentiment=sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else None,
            patent_count=None,
            compliance_signals=startup.get("compliance_signals", []),
            funding_diversity=startup.get("funding_diversity"),
            source_documents={"serp": enriched.get("serp", {}).get("serp_snippets", [])},
        )

    def _write_json(self, name: str, enriched: Dict[str, Any], output_dir: Path) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{name.replace(' ', '_').lower()}_external.json"
        path.write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")
