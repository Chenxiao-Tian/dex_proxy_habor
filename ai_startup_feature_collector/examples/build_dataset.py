"""Example script to run the full pipeline programmatically."""

from __future__ import annotations

from pathlib import Path

from ai_startup_feature_collector.cli import run_cli

if __name__ == "__main__":
    config_path = Path(__file__).resolve().parent.parent / "configs" / "demo.yml"
    run_cli(str(config_path))
