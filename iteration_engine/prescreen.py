"""Cheap, explainable metadata screening before expensive CAD classification."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, asdict
from typing import Iterable, Mapping


SECTORS = {
    "additive_manufacturing": ("3d print", "printer", "extruder", "bioprint", "fff", "fdm"),
    "robotics_automation": ("robot", "robotic", "manipulator", "actuator", "cobot", "automation"),
    "machine_tools": ("cnc", "machine tool", "milling", "grinding", "scarfing", "spindle"),
    "automotive_mobility": ("vehicle", "automotive", "car", "drivetrain", "helmet", "mobility"),
    "aerospace_turbomachinery": ("aerospace", "turbine", "blade", "fan", "aircraft", "satellite"),
    "biomedical_rehabilitation": ("prosthe", "medical", "rehabilitation", "biomedical", "hand", "wearable"),
    "process_fluid_power": ("hydraulic", "pneumatic", "valve", "pump", "fluid", "gear pump"),
    "scientific_instrumentation": ("instrument", "detector", "fiber robot", "laboratory", "test rig", "sensor"),
    "electronics_electromechanical": ("pcb", "electronics", "electrical", "control board", "mechatronic"),
    "industrial_equipment": ("industrial", "manufacturing", "gearbox", "conveyor", "mechanism", "machine"),
}

DOMAINS = {
    "fastening_joining": ("screw", "bolt", "nut", "washer", "fastener", "rivet"),
    "power_transmission": ("gear", "gearbox", "worm", "rack", "pulley", "belt", "chain", "sprocket"),
    "motion_actuation": ("motor", "servo", "actuator", "stepper", "bearing", "bushing", "shaft", "linear rail"),
    "fluid_handling": ("valve", "pump", "piston", "cylinder", "hydraulic", "pneumatic", "seal", "o-ring"),
    "structure_enclosure": ("frame", "bracket", "plate", "housing", "cover", "enclosure", "mount"),
    "tooling_machining": ("cutter", "drill", "spindle", "tool holder", "grinding", "scarfing"),
    "electrical_control": ("pcb", "connector", "sensor", "switch", "controller", "wiring"),
    "human_interface": ("prosthe", "hand", "finger", "helmet", "wearable", "gripper"),
}

COMPONENTS = {
    "screws_bolts": ("screw", "bolt", "socket cap", "flat head"),
    "nuts_washers": ("nut", "washer", "fastener"),
    "bearings_bushings": ("bearing", "bushing"),
    "gears_racks_worms": ("gear", "pinion", "rack", "worm"),
    "shafts_spindles": ("shaft", "axle", "spindle"),
    "pulleys_belts_chains": ("pulley", "belt", "chain", "sprocket", "cable", "rope"),
    "springs_elastic": ("spring", "elastic"),
    "seals_gaskets": ("seal", "gasket", "o-ring", "oring"),
    "valves_pumps_cylinders": ("valve", "pump", "piston", "cylinder", "hydraulic", "pneumatic"),
    "motors_servos": ("motor", "servo", "actuator", "stepper"),
    "frames_brackets_plates": ("frame", "bracket", "plate", "mount", "rail"),
    "covers_housings": ("cover", "housing", "enclosure", "case", "window"),
    "electronics_connectors": ("pcb", "connector", "sensor", "switch", "controller", "electronics"),
    "wheels_rollers": ("wheel", "roller", "caster"),
    "tools_cutters": ("cutter", "drill", "tool", "grinding", "scarfing"),
}

ASSEMBLY_SIGNALS = {
    "explicit_full_assembly": ("full assembly", "complete assembly", "entire assembly", "assembly model", "assembled", "assemblies"),
    "product_structure": ("subassembly", "sub-assembly", "mates", "assembly graph", "product structure"),
    "parts_evidence": ("bill of materials", "bom", "parts list", "all parts", "components"),
    "repetition_evidence": ("repeated", "quantity", "quantities", "fastening", "fasteners", "screws", "bolts", "nuts"),
    "assembly_file": (".sldasm", ".iam", ".asm", "assembly.step", "assembly.stp", "assem.step"),
}

NEGATIVE_SIGNALS = ("single part", "isolated part", "one component", "individual part", "part-only")
STEP_MARKERS = (
    ".step", ".stp", "step format", "step file", "step assembly", "step assemblies", "step package",
    "step and parasolid",
    "iso-10303", "ap 203", "ap203", "ap 214", "ap214", "ap 242", "ap242",
)


@dataclass(frozen=True)
class PrescreenResult:
    candidate_id: str
    manufacturing_sector: str
    sector_confidence: str
    engineering_domains: list[str]
    possible_components: list[str]
    assembly_confidence: str
    assembly_score: int
    decision: str
    evidence: list[str]
    caveats: list[str]


def _hits(text: str, terms: Iterable[str]) -> list[str]:
    return sorted({term for term in terms if term in text})


def _ranked_labels(text: str, taxonomy: Mapping[str, Iterable[str]]) -> list[tuple[str, int, list[str]]]:
    ranked = []
    for label, terms in taxonomy.items():
        found = _hits(text, terms)
        if found:
            ranked.append((label, len(found), found))
    return sorted(ranked, key=lambda item: (-item[1], item[0]))


def _quantity_evidence(text: str) -> list[str]:
    expressions = re.findall(
        r"\b(?:\d{1,5}\s*(?:parts?|components?|units?|screws?|bolts?|nuts?|robots?)|"
        r"(?:qty|quantity)\s*[:=]?\s*\d{1,5})\b",
        text,
    )
    return sorted(set(expressions))[:8]


def prescreen_candidate(candidate: Mapping[str, object]) -> PrescreenResult:
    """Classify metadata with transparent lexical evidence; never claims geometric truth."""
    values = [
        candidate.get("title", ""), candidate.get("description", ""),
        candidate.get("filename", ""), candidate.get("file_names", ""),
        candidate.get("categories", ""), candidate.get("bom_summary", ""),
    ]
    text = " ".join(str(value) for value in values if value).casefold()
    sector_rank = _ranked_labels(text, SECTORS)
    domain_rank = _ranked_labels(text, DOMAINS)
    component_rank = _ranked_labels(text, COMPONENTS)
    sector = sector_rank[0][0] if sector_rank else "unknown"
    sector_confidence = "high" if sector_rank and sector_rank[0][1] >= 3 else "medium" if sector_rank else "low"

    evidence: list[str] = []
    assembly_score = 0
    for name, terms in ASSEMBLY_SIGNALS.items():
        found = _hits(text, terms)
        if found:
            weight = 3 if name == "explicit_full_assembly" else 2
            assembly_score += weight
            evidence.append(f"{name}:" + "|".join(found[:4]))
    quantity = _quantity_evidence(text)
    if quantity:
        assembly_score += 2
        evidence.append("quantity:" + "|".join(quantity))
    if _hits(text, STEP_MARKERS):
        assembly_score += 2
        evidence.append("step_brep_format")
    if _hits(text, NEGATIVE_SIGNALS):
        assembly_score -= 6
        evidence.append("negative_single_part_signal")

    remote = candidate.get("remote_probe") or {}
    if isinstance(remote, Mapping):
        product_count = int(remote.get("product_count", 0) or 0)
        occurrence_count = int(remote.get("assembly_occurrence_count", 0) or 0)
        solid_count = int(remote.get("solid_marker_count", 0) or 0)
        if product_count >= 2 or occurrence_count >= 1:
            assembly_score += 5
            evidence.append(f"step_structure:products={product_count},occurrences={occurrence_count}")
        elif solid_count >= 10:
            assembly_score += 3
            evidence.append(f"step_structure:solid_markers={solid_count}")

    access = str(candidate.get("access_status", "unknown"))
    license_value = str(candidate.get("license", "unknown"))
    has_step = bool(_hits(text, STEP_MARKERS))
    caveats: list[str] = []
    if license_value.casefold() in {"", "unknown", "unspecified", "none"}:
        caveats.append("license_requires_review")
    if access in {"login_required", "manual", "blocked", "unknown"}:
        caveats.append(f"access_{access}")
    if not has_step:
        caveats.append("no_step_brep_evidence")

    if not has_step or assembly_score < 1:
        decision = "reject_or_metadata_only"
    elif "license_requires_review" in caveats:
        decision = "manual_license_review"
    elif assembly_score >= 8 and access in {"verified_direct", "verified_api", "public"}:
        decision = "priority_download"
    elif assembly_score >= 5:
        decision = "metadata_first"
    else:
        decision = "manual_assembly_review"
    confidence = "high" if assembly_score >= 8 else "medium" if assembly_score >= 5 else "low"

    return PrescreenResult(
        candidate_id=str(candidate.get("id", "")),
        manufacturing_sector=sector,
        sector_confidence=sector_confidence,
        engineering_domains=[item[0] for item in domain_rank[:4]],
        possible_components=[item[0] for item in component_rank],
        assembly_confidence=confidence,
        assembly_score=assembly_score,
        decision=decision,
        evidence=evidence,
        caveats=caveats,
    )


def summarize_prescreen(results: Iterable[PrescreenResult]) -> dict:
    rows = list(results)
    return {
        "candidate_count": len(rows),
        "manufacturing_sectors": dict(sorted(Counter(row.manufacturing_sector for row in rows).items())),
        "engineering_domains": dict(sorted(Counter(value for row in rows for value in row.engineering_domains).items())),
        "possible_components": dict(sorted(Counter(value for row in rows for value in row.possible_components).items())),
        "assembly_confidence": dict(sorted(Counter(row.assembly_confidence for row in rows).items())),
        "decisions": dict(sorted(Counter(row.decision for row in rows).items())),
        "results": [asdict(row) for row in rows],
    }
