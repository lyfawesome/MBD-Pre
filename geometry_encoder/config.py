"""Validated configuration for the automated geometry workflow."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkflowConfig:
    step_file: Path
    output: Path
    mode: str = "strict"
    threshold: float = 0.12
    size_tolerance: float = 0.03
    wl_iterations: int = 3
    drawexe: Path | None = None
    reuse_cache: bool = False
    skip_step_export: bool = False
    allow_unknown_geometry: bool = False
    precision_mode: str = "boolean"
    vertex_tolerance: float = 1e-5
    boolean_relative_tolerance: float = 1e-6
    export_volume_relative_tolerance: float = 1e-6
    precision_workers: int = 4

    def validate(self) -> None:
        if self.mode not in {"strict", "family"}:
            raise ValueError("mode must be strict or family")
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError("threshold must be in [0, 1]")
        if not 0.0 <= self.size_tolerance <= 1.0:
            raise ValueError("size_tolerance must be in [0, 1]")
        if not 1 <= self.wl_iterations <= 5:
            raise ValueError("wl_iterations must be in [1, 5]")
        if self.precision_mode not in {"boolean", "rigid", "off"}:
            raise ValueError("precision_mode must be boolean, rigid, or off")
        if (self.vertex_tolerance <= 0 or self.boolean_relative_tolerance <= 0
                or self.export_volume_relative_tolerance <= 0):
            raise ValueError("precision tolerances must be positive")
        if not 1 <= self.precision_workers <= 16:
            raise ValueError("precision_workers must be in [1, 16]")

    def to_dict(self) -> dict:
        result = asdict(self)
        result["step_file"] = str(self.step_file)
        result["output"] = str(self.output)
        result["drawexe"] = str(self.drawexe) if self.drawexe else None
        return result
