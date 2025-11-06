"""Command line entry point."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List
from dotenv import load_dotenv

from .config import CollectorSettings, ensure_output_dir
from .pipelines.external import ExternalKnowledgePipeline
from .pipelines.founders import EmbeddingClient, FounderSegmentationPipeline
from .pipelines.fundamentals import StartupFundamentalsPipeline, build_fundamental_sources
from .sources.linkedin import LinkedInDataSource
from .sources.serp import SerpApiDataSource


def load_founders(settings: CollectorSettings) -> List[Dict[str, Any]]:
    founders: List[Dict[str, Any]] = []
    for identifier, config in settings.founders.items():
        founders.append(
            {
                "identifier": identifier,
                "name": config.name,
                "linkedin_slug": config.linkedin.split("/")[-1] if config.linkedin else identifier,
                "bio": config.bio,
                "startup_description": _startup_description(settings, identifier),
                "prior_exits": 0,
            }
        )
    return founders


def _startup_description(settings: CollectorSettings, identifier: str) -> str:
    for startup in settings.startups:
        if identifier in startup.founders:
            return startup.description
    return ""


def run_cli(config_path: str) -> None:
    load_dotenv()
    settings = CollectorSettings.from_file(config_path)
    output_dir = ensure_output_dir(settings.project)

    if settings.pipeline_enabled("fundamentals"):
        params = settings.pipeline_params("fundamentals")
        sources = build_fundamental_sources(params)
        fundamentals = StartupFundamentalsPipeline(sources).run([startup.__dict__ for startup in settings.startups])
        fundamentals.to_parquet(output_dir / "features_ssff.parquet", index=False)

    if settings.pipeline_enabled("founders"):
        params = settings.pipeline_params("founders")
        linkedin = LinkedInDataSource(session_cookie=params.get("linkedin_session", ""))
        embedding_client = EmbeddingClient(provider=params.get("embedding_model", "openai"), api_key=params.get("openai_api_key", ""))
        founders = load_founders(settings)
        founders_df = FounderSegmentationPipeline(linkedin, embedding_client).run(founders)
        founders_df.to_parquet(output_dir / "features_founder.parquet", index=False)

    if settings.pipeline_enabled("external"):
        params = settings.pipeline_params("external")
        serp = SerpApiDataSource(api_key=params.get("serp_api_key", ""), engine=params.get("serp_engine", "google"))
        external_df = ExternalKnowledgePipeline(serp).run([startup.__dict__ for startup in settings.startups], output_dir)
        external_df.to_json(output_dir / "features_ssff_ext.json", orient="records", indent=2, force_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect AI startup features")
    parser.add_argument("--config", type=str, required=True, help="Path to YAML configuration file")
    args = parser.parse_args()
    run_cli(args.config)


if __name__ == "__main__":
    main()
