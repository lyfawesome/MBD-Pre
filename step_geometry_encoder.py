#!/usr/bin/env python3
"""Command-line entry point for the automated STEP geometry workflow."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from geometry_encoder.config import WorkflowConfig
from geometry_encoder.workflow import GeometryWorkflow


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Automated, training-free STEP B-Rep grouping workflow")
    parser.add_argument("step_file", type=Path)
    parser.add_argument("--output", type=Path, default=Path("geometry_encoder_output"))
    parser.add_argument("--mode", choices=("strict", "family"), default="strict")
    parser.add_argument("--threshold", type=float, default=0.12)
    parser.add_argument("--size-tolerance", type=float, default=0.03)
    parser.add_argument("--wl-iterations", type=int, default=3)
    parser.add_argument("--drawexe", type=Path)
    parser.add_argument("--reuse-cache", action="store_true")
    parser.add_argument("--skip-step-export", action="store_true")
    parser.add_argument("--allow-unknown-geometry", action="store_true")
    parser.add_argument(
        "--precision-mode", choices=("boolean", "rigid", "off"), default="boolean",
        help="Independent post-cluster verification level",
    )
    parser.add_argument("--vertex-tolerance", type=float, default=1e-5)
    parser.add_argument("--boolean-relative-tolerance", type=float, default=1e-6)
    parser.add_argument(
        "--export-volume-relative-tolerance", type=float, default=1e-6,
        help="Maximum relative volume drift after grouped STEP export and re-import",
    )
    parser.add_argument("--precision-workers", type=int, default=4)
    args = parser.parse_args(argv)
    config = WorkflowConfig(
        step_file=args.step_file, output=args.output, mode=args.mode,
        threshold=args.threshold, size_tolerance=args.size_tolerance,
        wl_iterations=args.wl_iterations, drawexe=args.drawexe,
        reuse_cache=args.reuse_cache, skip_step_export=args.skip_step_export,
        allow_unknown_geometry=args.allow_unknown_geometry,
        precision_mode=args.precision_mode, vertex_tolerance=args.vertex_tolerance,
        boolean_relative_tolerance=args.boolean_relative_tolerance,
        export_volume_relative_tolerance=args.export_volume_relative_tolerance,
        precision_workers=args.precision_workers,
    )
    report = GeometryWorkflow(config).run()
    print(
        f"Processed {report['part_count']} solids: "
        f"{report['candidate_group_count']} candidate groups -> {report['group_count']} verified groups."
    )
    print(f"Precision mode={config.precision_mode}; results: {config.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
