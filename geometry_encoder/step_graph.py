"""Dependency-free STEP graph descriptors for OCCT-normalized solids."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

RAW_ENTITY_RE = re.compile(r"#(\d+)\s*=\s*(.*?);", re.DOTALL)
REF_RE = re.compile(r"#(\d+)")
NUMBER_RE = re.compile(r"(?<![#A-Z_])[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:E[-+]?\d+)?", re.I)
STRING_RE = re.compile(r"'((?:''|[^'])*)'")

SURFACE_TYPES = (
    "PLANE", "CYLINDRICAL_SURFACE", "CONICAL_SURFACE", "SPHERICAL_SURFACE",
    "TOROIDAL_SURFACE", "B_SPLINE_SURFACE_WITH_KNOTS", "BEZIER_SURFACE",
    "SURFACE_OF_REVOLUTION", "SURFACE_OF_LINEAR_EXTRUSION", "OFFSET_SURFACE",
)
CURVE_TYPES = (
    "LINE", "CIRCLE", "ELLIPSE", "B_SPLINE_CURVE_WITH_KNOTS", "B_SPLINE_CURVE",
    "RATIONAL_B_SPLINE_CURVE", "BEZIER_CURVE",
    "SURFACE_CURVE", "PCURVE", "TRIMMED_CURVE",
)
BASE_CURVE_TYPES = {
    "LINE", "CIRCLE", "ELLIPSE", "B_SPLINE_CURVE_WITH_KNOTS",
    "B_SPLINE_CURVE", "RATIONAL_B_SPLINE_CURVE", "BEZIER_CURVE",
}
SOLID_TYPES = {"MANIFOLD_SOLID_BREP", "BREP_WITH_VOIDS", "FACETED_BREP"}


@dataclass(frozen=True)
class Entity:
    kind: str
    body: str
    refs: tuple[int, ...]


@dataclass
class GraphDescriptor:
    counts: dict[str, int]
    surface_histogram: dict[str, int]
    curve_histogram: dict[str, int]
    wl_histogram: dict[str, int]
    wl_family_histogram: dict[str, int]
    distance_histogram: list[float]
    graph: dict[str, int]

    def to_dict(self) -> dict:
        return {
            "counts": self.counts,
            "surface_histogram": self.surface_histogram,
            "curve_histogram": self.curve_histogram,
            "wl_histogram": self.wl_histogram,
            "wl_family_histogram": self.wl_family_histogram,
            "distance_histogram": self.distance_histogram,
            "graph": self.graph,
        }


def parse_step(path: Path) -> dict[int, Entity]:
    text = path.read_text(encoding="latin-1", errors="replace")
    entities: dict[int, Entity] = {}
    priority = (
        "B_SPLINE_CURVE_WITH_KNOTS", "RATIONAL_B_SPLINE_CURVE", "B_SPLINE_CURVE",
        "B_SPLINE_SURFACE_WITH_KNOTS", "RATIONAL_B_SPLINE_SURFACE", "B_SPLINE_SURFACE",
    )
    for match in RAW_ENTITY_RE.finditer(text):
        value = match.group(2).strip()
        simple = re.match(r"^([A-Z][A-Z0-9_]*)\s*\((.*)\)$", value, re.DOTALL)
        if simple:
            kind, body = simple.group(1), simple.group(2)
        else:
            kinds = tuple(re.findall(r"([A-Z][A-Z0-9_]*)\s*\(", value))
            if not kinds:
                continue
            kind = next((candidate for candidate in priority if candidate in kinds), kinds[0])
            body = value
        entities[int(match.group(1))] = Entity(kind, body, tuple(map(int, REF_RE.findall(body))))
    if not entities:
        raise ValueError(f"No simple STEP entities found in {path}")
    return entities


def reachable(root: int, entities: dict[int, Entity]) -> set[int]:
    seen: set[int] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        if current in seen or current not in entities:
            continue
        seen.add(current)
        stack.extend(entities[current].refs)
    return seen


def solid_root(entities: dict[int, Entity]) -> int:
    roots = [key for key, value in entities.items() if value.kind in SOLID_TYPES]
    if not roots:
        raise ValueError("OCCT-normalized STEP file contains no supported solid")
    return roots[0]


def solid_label(entities: dict[int, Entity], root: int) -> str:
    match = STRING_RE.search(entities[root].body)
    raw = match.group(1).replace("''", "'").strip() if match else ""
    return raw if raw and raw.upper() not in {"NONE", "SOLID"} else f"solid_{root}"


def _entity_kind(ref: int, entities: dict[int, Entity]) -> str:
    return entities[ref].kind if ref in entities else ""


def _direct_numbers(body: str) -> list[float]:
    cleaned = REF_RE.sub(" ", body)
    cleaned = STRING_RE.sub(" ", cleaned)
    return [float(value) for value in NUMBER_RE.findall(cleaned)]


def _intrinsic_parameters(entity: Entity) -> tuple[list[float], list[float]]:
    values = _direct_numbers(entity.body)
    length_count, angle_count = {
        "CYLINDRICAL_SURFACE": (1, 0), "SPHERICAL_SURFACE": (1, 0),
        "TOROIDAL_SURFACE": (2, 0), "CONICAL_SURFACE": (1, 1),
        "OFFSET_SURFACE": (1, 0), "CIRCLE": (1, 0), "ELLIPSE": (2, 0),
    }.get(entity.kind, (0, 0))
    if not length_count and not angle_count:
        return [], []
    lengths = values[-(length_count + angle_count):-angle_count or None] if length_count else []
    angles = values[-angle_count:] if angle_count else []
    return lengths, angles


def _parameter_token(entity: Entity, part_scale: float, family: bool) -> str:
    lengths, angles = _intrinsic_parameters(entity)
    scale = max(abs(part_scale), 1e-15) if family else 1.0
    tokens = []
    for value in lengths:
        magnitude = abs(value) / scale
        tokens.append("L0" if magnitude < 1e-15 else f"L{round(math.log10(magnitude) * 16) / 16:g}")
    tokens.extend(f"A{round(value * 360 / math.pi) / 2:g}" for value in angles)
    return ":".join(tokens)


def _edge_curve_from_oriented(edge_id: int, entities: dict[int, Entity]) -> int | None:
    entity = entities.get(edge_id)
    if not entity:
        return None
    if entity.kind == "EDGE_CURVE":
        return edge_id
    if entity.kind == "ORIENTED_EDGE":
        return next((ref for ref in reversed(entity.refs) if _entity_kind(ref, entities) == "EDGE_CURVE"), None)
    return None


def _face_edge_curves(face_id: int, entities: dict[int, Entity]) -> list[int]:
    result: list[int] = []
    bounds = [ref for ref in entities[face_id].refs if _entity_kind(ref, entities) in {"FACE_BOUND", "FACE_OUTER_BOUND"}]
    for bound_id in bounds:
        loops = [ref for ref in entities[bound_id].refs if _entity_kind(ref, entities) == "EDGE_LOOP"]
        for loop_id in loops:
            for oriented_id in entities[loop_id].refs:
                edge_curve = _edge_curve_from_oriented(oriented_id, entities)
                if edge_curve is not None:
                    result.append(edge_curve)
    return result


def _surface_for_face(face_id: int, entities: dict[int, Entity]) -> Entity:
    for ref in reversed(entities[face_id].refs):
        candidate = entities.get(ref)
        if candidate and (candidate.kind in SURFACE_TYPES or "SURFACE" in candidate.kind):
            return candidate
    return Entity("UNKNOWN_SURFACE", "", ())


def _curve_for_edge(edge_id: int, entities: dict[int, Entity]) -> Entity:
    queue = list(entities[edge_id].refs)
    seen: set[int] = set()
    fallback: Entity | None = None
    while queue:
        ref = queue.pop(0)
        if ref in seen:
            continue
        seen.add(ref)
        candidate = entities.get(ref)
        if not candidate:
            continue
        if candidate.kind in BASE_CURVE_TYPES:
            return candidate
        if candidate.kind in CURVE_TYPES or "CURVE" in candidate.kind:
            fallback = fallback or candidate
            queue[0:0] = list(candidate.refs)
    if fallback:
        return fallback
    return Entity("UNKNOWN_CURVE", "", ())


def _token(text: str) -> str:
    return hashlib.blake2b(text.encode("utf-8"), digest_size=10).hexdigest()


def _wl_histogram(node_labels: dict[int, str], adjacency: dict[int, list[tuple[int, str]]], iterations: int) -> Counter[str]:
    labels = {node: _token("0|" + label) for node, label in node_labels.items()}
    histogram: Counter[str] = Counter("0:" + label for label in labels.values())
    for level in range(1, iterations + 1):
        labels = {
            node: _token(labels[node] + "|" + "|".join(sorted(edge + ":" + labels[other] for other, edge in adjacency[node])))
            for node in sorted(labels)
        }
        histogram.update(f"{level}:{label}" for label in labels.values())
    return histogram


def _cartesian_point(entity: Entity) -> tuple[float, float, float] | None:
    if entity.kind != "CARTESIAN_POINT":
        return None
    values = [float(value) for value in NUMBER_RE.findall(entity.body)]
    return tuple(values[-3:]) if len(values) >= 3 else None


def _vertex_points(ids: set[int], entities: dict[int, Entity]) -> list[tuple[float, float, float]]:
    point_ids = {
        ref
        for entity_id in ids
        if entities[entity_id].kind == "VERTEX_POINT"
        for ref in entities[entity_id].refs
        if _entity_kind(ref, entities) == "CARTESIAN_POINT"
    }
    points = [point for point_id in point_ids if (point := _cartesian_point(entities[point_id]))]
    return sorted(set(tuple(round(value, 10) for value in point) for point in points))


def _distance_histogram(points: list[tuple[float, float, float]], bins: int = 32) -> list[float]:
    """Rotation/order-invariant, softly binned vertex-pair distances."""
    if len(points) < 2:
        return [0.0] * bins
    diameter = max(
        (math.dist(points[left], points[right]) for left in range(len(points)) for right in range(left)),
        default=0.0,
    )
    if diameter < 1e-12:
        return [0.0] * bins
    histogram = [0.0] * bins
    for left in range(len(points)):
        for right in range(left):
            position = min(bins - 1.0, max(0.0, math.dist(points[left], points[right]) / diameter * (bins - 1)))
            lower = int(math.floor(position))
            upper = min(bins - 1, lower + 1)
            fraction = position - lower
            histogram[lower] += 1.0 - fraction
            histogram[upper] += fraction
    total = sum(histogram) or 1
    return [value / total for value in histogram]


def _component_count(adjacency: dict[int, list[tuple[int, str]]]) -> int:
    remaining = set(adjacency)
    count = 0
    while remaining:
        count += 1
        stack = [remaining.pop()]
        while stack:
            current = stack.pop()
            for neighbour, _ in adjacency[current]:
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    stack.append(neighbour)
    return count


def describe_normalized_step(path: Path, wl_iterations: int = 3, part_scale: float = 1.0) -> tuple[str, GraphDescriptor]:
    entities = parse_step(path)
    root = solid_root(entities)
    ids = reachable(root, entities)
    counts = Counter(entities[entity_id].kind for entity_id in ids)
    face_ids = sorted(entity_id for entity_id in ids if entities[entity_id].kind == "ADVANCED_FACE")
    edge_faces: dict[int, list[int]] = defaultdict(list)
    node_labels: dict[int, str] = {}
    family_node_labels: dict[int, str] = {}
    surface_histogram: Counter[str] = Counter()
    curve_histogram: Counter[str] = Counter()
    unknown_curve_uses = 0

    for face_id in face_ids:
        edge_ids = _face_edge_curves(face_id, entities)
        for edge_id in edge_ids:
            edge_faces[edge_id].append(face_id)
            curve_kind = _curve_for_edge(edge_id, entities).kind
            curve_histogram[curve_kind] += 1
            unknown_curve_uses += curve_kind == "UNKNOWN_CURVE"
        surface = _surface_for_face(face_id, entities)
        surface_histogram[surface.kind] += 1
        bound_count = sum(
            _entity_kind(ref, entities) in {"FACE_BOUND", "FACE_OUTER_BOUND"}
            for ref in entities[face_id].refs
        )
        base_label = f"{surface.kind}|b={min(bound_count, 4)}|d={min(len(set(edge_ids)), 12)}"
        node_labels[face_id] = f"{base_label}|p={_parameter_token(surface, part_scale, False)}"
        family_node_labels[face_id] = f"{base_label}|p={_parameter_token(surface, part_scale, True)}"

    adjacency: dict[int, list[tuple[int, str]]] = {face_id: [] for face_id in face_ids}
    family_adjacency: dict[int, list[tuple[int, str]]] = {face_id: [] for face_id in face_ids}
    shared_edges = boundary_edges = seam_edges = 0
    for edge_id, attached in edge_faces.items():
        unique_faces = sorted(set(attached))
        curve = _curve_for_edge(edge_id, entities)
        curve_kind = f"{curve.kind}|p={_parameter_token(curve, part_scale, False)}"
        family_curve_kind = f"{curve.kind}|p={_parameter_token(curve, part_scale, True)}"
        if len(unique_faces) == 1:
            if len(attached) > 1:
                seam_edges += 1
                adjacency[unique_faces[0]].append((unique_faces[0], curve_kind + "|SEAM"))
                family_adjacency[unique_faces[0]].append((unique_faces[0], family_curve_kind + "|SEAM"))
            else:
                boundary_edges += 1
        for index, left in enumerate(unique_faces):
            for right in unique_faces[index + 1:]:
                adjacency[left].append((right, curve_kind))
                adjacency[right].append((left, curve_kind))
                family_adjacency[left].append((right, family_curve_kind))
                family_adjacency[right].append((left, family_curve_kind))
                shared_edges += 1

    points = _vertex_points(ids, entities)
    compact_counts = {
        key: counts[key]
        for key in (
            "ADVANCED_FACE", "EDGE_CURVE", "ORIENTED_EDGE", "VERTEX_POINT",
            "EDGE_LOOP", "FACE_BOUND", "FACE_OUTER_BOUND", "CLOSED_SHELL",
        )
    }
    return solid_label(entities, root), GraphDescriptor(
        counts=compact_counts,
        surface_histogram=dict(surface_histogram),
        curve_histogram=dict(curve_histogram),
        wl_histogram=dict(_wl_histogram(node_labels, adjacency, wl_iterations)),
        wl_family_histogram=dict(_wl_histogram(family_node_labels, family_adjacency, wl_iterations)),
        distance_histogram=_distance_histogram(points),
        graph={
            "nodes": len(face_ids),
            "shared_edges": shared_edges,
            "boundary_edges": boundary_edges,
            "seam_edges": seam_edges,
            "connected_components": _component_count(adjacency),
            "vertex_points": len(points),
            "unknown_surface_uses": surface_histogram["UNKNOWN_SURFACE"],
            "unknown_curve_uses": unknown_curve_uses,
        },
    )
