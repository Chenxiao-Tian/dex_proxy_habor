"""Basic tests for configuration parsing."""

from __future__ import annotations

from pathlib import Path

from ai_startup_feature_collector.config import CollectorSettings


def test_config_round_trip(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
project:
  name: test
  output_dir: outputs
startups:
  - name: Example
    website: https://example.com
    description: Example startup
founders:
  alice:
    name: Alice
    linkedin: https://www.linkedin.com/in/alice
    bio: Founder bio
pipelines:
  fundamentals:
    enabled: true
  founders:
    enabled: false
        """,
        encoding="utf-8",
    )

    settings = CollectorSettings.from_file(config_path)
    assert settings.project.name == "test"
    assert settings.startups[0].name == "Example"
    assert settings.pipeline_enabled("fundamentals") is True
    assert settings.pipeline_enabled("founders") is False
