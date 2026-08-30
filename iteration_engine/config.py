"""Configuration loading for the continuous iteration engine."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "continuous_iteration.toml"


@dataclass(frozen=True)
class IterationConfig:
    path: Path
    raw: dict[str, Any]

    @property
    def discovery(self) -> dict[str, Any]:
        return self.raw["discovery"]

    @property
    def cycle(self) -> dict[str, Any]:
        return self.raw["cycle"]

    @property
    def gates(self) -> dict[str, Any]:
        return self.raw["quality_gates"]

    @property
    def taxonomy(self) -> dict[str, list[str]]:
        return {
            key: list(value["keywords"])
            for key, value in self.raw["coverage"]["types"].items()
        }

    @property
    def thresholds(self) -> list[float]:
        return [float(value) for value in self.raw["optimization"]["thresholds"]]


def load_config(path: Path = DEFAULT_CONFIG) -> IterationConfig:
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    if raw.get("schema_version") != 1:
        raise ValueError(f"Unsupported iteration config schema: {raw.get('schema_version')!r}")
    required = {"discovery", "coverage", "cycle", "quality_gates", "optimization"}
    missing = required - raw.keys()
    if missing:
        raise ValueError(f"Missing iteration config sections: {sorted(missing)}")
    if not raw["coverage"].get("types"):
        raise ValueError("coverage.types must define at least one semantic type")
    return IterationConfig(path=path.resolve(), raw=raw)
