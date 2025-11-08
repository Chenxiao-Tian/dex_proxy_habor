"""Base classes for data source integrations."""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional


@dataclass(slots=True)
class DataSourceResult:
    """Structured result returned by a data source."""

    raw: Dict[str, Any]
    metrics: Dict[str, Any]


class BaseDataSource(abc.ABC):
    """All data sources derive from this base class."""

    name: str

    def __init__(self, name: Optional[str] = None) -> None:
        self.name = name or self.__class__.__name__.replace("DataSource", "").lower()

    @abc.abstractmethod
    def fetch(self, startup: Dict[str, Any]) -> DataSourceResult:
        """Fetch raw data for a startup."""

    def enrich(self, startup: Dict[str, Any]) -> Dict[str, Any]:
        """Return normalized metrics for the pipeline."""

        result = self.fetch(startup)
        return {self.name: result.metrics}


class CompositeDataSource(BaseDataSource):
    """Combine multiple data sources into a single interface."""

    def __init__(self, sources: Iterable[BaseDataSource]):
        super().__init__(name="composite")
        self.sources = list(sources)

    def fetch(self, startup: Dict[str, Any]) -> DataSourceResult:
        raise NotImplementedError("CompositeDataSource delegates to enrich().")

    def enrich(self, startup: Dict[str, Any]) -> Dict[str, Any]:
        aggregated: Dict[str, Any] = {}
        for source in self.sources:
            aggregated.update(source.enrich(startup))
        return aggregated
