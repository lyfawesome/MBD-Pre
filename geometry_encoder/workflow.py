"""Stage-oriented, observable, and resumable STEP grouping workflow."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from .config import WorkflowConfig
from .occt_backend import (
    ExactProperties, export_groups, find_drawexe, inspect_and_normalize,
    validate_group_steps, verify_rigid_pairs_with_boolean,
)
from .precision import build_pair_verifications
from .similarity import PartFeatures, density_complete_link, distance_matrix, verify_assignments
from .step_graph import describe_normalized_step
from .telemetry import WorkflowRecorder, file_sha256


CACHE_SCHEMA = 4


def _normalized_metadata(cache_dir: Path) -> list[dict]:
    return [
        {"file": path.name, "bytes": path.stat().st_size, "sha256": file_sha256(path)}
        for path in sorted(cache_dir.glob("part_*.step"))
    ]


def _load_or_extract(
    source: Path, cache_dir: Path, manifest: Path, drawexe: Path, reuse: bool,
) -> tuple[list[ExactProperties], bool]:
    source_hash = file_sha256(source)
    backend = {"path": str(drawexe), "bytes": drawexe.stat().st_size, "mtime_ns": drawexe.stat().st_mtime_ns}
    if reuse and manifest.is_file():
        cached = json.loads(manifest.read_text(encoding="utf-8"))
        metadata = _normalized_metadata(cache_dir)
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
            return properties, True
    properties = inspect_and_normalize(source, cache_dir, drawexe)
    manifest.write_text(json.dumps({
        "schema": CACHE_SCHEMA, "source": str(source), "source_sha256": source_hash,
        "backend": backend, "normalized_parts": _normalized_metadata(cache_dir),
        "properties": [item.to_dict() for item in properties],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return properties, False


def _groups(assignments: list[int], parts: list[PartFeatures]) -> dict[int, list[int]]:
    result: dict[int, list[int]] = {}
    for part, group in zip(parts, assignments):
        result.setdefault(group, []).append(part.index)
    return result


def _assignments(groups: dict[int, list[int]], part_count: int) -> list[int]:
    result = [0] * part_count
    for group, indices in groups.items():
        for index in indices:
            result[index - 1] = group
    if any(value <= 0 for value in result):
        raise RuntimeError("Final precision groups do not cover every part")
    return result


def _precision_partition_is_proven(groups: dict[int, list[int]], verifications: list) -> bool:
    adjacency: dict[int, set[int]] = {}
    for item in verifications:
        if item.passed:
            adjacency.setdefault(item.reference_part, set()).add(item.candidate_part)
            adjacency.setdefault(item.candidate_part, set()).add(item.reference_part)
    for parts in groups.values():
        if len(parts) < 2:
            continue
        reached, stack = set(), [parts[0]]
        allowed = set(parts)
        while stack:
            current = stack.pop()
            if current in reached:
                continue
            reached.add(current)
            stack.extend(adjacency.get(current, set()) & allowed)
        if reached != allowed:
            return False
    return True


def _stable_keys(parts: list[PartFeatures]) -> list[str]:
    return [hashlib.sha256(json.dumps({
        "volume": part.exact.volume, "area": part.exact.area,
        "length": part.exact.edge_length, "moments": part.exact.moments,
        "descriptor": part.graph.to_dict(),
    }, sort_keys=True).encode("utf-8")).hexdigest() for part in parts]


def _group_summaries(groups: dict[int, list[int]], pairs: list[dict]) -> list[dict]:
    lookup = {(row["part_a"], row["part_b"]): row for row in pairs}
    summaries = []
    for group, indices in sorted(groups.items()):
        values = [
            lookup[(min(left, right), max(left, right))]["similarity"]
            for position, right in enumerate(indices) for left in indices[:position]
        ]
        summaries.append({
            "group": group, "part_count": len(indices), "parts": indices,
            "minimum_internal_similarity": min(values) if values else 1.0,
            "mean_internal_similarity": sum(values) / len(values) if values else 1.0,
        })
    return summaries


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
    fields = [
        "part_a", "part_b", "similarity", "distance", "topology_distance",
        "geometry_distance", "shape_distance", "size_distance", "size_gate_failed", "same_group",
    ]
    with (output / "similarities.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for pair in pairs:
            row = dict(pair)
            row["same_group"] = assignments[row["part_a"] - 1] == assignments[row["part_b"] - 1]
            writer.writerow(row)


def _data_quality(parts: list[PartFeatures], matrix: list[list[float]]) -> dict:
    curve_types: Counter[str] = Counter()
    surface_types: Counter[str] = Counter()
    for part in parts:
        curve_types.update(part.graph.curve_histogram)
        surface_types.update(part.graph.surface_histogram)
    symmetry_error = max(
        (abs(matrix[left][right] - matrix[right][left]) for left in range(len(matrix)) for right in range(len(matrix))),
        default=0.0,
    )
    return {
        "part_count": len(parts),
        "nonpositive_volume_parts": [part.index for part in parts if part.exact.volume <= 0],
        "zero_face_parts": [part.index for part in parts if part.exact.faces <= 0],
        "unknown_curve_uses": sum(part.graph.graph["unknown_curve_uses"] for part in parts),
        "unknown_surface_uses": sum(part.graph.graph["unknown_surface_uses"] for part in parts),
        "curve_types": dict(curve_types), "surface_types": dict(surface_types),
        "distance_matrix_symmetry_error": symmetry_error,
        "distance_range": [
            min((value for row in matrix for value in row), default=0.0),
            max((value for row in matrix for value in row), default=0.0),
        ],
    }


class GeometryWorkflow:
    def __init__(self, config: WorkflowConfig):
        config.validate()
        self.config = config

    def run(self) -> dict:
        config = self.config
        source = config.step_file.resolve()
        output = config.output.resolve()
        if not source.is_file():
            raise FileNotFoundError(source)
        output.mkdir(parents=True, exist_ok=True)
        source_hash = file_sha256(source)
        recorder = WorkflowRecorder(output, config.to_dict(), source_hash)
        drawexe = find_drawexe(config.drawexe)
        cache_dir = output / "normalized_parts"

        with recorder.stage("normalize") as stage:
            properties, cache_hit = _load_or_extract(
                source, cache_dir, output / "cache_manifest.json", drawexe, config.reuse_cache
            )
            stage["metrics"] = {"part_count": len(properties), "cache_hit": cache_hit}
        recorder.gate("nonempty_model", bool(properties), {"part_count": len(properties)})

        with recorder.stage("feature_collection") as stage:
            parts: list[PartFeatures] = []
            for exact in properties:
                normalized = cache_dir / f"part_{exact.index:04d}.step"
                label, graph = describe_normalized_step(
                    normalized, config.wl_iterations, max(exact.volume, 1e-15) ** (1.0 / 3.0)
                )
                if label.startswith("solid_"):
                    label = f"part_{exact.index:04d}"
                parts.append(PartFeatures(
                    exact.index, label, exact, graph, str(normalized.relative_to(output))
                ))
            stage["metrics"] = {"part_count": len(parts)}

        with recorder.stage("similarity") as stage:
            matrix, pairs = distance_matrix(parts, config.mode, config.size_tolerance)
            quality = _data_quality(parts, matrix)
            (output / "data_quality.json").write_text(
                json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            stage["metrics"] = quality
        recorder.gate("geometry_supported", config.allow_unknown_geometry or (
            quality["unknown_curve_uses"] == 0 and quality["unknown_surface_uses"] == 0
        ), {"unknown_curves": quality["unknown_curve_uses"], "unknown_surfaces": quality["unknown_surface_uses"]})
        recorder.gate("distance_matrix_valid", quality["distance_matrix_symmetry_error"] <= 1e-12, quality)

        with recorder.stage("candidate_clustering") as stage:
            candidate_assignments = density_complete_link(
                matrix, config.threshold, stable_keys=_stable_keys(parts)
            )
            verify_assignments(matrix, candidate_assignments, config.threshold)
            candidate_groups = _groups(candidate_assignments, parts)
            stage["metrics"] = {"candidate_group_count": len(candidate_groups)}

        with recorder.stage("precision_verification") as stage:
            verifications = []
            lineage = {group: [group] for group in candidate_groups}
            final_groups = candidate_groups
            if config.precision_mode != "off":
                partitions: list[tuple[int, list[int]]] = []
                volumes = {part.index: part.exact.volume for part in parts}
                for original_group, original_parts in sorted(candidate_groups.items()):
                    remaining = list(original_parts)
                    while remaining:
                        reference = remaining[0]
                        if len(remaining) == 1:
                            partitions.append((original_group, [reference]))
                            break
                        round_checks = build_pair_verifications(
                            {original_group: remaining}, cache_dir, config.vertex_tolerance
                        )
                        if config.precision_mode == "boolean":
                            verify_rigid_pairs_with_boolean(
                                source, round_checks, volumes, drawexe,
                                config.boolean_relative_tolerance, config.precision_workers,
                            )
                        else:
                            for item in round_checks:
                                if item.transform is not None:
                                    item.passed = True
                                    item.status = "rigid_verified"
                                    item.reason = "Topology-aware rigid congruence passed"
                        verifications.extend(round_checks)
                        passed = {item.candidate_part for item in round_checks if item.passed}
                        partitions.append((original_group, [reference] + [part for part in remaining[1:] if part in passed]))
                        remaining = [part for part in remaining[1:] if part not in passed]
                final_groups = {
                    group_id: sorted(group_parts)
                    for group_id, (_, group_parts) in enumerate(partitions, 1)
                }
                lineage = {
                    group_id: [original_group]
                    for group_id, (original_group, _) in enumerate(partitions, 1)
                }
            final_assignments = _assignments(final_groups, len(parts))
            precision_report = {
                "mode": config.precision_mode,
                "candidate_group_count": len(candidate_groups),
                "final_group_count": len(final_groups),
                "lineage": lineage,
                "checked_pair_count": len(verifications),
                "passed_pair_count": sum(item.passed for item in verifications),
                "failed_or_split_pair_count": sum(not item.passed for item in verifications),
                "pairs": [item.to_dict() for item in verifications],
            }
            (output / "precision_report.json").write_text(
                json.dumps(precision_report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            stage["metrics"] = {key: value for key, value in precision_report.items() if key != "pairs"}
        recorder.gate(
            "precision_partition_proven",
            config.precision_mode == "off" or _precision_partition_is_proven(final_groups, verifications),
            {"mode": config.precision_mode, "group_count": len(final_groups), "checked_pairs": len(verifications)},
        )
        recorder.gate("final_group_coverage", sorted(
            index for indices in final_groups.values() for index in indices
        ) == list(range(1, len(parts) + 1)), {"part_count": len(parts), "group_count": len(final_groups)})

        with recorder.stage("result_materialization") as stage:
            _write_csv(output, parts, final_assignments, pairs)
            exports = validation = []
            if not config.skip_step_export:
                group_dir = output / "grouped_steps"
                exports = export_groups(source, final_groups, group_dir, drawexe)
                validation = validate_group_steps(
                    [group_dir / item["file"] for item in exports],
                    [item["solid_count"] for item in exports], drawexe,
                    [sum(parts[index - 1].exact.volume for index in final_groups[item["group"]]) for item in exports],
                )
                (group_dir / "manifest.json").write_text(
                    json.dumps({"exports": exports, "validation": validation}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            stage["metrics"] = {"export_count": len(exports), "valid_export_count": sum(item["valid"] for item in validation)}
        if not config.skip_step_export:
            recorder.gate("export_roundtrip", all(item["valid"] for item in validation), {
                "expected_solids": sum(item["expected_solid_count"] for item in validation),
                "actual_solids": sum(item["actual_solid_count"] for item in validation),
                "valid_files": sum(item["valid"] for item in validation),
            })

        report = {
            "version": "4.0.0", "method": "automated-brep-similarity-with-independent-precision-verification",
            "source": str(source), "source_sha256": source_hash, "occt_drawexe": str(drawexe),
            "config": config.to_dict(), "part_count": len(parts),
            "candidate_group_count": len(candidate_groups), "group_count": len(final_groups),
            "candidate_groups": _group_summaries(candidate_groups, pairs),
            "groups": _group_summaries(final_groups, pairs),
            "precision": {key: value for key, value in precision_report.items() if key != "pairs"},
            "data_quality": quality,
            "parts": [{
                "part_index": part.index, "name": part.label, "group": final_assignments[part.index - 1],
                "exact": part.exact.to_dict(), "descriptor": part.graph.to_dict(),
            } for part in parts],
            "exports": exports, "validation": validation,
        }
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        (output / "method.json").write_text(json.dumps({
            "learned_parameters": False, "random_projection": False,
            "candidate_clustering": "deterministic agglomerative complete-link",
            "precision_verification": config.precision_mode,
            "precision_vertex_tolerance": config.vertex_tolerance,
            "boolean_relative_tolerance": config.boolean_relative_tolerance,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        artifacts = [
            output / "parts.csv", output / "similarities.csv", output / "report.json",
            output / "precision_report.json", output / "data_quality.json", output / "method.json",
        ]
        if not config.skip_step_export:
            artifacts.extend(sorted((output / "grouped_steps").glob("*")))
        recorder.collect_artifacts(artifacts)
        recorder.complete({
            "part_count": len(parts), "candidate_group_count": len(candidate_groups),
            "final_group_count": len(final_groups), "precision_checked_pairs": len(verifications),
            "export_count": len(exports),
        })
        return report
