"""Interpretable multi-channel distances and dependency-free clustering."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .occt_backend import ExactProperties
from .step_graph import GraphDescriptor


@dataclass
class PartFeatures:
    index: int
    label: str
    exact: ExactProperties
    graph: GraphDescriptor
    source_file: str


@dataclass(frozen=True)
class DistanceBreakdown:
    total: float
    topology: float
    geometry: float
    shape: float
    size: float
    size_gate_failed: bool = False

    @property
    def similarity(self) -> float:
        return max(0.0, 1.0 - self.total)

    def to_dict(self) -> dict:
        return {
            "distance": self.total,
            "similarity": self.similarity,
            "topology_distance": self.topology,
            "geometry_distance": self.geometry,
            "shape_distance": self.shape,
            "size_distance": self.size,
            "size_gate_failed": self.size_gate_failed,
        }


def _cosine_distance(left: dict[str, int], right: dict[str, int]) -> float:
    keys = left.keys() | right.keys()
    dot = sum(left.get(key, 0) * right.get(key, 0) for key in keys)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm and not right_norm:
        return 0.0
    if not left_norm or not right_norm:
        return 1.0
    return max(0.0, min(1.0, 1.0 - dot / (left_norm * right_norm)))


def _relative(left: float, right: float) -> float:
    return abs(left - right) / max(abs(left), abs(right), 1e-12)


def _log_ratio(left: float, right: float, octave_cap: float = 3.0) -> float:
    if left <= 1e-15 and right <= 1e-15:
        return 0.0
    if left <= 1e-15 or right <= 1e-15:
        return 1.0
    return min(1.0, abs(math.log(left / right, 2.0)) / octave_cap)


def _histogram_l1(left: list[float], right: list[float]) -> float:
    return min(1.0, sum(abs(a - b) for a, b in zip(left, right)) / 2.0)


def compare(
    left: PartFeatures,
    right: PartFeatures,
    mode: str = "strict",
    strict_size_tolerance: float = 0.03,
) -> DistanceBreakdown:
    left_wl = left.graph.wl_family_histogram if mode == "family" else left.graph.wl_histogram
    right_wl = right.graph.wl_family_histogram if mode == "family" else right.graph.wl_histogram
    topology = _cosine_distance(left_wl, right_wl)

    count_keys = left.graph.counts.keys() | right.graph.counts.keys()
    count_distance = sum(
        _relative(left.graph.counts.get(key, 0), right.graph.counts.get(key, 0))
        for key in count_keys
    ) / max(1, len(count_keys))
    surface_distance = _cosine_distance(left.graph.surface_histogram, right.graph.surface_histogram)
    curve_distance = _cosine_distance(left.graph.curve_histogram, right.graph.curve_histogram)

    left_scale = max(left.exact.volume, 1e-15) ** (1.0 / 3.0)
    right_scale = max(right.exact.volume, 1e-15) ** (1.0 / 3.0)
    dimensionless = [
        _relative(left.exact.area / left_scale**2, right.exact.area / right_scale**2),
        _relative(left.exact.edge_length / left_scale, right.exact.edge_length / right_scale),
    ]
    left_moment_sum = sum(left.exact.moments) or 1.0
    right_moment_sum = sum(right.exact.moments) or 1.0
    dimensionless.extend(
        _relative(a / left_moment_sum, b / right_moment_sum)
        for a, b in zip(left.exact.moments, right.exact.moments)
    )
    geometry = min(1.0, (
        0.30 * count_distance
        + 0.30 * surface_distance
        + 0.15 * curve_distance
        + 0.25 * (sum(dimensionless) / len(dimensionless))
    ))
    shape = _histogram_l1(left.graph.distance_histogram, right.graph.distance_histogram)
    size = sum((
        _log_ratio(left.exact.volume, right.exact.volume),
        _log_ratio(left.exact.area, right.exact.area),
        _log_ratio(left.exact.edge_length, right.exact.edge_length),
    )) / 3.0
    size_relative = max(
        _relative(left.exact.volume, right.exact.volume),
        _relative(left.exact.area, right.exact.area),
        _relative(left.exact.edge_length, right.exact.edge_length),
    )

    if mode == "family":
        weights = (0.48, 0.32, 0.20, 0.0)
    elif mode == "strict":
        weights = (0.40, 0.25, 0.20, 0.15)
    else:
        raise ValueError(f"Unknown comparison mode: {mode}")
    total = sum(weight * value for weight, value in zip(weights, (topology, geometry, shape, size)))
    size_gate_failed = mode == "strict" and size_relative > strict_size_tolerance
    if size_gate_failed:
        total = 1.0
    return DistanceBreakdown(total, topology, geometry, shape, size, size_gate_failed)


def distance_matrix(parts: list[PartFeatures], mode: str, strict_size_tolerance: float = 0.03) -> tuple[list[list[float]], list[dict]]:
    size = len(parts)
    matrix = [[0.0] * size for _ in range(size)]
    pairs = []
    for right in range(size):
        for left in range(right):
            breakdown = compare(parts[left], parts[right], mode, strict_size_tolerance)
            matrix[left][right] = matrix[right][left] = breakdown.total
            pairs.append({
                "part_a": parts[left].index,
                "part_b": parts[right].index,
                **breakdown.to_dict(),
            })
    return matrix, sorted(pairs, key=lambda row: (row["distance"], row["part_a"], row["part_b"]))


def density_complete_link(
    matrix: list[list[float]],
    threshold: float,
    min_samples: int = 2,
    stable_keys: list[str] | None = None,
) -> list[int]:
    """Deterministic agglomerative complete-link threshold clustering."""
    del min_samples  # Kept for CLI compatibility with version 2.0.
    count = len(matrix)
    keys = stable_keys or [f"{index:012d}" for index in range(count)]
    if len(keys) != count:
        raise ValueError("stable_keys length must match distance matrix")
    groups: list[tuple[int, ...]] = [(index,) for index in range(count)]
    while True:
        candidates = []
        for left_index, left in enumerate(groups):
            for right_index in range(left_index):
                right = groups[right_index]
                complete_distance = max(matrix[a][b] for a in left for b in right)
                if complete_distance <= threshold:
                    merged_keys = tuple(sorted(keys[index] for index in left + right))
                    candidates.append((complete_distance, merged_keys, right_index, left_index))
        if not candidates:
            break
        _, _, first, second = min(candidates)
        merged = tuple(sorted(groups[first] + groups[second]))
        groups = [group for index, group in enumerate(groups) if index not in {first, second}]
        groups.append(merged)

    assignments = [0] * count
    ordered = sorted(groups, key=min)
    for group_id, group in enumerate(ordered, 1):
        for index in group:
            assignments[index] = group_id
    return assignments


def verify_assignments(matrix: list[list[float]], assignments: list[int], threshold: float) -> None:
    if len(matrix) != len(assignments) or any(group <= 0 for group in assignments):
        raise ValueError("Incomplete cluster assignment")
    for right in range(len(matrix)):
        for left in range(right):
            if assignments[left] == assignments[right] and matrix[left][right] > threshold + 1e-12:
                raise ValueError(
                    f"Complete-link invariant failed for parts {left + 1}, {right + 1}: "
                    f"{matrix[left][right]} > {threshold}"
                )
