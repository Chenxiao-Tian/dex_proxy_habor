"""Configuration helpers for the AI Startup Feature Collector."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:  # pragma: no cover - optional dependency
    import yaml  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    yaml = None


@dataclass(slots=True)
class PipelineToggle:
    """Enable/disable a pipeline and hold arbitrary parameters."""

    enabled: bool = True
    params: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: Dict[str, Any]) -> "PipelineToggle":
        params = dict(data)
        enabled = bool(params.pop("enabled", True))
        return cls(enabled=enabled, params=params)


@dataclass(slots=True)
class StartupConfig:
    """Configuration for a single startup target."""

    name: str
    website: str
    description: str
    tags: List[str] = field(default_factory=list)
    competitors: List[str] = field(default_factory=list)
    founders: List[str] = field(default_factory=list)


@dataclass(slots=True)
class FounderConfig:
    """Configuration for a founder profile."""

    identifier: str
    name: str
    linkedin: Optional[str]
    bio: str


@dataclass(slots=True)
class ProjectConfig:
    """Metadata about a feature collection project."""

    name: str
    output_dir: Path


@dataclass(slots=True)
class CollectorSettings:
    """Container for all CLI settings."""

    project: ProjectConfig
    startups: List[StartupConfig]
    founders: Dict[str, FounderConfig]
    pipelines: Dict[str, PipelineToggle]

    @classmethod
    def from_file(cls, path: Path | str) -> "CollectorSettings":
        text = Path(path).read_text(encoding="utf-8")
        data = load_config_text(text)
        project_data = data.get("project", {})
        project = ProjectConfig(
            name=project_data.get("name", "ai_startup_project"),
            output_dir=Path(project_data.get("output_dir", "outputs")),
        )

        startups = [
            StartupConfig(
                name=item["name"],
                website=item.get("website", ""),
                description=item.get("description", ""),
                tags=item.get("tags", []) or [],
                competitors=item.get("competitors", []) or [],
                founders=item.get("founders", []) or [],
            )
            for item in data.get("startups", [])
        ]

        founders = {
            key: FounderConfig(
                identifier=key,
                name=value.get("name", key),
                linkedin=value.get("linkedin"),
                bio=value.get("bio", ""),
            )
            for key, value in (data.get("founders", {}) or {}).items()
        }

        pipelines = {
            key: PipelineToggle.from_mapping(value or {})
            for key, value in (data.get("pipelines", {}) or {}).items()
        }

        return cls(
            project=project,
            startups=startups,
            founders=founders,
            pipelines=pipelines,
        )

    def pipeline_enabled(self, name: str) -> bool:
        toggle = self.pipelines.get(name)
        return bool(toggle.enabled) if toggle else False

    def pipeline_params(self, name: str) -> Dict[str, Any]:
        toggle = self.pipelines.get(name)
        return dict(toggle.params) if toggle else {}


def ensure_output_dir(project: ProjectConfig) -> Path:
    """Create the output directory if it does not exist."""

    project.output_dir.mkdir(parents=True, exist_ok=True)
    return project.output_dir


def load_config_text(text: str) -> Dict[str, Any]:
    """Load configuration data with optional YAML dependency."""

    if yaml is not None:  # pragma: no branch - prefer full YAML parser when available
        return yaml.safe_load(text)  # type: ignore[no-any-return]
    return _simple_yaml_load(text)


def _parse_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "yes"}:
        return True
    if lowered in {"false", "no"}:
        return False
    if lowered in {"null", "none"}:
        return None
    if (value.startswith("\"") and value.endswith("\"")) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _simple_yaml_load(text: str) -> Dict[str, Any]:
    """Parse a very small subset of YAML used in the configs."""

    from dataclasses import dataclass

    @dataclass
    class Context:
        indent: int
        container: Any
        parent: Any | None
        key: str | None
        pending: bool = False

    root: Dict[str, Any] = {}
    stack: List[Context] = [Context(indent=-1, container=root, parent=None, key=None, pending=False)]

    lines = text.splitlines()
    for raw_line in lines:
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()

        while len(stack) > 1 and indent <= stack[-1].indent:
            stack.pop()

        ctx = stack[-1]
        container = ctx.container

        if stripped.startswith("- "):
            if ctx.pending and isinstance(container, dict):
                new_list: List[Any] = []
                assert ctx.parent is not None and ctx.key is not None
                ctx.parent[ctx.key] = new_list
                ctx.container = new_list
                ctx.pending = False
                container = new_list
            if not isinstance(container, list):
                raise ValueError("List item without list context")

            item_value = stripped[2:].strip()
            if not item_value:
                new_dict: Dict[str, Any] = {}
                container.append(new_dict)
                stack.append(Context(indent=indent, container=new_dict, parent=container, key=None, pending=False))
            elif ":" in item_value:
                key, val = item_value.split(":", 1)
                key = key.strip()
                val = val.strip()
                new_dict: Dict[str, Any] = {}
                container.append(new_dict)
                if val:
                    new_dict[key] = _parse_scalar(val)
                    stack.append(Context(indent=indent, container=new_dict, parent=container, key=None, pending=False))
                else:
                    stack.append(Context(indent=indent, container=new_dict, parent=container, key=key, pending=True))
            else:
                container.append(_parse_scalar(item_value))
            continue

        key, _, value_part = stripped.partition(":")
        key = key.strip()
        value_part = value_part.strip()

        if isinstance(container, list):
            raise ValueError("Unexpected mapping inside list without '-'")

        if value_part:
            container[key] = _parse_scalar(value_part)
            ctx.key = key
            ctx.pending = False
        else:
            placeholder: Dict[str, Any] = {}
            container[key] = placeholder
            ctx.key = key
            new_ctx = Context(indent=indent, container=placeholder, parent=container, key=key, pending=True)
            stack.append(new_ctx)

    return root
