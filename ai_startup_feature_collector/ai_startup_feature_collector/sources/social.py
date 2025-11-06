"""Social media and review aggregators."""

from __future__ import annotations

from typing import Any, Dict

from .base import BaseDataSource, DataSourceResult


class SocialSentimentDataSource(BaseDataSource):
    """Compute sentiment score using public text snippets."""

    def __init__(self) -> None:
        super().__init__(name="social")

    def fetch(self, startup: Dict[str, Any]) -> DataSourceResult:
        snippets = startup.get("snippets", [])
        sentiment = self._sentiment(snippets)
        metrics = {
            "sentiment": "Positive" if sentiment > 0.2 else "Negative" if sentiment < -0.2 else "Neutral",
            "sentiment_score": sentiment,
        }
        return DataSourceResult(raw={"snippets": snippets}, metrics=metrics)

    @staticmethod
    def _sentiment(snippets: Any) -> float:
        if not snippets:
            return 0.0
        lexicon_positive = {"great", "love", "amazing", "positive", "growth"}
        lexicon_negative = {"bad", "hate", "slow", "negative", "concern"}
        total = 0
        for snippet in snippets:
            text = str(snippet).lower()
            total += sum(word in text for word in lexicon_positive)
            total -= sum(word in text for word in lexicon_negative)
        return total / len(snippets)
