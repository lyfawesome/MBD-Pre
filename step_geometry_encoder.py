#!/usr/bin/env python3
"""Training-free STEP B-Rep similarity grouping CLI."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Iterable

from geometry_encoder.occt_backend import ExactProperties, export_groups, find_drawexe, inspect_and_normalize, validate_group_steps
from geometry_encoder.similarity import PartFeatures, density_complete_link, distance_matrix, verify_assignments
from geometry_encoder.step_graph import describe_normalized_step


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


CACHE_SCHEMA = 3


def _normalized_metadata(cache_dir: Path) -> list[dict]:
    return [
        {"file": path.name, "bytes": path.stat().st_size, "sha256": _sha256(path)}
        for path in sorted(cache_dir.glob("part_*.step"))
    ]


def _load_or_extract(source: Path, cache_dir: Path, manifest: Path, drawexe: Path, reuse: bool) -> tuple[list[ExactProperties], str]:
    source_hash = _sha256(source)
    if reuse and manifest.is_file():
        cached = json.loads(manifest.read_text(encoding="utf-8"))
        metadata = _normalized_metadata(cache_dir)
        backend = {"path": str(drawexe), "bytes": drawexe.stat().st_size, "mtime_ns": drawexe.stat().st_mtime_ns}
        if (
            cached.get("schema") == CACHE_SCHEMA
            and cached.get("source_sha256") == source_hash
            and cached.get("backend") == backend
            and cached.get("normalized_parts") == metadata
            and len(metadata) == len(cached.get("properties", []))
        ):
            properties = []
            for raw in cached["properties"]:
                raw = dict(raw)
                for key in ("center", "moments", "bbox"):
                    raw[key] = tuple(raw[key])
                properties.append(ExactProperties(**raw))
            return properties, source_hash
    properties = inspect_and_normalize(source, cache_dir, drawexe)
    manifest.write_text(json.dumps({
        "schema": CACHE_SCHEMA, "source": str(source.resolve()), "source_sha256": source_hash,
        "backend": {"path": str(drawexe), "bytes": drawexe.stat().st_size, "mtime_ns": drawexe.stat().st_mtime_ns},
        "normalized_parts": _normalized_metadata(cache_dir),
        "properties": [item.to_dict() for item in properties],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return properties, source_hash


def _write_csv(output: Path, parts: list[PartFeatures], assignments: list[int], pairs: list[dict]) -> None:
    with (output / "parts.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "part_index", "part_name", "group", "volume", "surface_area", "edge_length",
            "faces", "edges", "vertices", "bbox_max", "bbox_mid", "bbox_min",
            "moment_max", "moment_mid", "moment_min", "normalized_step",
        ])
        for part, group in zip(parts, assignments):
            writer.writerow([
                part.index, part.label, group, part.exact.volume, part.exact.area,
                part.exact.edge_length, part.exact.faces, part.exact.edges, part.exact.vertices,
                *part.exact.bbox, *part.exact.moments, part.source_file,
            ])
    with (output / "similarities.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        fields = ["part_a", "part_b", "similarity", "distance", "topology_distance", "geometry_distance", "shape_distance", "size_distance", "size_gate_failed", "same_group"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for pair in pairs:
            row = dict(pair)
            row["same_group"] = assignments[row["part_a"] - 1] == assignments[row["part_b"] - 1]
            writer.writerow(row)


def _group_summaries(parts: list[PartFeatures], assignments: list[int], pairs: list[dict]) -> list[dict]:
    grouped: dict[int, list[int]] = {}
    for part, group in zip(parts, assignments):
        grouped.setdefault(group, []).append(part.index)
    pair_lookup = {(row["part_a"], row["part_b"]): row for row in pairs}
    summaries = []
    for group, indices in sorted(grouped.items()):
        similarities = [
            pair_lookup[(min(left, right), max(left, right))]["similarity"]
            for position, right in enumerate(indices) for left in indices[:position]
        ]
        summaries.append({
            "group": group, "part_count": len(indices), "parts": indices,
            "minimum_internal_similarity": min(similarities) if similarities else 1.0,
            "mean_internal_similarity": sum(similarities) / len(similarities) if similarities else 1.0,
        })
    return summaries


def _post_cluster_verification(parts: list[PartFeatures], assignments: list[int], pairs: list[dict], threshold: float) -> dict:
    grouped_pairs = [
        pair for pair in pairs
        if assignments[pair["part_a"] - 1] == assignments[pair["part_b"] - 1]
    ]
    violations = [pair for pair in grouped_pairs if pair["distance"] > threshold + 1e-12 or pair["size_gate_failed"]]
    exact_pairs = [
        pair for pair in grouped_pairs
        if max(pair["topology_distance"], pair["geometry_distance"], pair["shape_distance"], pair["size_distance"]) <= 1e-9
    ]
    return {
        "coverage_exactly_once": sorted(range(1, len(parts) + 1)) == sorted(part.index for part in parts),
        "within_complete_link_threshold": not violations,
        "grouped_pair_count": len(grouped_pairs),
        "exact_invariant_pair_count": len(exact_pairs),
        "violations": violations,
    }


def run(args: argparse.Namespace) -> dict:
    source = args.step_file.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    cache_dir = output / "normalized_parts"
    drawexe = find_drawexe(args.drawexe)
    properties, source_hash = _load_or_extract(source, cache_dir, output / "cache_manifest.json", drawexe, args.reuse_cache)

    parts: list[PartFeatures] = []
    for exact in properties:
        normalized = cache_dir / f"part_{exact.index:04d}.step"
        label, graph = describe_normalized_step(
            normalized, args.wl_iterations, max(exact.volume, 1e-15) ** (1.0 / 3.0)
        )
        if not args.allow_unknown_geometry and (
            graph.graph["unknown_surface_uses"] or graph.graph["unknown_curve_uses"]
        ):
            raise RuntimeError(
                f"Part {exact.index} contains unsupported geometry: "
                f"surfaces={graph.graph['unknown_surface_uses']}, curves={graph.graph['unknown_curve_uses']}. "
                "Use --allow-unknown-geometry only after reviewing the report."
            )
        if label.startswith("solid_"):
            label = f"part_{exact.index:04d}"
        parts.append(PartFeatures(exact.index, label, exact, graph, str(normalized.relative_to(output))))

    matrix, pairs = distance_matrix(parts, args.mode, args.size_tolerance)
    stable_keys = [hashlib.sha256(json.dumps({
        "volume": part.exact.volume, "area": part.exact.area,
        "length": part.exact.edge_length, "moments": part.exact.moments,
        "descriptor": part.graph.to_dict(),
    }, sort_keys=True).encode("utf-8")).hexdigest() for part in parts]
    assignments = density_complete_link(matrix, args.threshold, stable_keys=stable_keys)
    verify_assignments(matrix, assignments, args.threshold)
    _write_csv(output, parts, assignments, pairs)
    groups: dict[int, list[int]] = {}
    for part, group in zip(parts, assignments):
        groups.setdefault(group, []).append(part.index)
    exported_indices = [index for indices in groups.values() for index in indices]
    if sorted(exported_indices) != list(range(1, len(parts) + 1)) or len(set(exported_indices)) != len(parts):
        raise RuntimeError("Cluster coverage is incomplete or contains duplicate solid indices")
    post_cluster_verification = _post_cluster_verification(parts, assignments, pairs, args.threshold)
    if not post_cluster_verification["within_complete_link_threshold"]:
        raise RuntimeError("Post-cluster geometric consistency verification failed")

    exports = validation = []
    if not args.skip_step_export:
        group_dir = output / "grouped_steps"
        exports = export_groups(source, groups, group_dir, drawexe)
        validation = validate_group_steps(
            [group_dir / item["file"] for item in exports],
            [item["solid_count"] for item in exports],
            drawexe,
            [sum(parts[index - 1].exact.volume for index in groups[item["group"]]) for item in exports],
        )
        if not all(item["valid"] for item in validation):
            raise RuntimeError(f"Generated STEP validation failed: {[item['file'] for item in validation if not item['valid']]}")
        (group_dir / "manifest.json").write_text(json.dumps({"exports": exports, "validation": validation}, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "version": "3.0.0", "method": "training-free-brep-dual-wl-vpd-agglomerative-complete-link",
        "source": str(source), "source_sha256": source_hash, "occt_drawexe": str(drawexe),
        "mode": args.mode, "distance_threshold": args.threshold,
        "size_tolerance": args.size_tolerance, "wl_iterations": args.wl_iterations,
        "part_count": len(parts), "group_count": len(groups),
        "groups": _group_summaries(parts, assignments, pairs),
        "parts": [{
            "part_index": part.index, "name": part.label, "group": group,
            "exact": part.exact.to_dict(), "descriptor": part.graph.to_dict(),
        } for part, group in zip(parts, assignments)],
        "post_cluster_verification": post_cluster_verification,
        "exports": exports, "validation": validation,
    }
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "method.json").write_text(json.dumps({
        "learned_parameters": False, "random_projection": False,
        "dataset_relative_normalization": False,
        "channels": {
            "topology": "strict and scale-normalized attributed WL subtree histograms",
            "geometry": "fixed B-Rep counts and dimensionless mass properties",
            "shape": "rotation-invariant all-pairs geometric-diameter-normalized soft histogram",
            "size": "absolute volume, area and edge-length log ratios",
        },
        "clustering": "deterministic agglomerative complete-link",
        "strict_size_gate": args.size_tolerance,
        "strict_weights": {"topology": 0.40, "geometry": 0.25, "shape": 0.20, "size": 0.15},
        "family_weights": {"topology": 0.48, "geometry": 0.32, "shape": 0.20, "size": 0.0},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Training-free STEP B-Rep similarity grouping")
    parser.add_argument("step_file", type=Path)
    parser.add_argument("--output", type=Path, default=Path("geometry_encoder_output"))
    parser.add_argument("--mode", choices=("strict", "family"), default="strict")
    parser.add_argument("--threshold", type=float, default=0.12, help="Maximum composite distance within a group")
    parser.add_argument("--size-tolerance", type=float, default=0.03, help="Strict-mode maximum relative volume/area/length difference")
    parser.add_argument("--wl-iterations", type=int, default=3, choices=range(1, 6))
    parser.add_argument("--drawexe", type=Path)
    parser.add_argument("--reuse-cache", action="store_true")
    parser.add_argument("--skip-step-export", action="store_true")
    parser.add_argument("--allow-unknown-geometry", action="store_true")
    args = parser.parse_args(argv)
    if not 0.0 <= args.threshold <= 1.0:
        parser.error("threshold must be in [0, 1]")
    if not 0.0 <= args.size_tolerance <= 1.0:
        parser.error("size-tolerance must be in [0, 1]")
    report = run(args)
    print(f"Processed {report['part_count']} solids into {report['group_count']} groups.")
    print(f"Mode={report['mode']}, distance threshold={report['distance_threshold']:.3f}")
    print(f"Results: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
