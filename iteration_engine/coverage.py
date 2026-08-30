"""Measure semantic-name and coarse geometry coverage of the local corpus."""

from __future__ import annotations

import csv
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from .io import atomic_write_json, utc_now


PRODUCT_NAME = re.compile(r"\bPRODUCT\s*\(\s*'((?:''|[^'])*)'", re.IGNORECASE)


def extract_product_names(path: Path) -> list[str]:
    text = path.read_text(encoding="latin-1", errors="ignore")
    return sorted({match.replace("''", "'").strip() for match in PRODUCT_NAME.findall(text)
                   if match.strip()})


def semantic_matches(texts: Iterable[str], taxonomy: dict[str, list[str]]) -> dict[str, list[str]]:
    normalized = "\n".join(texts).casefold()
    return {
        entity_type: sorted({keyword for keyword in keywords if keyword.casefold() in normalized})
        for entity_type, keywords in taxonomy.items()
    }


def _log_bin(value: str, width: float = 0.5) -> int:
    number = max(float(value), 1e-18)
    return math.floor(math.log10(number) / width)


def _count_bin(value: str, width: int) -> int:
    return int(float(value)) // width


def geometry_signature(row: dict[str, str]) -> str:
    """Coarse, stable coverage signature; not an equivalence classifier."""
    return ":".join(map(str, (
        _log_bin(row["volume"]), _log_bin(row["surface_area"]),
        _count_bin(row["faces"], 4), _count_bin(row["edges"], 8),
        _count_bin(row["vertices"], 8),
    )))


def build_coverage(
    assemblies: Path | Iterable[Path],
    runs: Path | Iterable[Path],
    taxonomy: dict[str, list[str]],
    output: Path,
    minimum_sources_per_type: int = 1,
) -> dict:
    assembly_roots = [assemblies] if isinstance(assemblies, Path) else list(assemblies)
    run_roots = [runs] if isinstance(runs, Path) else list(runs)
    type_sources: dict[str, set[str]] = defaultdict(set)
    type_keywords: dict[str, set[str]] = defaultdict(set)
    product_names: dict[str, list[str]] = {}
    for assembly_root in assembly_roots:
        if not assembly_root.exists():
            continue
        for path in sorted((*assembly_root.rglob("*.step"), *assembly_root.rglob("*.stp"))):
            names = extract_product_names(path)
            source_id = path.stem
            product_names[str(path.resolve())] = names
            matches = semantic_matches([source_id, *names], taxonomy)
            for entity_type, keywords in matches.items():
                if keywords:
                    type_sources[entity_type].add(source_id)
                    type_keywords[entity_type].update(keywords)

    signatures: Counter[str] = Counter()
    signature_sources: dict[str, set[str]] = defaultdict(set)
    for run_root in run_roots:
        if not run_root.exists():
            continue
        for parts_path in sorted(run_root.glob("*/parts.csv")):
            with parts_path.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    signature = geometry_signature(row)
                    signatures[signature] += 1
                    signature_sources[signature].add(parts_path.parent.name)

    semantic = []
    for entity_type in sorted(taxonomy):
        sources = sorted(type_sources[entity_type])
        semantic.append({
            "type": entity_type,
            "covered": bool(sources),
            "source_count": len(sources),
            "sources": sources,
            "matched_keywords": sorted(type_keywords[entity_type]),
        })
    missing = [row["type"] for row in semantic if not row["covered"]]
    undercovered = [row["type"] for row in semantic
                    if row["covered"] and row["source_count"] < minimum_sources_per_type]
    result = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "definition": {
            "semantic": "Keyword evidence from STEP PRODUCT names and source identifiers; not inferred function.",
            "geometry": "Coarse log-size/topology bins used only to measure corpus diversity.",
        },
        "semantic_types": semantic,
        "covered_semantic_types": sum(row["covered"] for row in semantic),
        "minimum_sources_per_type": minimum_sources_per_type,
        "missing_semantic_types": missing,
        "undercovered_semantic_types": undercovered,
        "coverage_gaps": [*missing, *undercovered],
        "assembly_files_scanned": len(product_names),
        "product_name_count": sum(len(names) for names in product_names.values()),
        "classified_geometry_signatures": len(signatures),
        "rare_geometry_signatures": sum(count <= 2 for count in signatures.values()),
        "geometry_signatures": [
            {"signature": signature, "part_count": count,
             "source_count": len(signature_sources[signature])}
            for signature, count in sorted(signatures.items())
        ],
    }
    atomic_write_json(output, result)
    return result
