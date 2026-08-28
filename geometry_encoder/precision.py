"""Independent post-cluster rigid congruence and exact-verification models."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from .step_graph import (
    _cartesian_point, _curve_for_edge, _entity_kind, _face_edge_curves,
    _surface_for_face, _vertex_points,
    parse_step, reachable, solid_root,
)


Point = tuple[float, float, float]
Matrix3 = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
EdgeSignature = Counter[tuple[int, int, str]]
FaceSignature = Counter[tuple[str, tuple[tuple[int, int, str], ...]]]


@dataclass(frozen=True)
class RigidGeometry:
    points: list[Point]
    edges: EdgeSignature
    faces: FaceSignature


@dataclass(frozen=True)
class RigidTransform:
    rotation: Matrix3
    translation: Point
    axis: Point
    angle_degrees: float
    rms_vertex_error: float
    max_vertex_error: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PairVerification:
    group: int
    reference_part: int
    candidate_part: int
    status: str
    reason: str
    vertex_count: int
    transform: RigidTransform | None = None
    forward_difference_volume: float | None = None
    reverse_difference_volume: float | None = None
    boolean_relative_error: float | None = None
    passed: bool = False

    def to_dict(self) -> dict:
        result = asdict(self)
        if self.transform:
            result["transform"] = self.transform.to_dict()
        return result


def load_vertex_points(path: Path) -> list[Point]:
    entities = parse_step(path)
    return _vertex_points(reachable(solid_root(entities), entities), entities)


def load_rigid_geometry(path: Path) -> RigidGeometry:
    """Load vertices plus typed edge connectivity to disambiguate symmetric point sets."""
    entities = parse_step(path)
    ids = reachable(solid_root(entities), entities)
    points = _vertex_points(ids, entities)
    point_index = {point: index for index, point in enumerate(points)}
    vertex_coordinates: dict[int, Point] = {}
    for entity_id in ids:
        entity = entities[entity_id]
        if entity.kind != "VERTEX_POINT":
            continue
        point_ref = next((ref for ref in entity.refs if _entity_kind(ref, entities) == "CARTESIAN_POINT"), None)
        if point_ref is None:
            continue
        point = _cartesian_point(entities[point_ref])
        if point is not None:
            vertex_coordinates[entity_id] = tuple(round(value, 10) for value in point)
    def typed_edge(edge_id: int) -> tuple[int, int, str] | None:
        endpoints = [ref for ref in entities[edge_id].refs if _entity_kind(ref, entities) == "VERTEX_POINT"][:2]
        if len(endpoints) != 2 or any(ref not in vertex_coordinates for ref in endpoints):
            return None
        left = point_index[vertex_coordinates[endpoints[0]]]
        right = point_index[vertex_coordinates[endpoints[1]]]
        return min(left, right), max(left, right), _curve_for_edge(edge_id, entities).kind

    edges: EdgeSignature = Counter()
    for entity_id in ids:
        entity = entities[entity_id]
        if entity.kind != "EDGE_CURVE":
            continue
        signature = typed_edge(entity_id)
        if signature is not None:
            edges[signature] += 1
    faces: FaceSignature = Counter()
    for entity_id in ids:
        if entities[entity_id].kind != "ADVANCED_FACE":
            continue
        boundary = tuple(sorted(
            signature for edge_id in _face_edge_curves(entity_id, entities)
            if (signature := typed_edge(edge_id)) is not None
        ))
        faces[(_surface_for_face(entity_id, entities).kind, boundary)] += 1
    return RigidGeometry(points, edges, faces)


def _sub(left: Point, right: Point) -> Point:
    return tuple(a - b for a, b in zip(left, right))  # type: ignore[return-value]


def _add(left: Point, right: Point) -> Point:
    return tuple(a + b for a, b in zip(left, right))  # type: ignore[return-value]


def _scale(value: Point, factor: float) -> Point:
    return tuple(item * factor for item in value)  # type: ignore[return-value]


def _dot(left: Point, right: Point) -> float:
    return sum(a * b for a, b in zip(left, right))


def _cross(left: Point, right: Point) -> Point:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _norm(value: Point) -> float:
    return math.sqrt(_dot(value, value))


def _unit(value: Point) -> Point:
    magnitude = _norm(value)
    if magnitude <= 1e-15:
        raise ValueError("Cannot normalize zero vector")
    return _scale(value, 1.0 / magnitude)


def _frame(a: Point, b: Point, c: Point) -> Matrix3:
    first = _unit(_sub(b, a))
    raw_second = _sub(_sub(c, a), _scale(first, _dot(_sub(c, a), first)))
    second = _unit(raw_second)
    third = _unit(_cross(first, second))
    return (first, second, third)


def _rotation(source: Matrix3, target: Matrix3) -> Matrix3:
    # Frames are stored as basis vectors; R = T * S^T.
    return tuple(
        tuple(sum(target[k][row] * source[k][column] for k in range(3)) for column in range(3))
        for row in range(3)
    )  # type: ignore[return-value]


def _matvec(matrix: Matrix3, point: Point) -> Point:
    return tuple(sum(row[column] * point[column] for column in range(3)) for row in matrix)  # type: ignore[return-value]


def _axis_angle(matrix: Matrix3) -> tuple[Point, float]:
    # Stable matrix-to-quaternion conversion avoids the severe loss of precision
    # in the usual skew/diagonal formulas close to 180 degrees.
    trace = matrix[0][0] + matrix[1][1] + matrix[2][2]
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        qw = 0.25 * scale
        qx = (matrix[2][1] - matrix[1][2]) / scale
        qy = (matrix[0][2] - matrix[2][0]) / scale
        qz = (matrix[1][0] - matrix[0][1]) / scale
    else:
        largest = max(range(3), key=lambda index: matrix[index][index])
        if largest == 0:
            scale = math.sqrt(max(0.0, 1.0 + matrix[0][0] - matrix[1][1] - matrix[2][2])) * 2.0
            qw, qx = (matrix[2][1] - matrix[1][2]) / scale, 0.25 * scale
            qy, qz = (matrix[0][1] + matrix[1][0]) / scale, (matrix[0][2] + matrix[2][0]) / scale
        elif largest == 1:
            scale = math.sqrt(max(0.0, 1.0 + matrix[1][1] - matrix[0][0] - matrix[2][2])) * 2.0
            qw, qy = (matrix[0][2] - matrix[2][0]) / scale, 0.25 * scale
            qx, qz = (matrix[0][1] + matrix[1][0]) / scale, (matrix[1][2] + matrix[2][1]) / scale
        else:
            scale = math.sqrt(max(0.0, 1.0 + matrix[2][2] - matrix[0][0] - matrix[1][1])) * 2.0
            qw, qz = (matrix[1][0] - matrix[0][1]) / scale, 0.25 * scale
            qx, qy = (matrix[0][2] + matrix[2][0]) / scale, (matrix[1][2] + matrix[2][1]) / scale
    quaternion_norm = math.sqrt(qw * qw + qx * qx + qy * qy + qz * qz)
    qw, qx, qy, qz = (value / quaternion_norm for value in (qw, qx, qy, qz))
    if qw < 0.0:
        qw, qx, qy, qz = (-qw, -qx, -qy, -qz)
    vector_norm = math.sqrt(qx * qx + qy * qy + qz * qz)
    if vector_norm < 1e-14:
        return (0.0, 0.0, 1.0), 0.0
    axis = (qx / vector_norm, qy / vector_norm, qz / vector_norm)
    angle = 2.0 * math.atan2(vector_norm, max(-1.0, min(1.0, qw)))
    return axis, math.degrees(angle)


def _fingerprints(points: list[Point], tolerance: float) -> list[tuple[int, ...]]:
    return [
        tuple(sorted(
            round(math.dist(point, other) / tolerance)
            for other_index, other in enumerate(points) if other_index != point_index
        ))
        for point_index, point in enumerate(points)
    ]


def _match_points(
    transformed: list[Point], target: list[Point], tolerance: float,
) -> tuple[float, float, tuple[int, ...]] | None:
    buckets: dict[tuple[int, int, int], list[int]] = {}
    for index, point in enumerate(target):
        key = tuple(round(value / tolerance) for value in point)
        buckets.setdefault(key, []).append(index)  # type: ignore[arg-type]
    used: set[int] = set()
    errors = []
    mapping = []
    for point in transformed:
        center = tuple(round(value / tolerance) for value in point)
        candidates = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    candidates.extend(buckets.get((center[0] + dx, center[1] + dy, center[2] + dz), ()))
        available = [(math.dist(point, target[index]), index) for index in candidates if index not in used]
        if not available:
            return None
        error, chosen = min(available)
        if error > tolerance:
            return None
        used.add(chosen)
        errors.append(error)
        mapping.append(chosen)
    if len(used) != len(target):
        return None
    return (
        math.sqrt(sum(error * error for error in errors) / max(1, len(errors))),
        max(errors, default=0.0), tuple(mapping),
    )


def find_rigid_transform(
    source: list[Point], target: list[Point], tolerance: float = 1e-5,
    source_edges: EdgeSignature | None = None, target_edges: EdgeSignature | None = None,
    source_faces: FaceSignature | None = None, target_faces: FaceSignature | None = None,
) -> RigidTransform | None:
    """Find a proper rigid transform using invariant vertex-distance fingerprints."""
    if len(source) != len(target) or len(source) < 3:
        return None
    source_fingerprints = _fingerprints(source, tolerance)
    target_fingerprints = _fingerprints(target, tolerance)
    a, b = max(
        ((left, right) for left in range(len(source)) for right in range(left)),
        key=lambda pair: math.dist(source[pair[0]], source[pair[1]]),
    )
    line = _sub(source[b], source[a])
    line_length = _norm(line)
    c = max(
        (index for index in range(len(source)) if index not in {a, b}),
        key=lambda index: _norm(_cross(line, _sub(source[index], source[a]))) / line_length,
    )
    altitude = _norm(_cross(line, _sub(source[c], source[a]))) / line_length
    if altitude <= tolerance:
        return None
    target_a = [index for index, value in enumerate(target_fingerprints) if value == source_fingerprints[a]]
    target_b = [index for index, value in enumerate(target_fingerprints) if value == source_fingerprints[b]]
    target_c = [index for index, value in enumerate(target_fingerprints) if value == source_fingerprints[c]]
    source_distances = (math.dist(source[a], source[b]), math.dist(source[a], source[c]), math.dist(source[b], source[c]))
    attempts = 0
    for ta in target_a:
        for tb in target_b:
            if ta == tb or abs(math.dist(target[ta], target[tb]) - source_distances[0]) > tolerance:
                continue
            for tc in target_c:
                if tc in {ta, tb}:
                    continue
                if abs(math.dist(target[ta], target[tc]) - source_distances[1]) > tolerance:
                    continue
                if abs(math.dist(target[tb], target[tc]) - source_distances[2]) > tolerance:
                    continue
                attempts += 1
                if attempts > 10000:
                    return None
                rotation = _rotation(_frame(source[a], source[b], source[c]), _frame(target[ta], target[tb], target[tc]))
                translation = _sub(target[ta], _matvec(rotation, source[a]))
                transformed = [_add(_matvec(rotation, point), translation) for point in source]
                errors = _match_points(transformed, target, tolerance)
                if errors is not None:
                    if source_edges is not None and target_edges is not None:
                        mapping = errors[2]
                        remapped = Counter(
                            (min(mapping[left], mapping[right]), max(mapping[left], mapping[right]), curve)
                            for (left, right, curve), count in source_edges.items()
                            for _ in range(count)
                        )
                        if remapped != target_edges:
                            continue
                    if source_faces is not None and target_faces is not None:
                        mapping = errors[2]
                        remapped_faces: FaceSignature = Counter()
                        for (surface, boundary), count in source_faces.items():
                            mapped_boundary = tuple(sorted(
                                (min(mapping[left], mapping[right]), max(mapping[left], mapping[right]), curve)
                                for left, right, curve in boundary
                            ))
                            remapped_faces[(surface, mapped_boundary)] += count
                        if remapped_faces != target_faces:
                            continue
                    axis, angle = _axis_angle(rotation)
                    return RigidTransform(rotation, translation, axis, angle, errors[0], errors[1])
    return None


def build_pair_verifications(
    groups: dict[int, list[int]], normalized_dir: Path, tolerance: float = 1e-5,
) -> list[PairVerification]:
    results = []
    geometry_cache: dict[int, RigidGeometry] = {}
    for group, indices in sorted(groups.items()):
        if len(indices) < 2:
            continue
        reference = indices[0]
        geometry_cache.setdefault(reference, load_rigid_geometry(normalized_dir / f"part_{reference:04d}.step"))
        for candidate in indices[1:]:
            geometry_cache.setdefault(candidate, load_rigid_geometry(normalized_dir / f"part_{candidate:04d}.step"))
            source, target = geometry_cache[reference], geometry_cache[candidate]
            transform = find_rigid_transform(
                source.points, target.points, tolerance,
                source.edges, target.edges, source.faces, target.faces,
            )
            if transform is None:
                results.append(PairVerification(
                    group, reference, candidate, "alignment_failed",
                    "No proper rigid transform preserves vertices, typed edges, and face boundaries",
                    len(source.points), passed=False,
                ))
            else:
                results.append(PairVerification(
                    group, reference, candidate, "aligned", "Rigid topology-aware congruence passed",
                    len(source.points), transform=transform,
                ))
    return results


def build_rigid_verification_forest(
    groups: dict[int, list[int]], normalized_dir: Path, tolerance: float = 1e-5,
) -> list[PairVerification]:
    """Build a minimal congruence forest, creating a new root when alignment fails."""
    results: list[PairVerification] = []
    geometry_cache: dict[int, RigidGeometry] = {}
    for group, indices in sorted(groups.items()):
        roots: list[int] = []
        for candidate in indices:
            geometry_cache.setdefault(candidate, load_rigid_geometry(normalized_dir / f"part_{candidate:04d}.step"))
            matched = False
            failures: list[PairVerification] = []
            for reference in roots:
                reference_geometry = geometry_cache[reference]
                candidate_geometry = geometry_cache[candidate]
                transform = find_rigid_transform(
                    reference_geometry.points, candidate_geometry.points, tolerance,
                    reference_geometry.edges, candidate_geometry.edges,
                    reference_geometry.faces, candidate_geometry.faces,
                )
                if transform is not None:
                    results.append(PairVerification(
                        group, reference, candidate, "aligned", "Rigid vertex congruence passed",
                        len(reference_geometry.points), transform=transform,
                    ))
                    matched = True
                    break
                failures.append(PairVerification(
                    group, reference, candidate, "alignment_failed",
                    "No proper rigid transform maps the complete vertex sets",
                    len(reference_geometry.points), passed=False,
                ))
            if not matched:
                results.extend(failures)
                roots.append(candidate)
    return results


def refine_groups_from_verifications(
    groups: dict[int, list[int]], verifications: list[PairVerification],
) -> tuple[dict[int, list[int]], dict[int, list[int]]]:
    """Split candidate groups into components connected by passed exact checks."""
    parent: dict[int, int] = {}

    def find(value: int) -> int:
        parent.setdefault(value, value)
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    original_group_by_part = {
        part: group for group, parts in groups.items() for part in parts
    }
    for part in original_group_by_part:
        find(part)
    for item in verifications:
        if item.passed:
            union(item.reference_part, item.candidate_part)
    components: dict[tuple[int, int], list[int]] = {}
    for part, original_group in original_group_by_part.items():
        components.setdefault((original_group, find(part)), []).append(part)
    refined = {
        group_id: sorted(parts)
        for group_id, (_, parts) in enumerate(
            sorted(components.items(), key=lambda item: min(item[1])), 1
        )
    }
    lineage = {
        group_id: sorted({original_group_by_part[part] for part in parts})
        for group_id, parts in refined.items()
    }
    return refined, lineage
