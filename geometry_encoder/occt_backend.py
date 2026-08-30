"""Thin Python wrapper around the installed Open CASCADE DRAW executable."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ExactProperties:
    index: int
    shape_name: str
    volume: float
    area: float
    edge_length: float
    center: tuple[float, float, float]
    moments: tuple[float, float, float]
    bbox: tuple[float, float, float]
    vertices: int
    edges: int
    wires: int
    faces: int
    shells: int
    solids: int

    def to_dict(self) -> dict:
        return asdict(self)


def find_drawexe(explicit: Path | None = None) -> Path:
    candidates = [
        explicit,
        Path(shutil.which("DRAWEXE") or "") if shutil.which("DRAWEXE") else None,
        Path(r"C:\msys64\ucrt64\bin\DRAWEXE.exe"),
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate.resolve()
    raise RuntimeError(
        "Open CASCADE DRAWEXE was not found. Install OCCT/FreeCAD or pass --drawexe."
    )


def _tcl_path(path: Path) -> str:
    value = path.resolve().as_posix()
    if "{" in value or "}" in value:
        raise ValueError(f"Unsupported brace in path: {path}")
    return "{" + value + "}"


def _run_draw(drawexe: Path, script: str, timeout: int = 900) -> str:
    with tempfile.TemporaryDirectory(prefix="step_encoder_") as folder:
        script_path = Path(folder) / "job.tcl"
        script_path.write_text(script, encoding="utf-8")
        environment = os.environ.copy()
        environment.setdefault("CSF_OCCTResourcePath", str(drawexe.parent.parent / "share" / "opencascade" / "resources"))
        completed = subprocess.run(
            [str(drawexe), "-b", "-f", str(script_path)],
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            env=environment,
            check=False,
        )
    if completed.returncode != 0 or "An exception was caught" in completed.stdout:
        tail = completed.stdout[-4000:]
        raise RuntimeError(f"Open CASCADE job failed (exit {completed.returncode}):\n{tail}")
    return completed.stdout


def _mass(block: str, section: str) -> float:
    match = re.search(rf"@@{section}_BEGIN\s*(.*?)@@{section}_END", block, re.S)
    if not match:
        raise ValueError(f"Missing {section} output")
    value = re.search(r"Mass\s*:\s*([-+0-9.eE]+)", match.group(1))
    return float(value.group(1)) if value else 0.0


def _vector(block: str, heading: str) -> tuple[float, float, float]:
    match = re.search(
        rf"{re.escape(heading)}\s*:\s*.*?X\s*=\s*([-+0-9.eE]+).*?Y\s*=\s*([-+0-9.eE]+).*?Z\s*=\s*([-+0-9.eE]+)",
        block,
        re.S,
    )
    return tuple(map(float, match.groups())) if match else (0.0, 0.0, 0.0)


def _moments(block: str) -> tuple[float, float, float]:
    match = re.search(
        r"Moments\s*:.*?IX\s*=\s*([-+0-9.eE]+).*?IY\s*=\s*([-+0-9.eE]+).*?IZ\s*=\s*([-+0-9.eE]+)",
        block,
        re.S,
    )
    return tuple(sorted(map(float, match.groups()), reverse=True)) if match else (0.0, 0.0, 0.0)


def _shape_count(block: str, item: str) -> int:
    match = re.search(rf"^\s*{re.escape(item)}\s*:\s*(\d+)", block, re.M)
    return int(match.group(1)) if match else 0


def inspect_and_normalize(
    source: Path,
    cache_dir: Path,
    drawexe: Path,
) -> list[ExactProperties]:
    """Import once and write per-solid STEP for review plus exact native B-Rep for computation."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    for pattern in ("part_*.step", "part_*.brep"):
        for stale in cache_dir.glob(pattern):
            stale.unlink()
    source_tcl = _tcl_path(source)
    cache_tcl = _tcl_path(cache_dir)
    script = f"""
pload ALL
NewDocument D
ReadStep D {source_tcl}
XGetOneShape model D
set solidNames [explode model So]
puts "@@SOLID_COUNT [llength $solidNames]"
set index 0
foreach shape $solidNames {{
  incr index
  puts "@@PART_BEGIN $index $shape"
  puts "@@VPROPS_BEGIN"
  puts [vprops $shape 1.e-9 -full]
  puts "@@VPROPS_END"
  puts "@@SPROPS_BEGIN"
  puts [sprops $shape 1.e-9 -full]
  puts "@@SPROPS_END"
  puts "@@LPROPS_BEGIN"
  puts [lprops $shape -full]
  puts "@@LPROPS_END"
  bounding $shape -noTriangulation -save bx0 by0 bz0 bx1 by1 bz1
  puts "@@BBOX [dval bx1-bx0] [dval by1-by0] [dval bz1-bz0]"
  puts "@@NBSHAPES_BEGIN"
  puts [nbshapes $shape]
  puts "@@NBSHAPES_END"
  puts "@@PART_END"
}}
newmodel
set index 0
foreach shape $solidNames {{
  incr index
  set stepname [format "%s/part_%04d.step" {cache_tcl} $index]
  set brepname [format "%s/part_%04d.brep" {cache_tcl} $index]
  bsave $shape $brepname
  stepwrite 0 $shape $stepname
  puts "@@NORMALIZED $index $stepname $brepname"
  newmodel
}}
"""
    output = _run_draw(drawexe, script, timeout=7200)
    count_match = re.search(r"@@SOLID_COUNT\s+(\d+)", output)
    if not count_match:
        raise RuntimeError("OCCT did not report the number of solids")
    expected = int(count_match.group(1))
    properties: list[ExactProperties] = []
    for match in re.finditer(r"@@PART_BEGIN\s+(\d+)\s+(\S+)\s*(.*?)@@PART_END", output, re.S):
        index, shape_name, block = int(match.group(1)), match.group(2), match.group(3)
        v_match = re.search(r"@@VPROPS_BEGIN\s*(.*?)@@VPROPS_END", block, re.S)
        v_block = v_match.group(1) if v_match else ""
        bbox_match = re.search(r"@@BBOX\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)", block)
        bbox = tuple(sorted(map(abs, map(float, bbox_match.groups())), reverse=True)) if bbox_match else (0.0, 0.0, 0.0)
        properties.append(ExactProperties(
            index=index,
            shape_name=shape_name,
            volume=_mass(block, "VPROPS"),
            area=_mass(block, "SPROPS"),
            edge_length=_mass(block, "LPROPS"),
            center=_vector(v_block, "Center of gravity"),
            moments=_moments(v_block),
            bbox=bbox,
            vertices=_shape_count(block, "VERTEX"),
            edges=_shape_count(block, "EDGE"),
            wires=_shape_count(block, "WIRE"),
            faces=_shape_count(block, "FACE"),
            shells=_shape_count(block, "SHELL"),
            solids=_shape_count(block, "SOLID"),
        ))
    normalized = sorted(cache_dir.glob("part_*.step"))
    native_breps = sorted(cache_dir.glob("part_*.brep"))
    if len(properties) != expected or len(normalized) != expected or len(native_breps) != expected:
        raise RuntimeError(
            f"OCCT expected {expected} solids, parsed {len(properties)} properties, "
            f"wrote {len(normalized)} STEP and {len(native_breps)} B-Rep files.\n"
            f"OCCT output tail:\n{output[-5000:]}"
        )
    return properties


def export_groups(
    source: Path,
    groups: dict[int, list[int]],
    output_dir: Path,
    drawexe: Path,
) -> list[dict]:
    """Export each cluster using OCCT, preserving exact B-Rep geometry."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("group_*.step"):
        stale.unlink()
    manifest = output_dir / "manifest.json"
    if manifest.exists():
        manifest.unlink()
    lines = [
        "pload ALL",
        "NewDocument D",
        f"ReadStep D {_tcl_path(source)}",
        "XGetOneShape model D",
        "set solidNames [explode model So]",
    ]
    destinations: list[tuple[int, Path, int]] = []
    for group_id, indices in sorted(groups.items()):
        shape_names = " ".join(f"model_{index}" for index in indices)
        group_name = f"grouped_{group_id:03d}"
        destination = output_dir / f"group_{group_id:03d}_{len(indices)}_solids.step"
        lines.extend([
            f"compound {shape_names} {group_name}",
            "newmodel",
            f"stepwrite 0 {group_name} {_tcl_path(destination)}",
            f"puts \"@@GROUP_WRITTEN {group_id} {len(indices)}\"",
        ])
        destinations.append((group_id, destination, len(indices)))
    output = _run_draw(drawexe, "\n".join(lines))
    written = {int(value) for value in re.findall(r"@@GROUP_WRITTEN\s+(\d+)", output)}
    if written != set(groups):
        raise RuntimeError(f"OCCT did not confirm every group export: {sorted(written)}")
    return [
        {"group": group_id, "solid_count": count, "file": destination.name, "bytes": destination.stat().st_size}
        for group_id, destination, count in destinations
    ]


def validate_group_steps(
    files: list[Path], expected_counts: list[int], drawexe: Path,
    expected_volumes: list[float] | None = None,
    volume_relative_tolerance: float = 1e-6,
) -> list[dict]:
    """Re-import every generated STEP file and run OCCT BRepCheck."""
    if len(files) != len(expected_counts):
        raise ValueError("files and expected_counts must have equal length")
    if expected_volumes is not None and len(files) != len(expected_volumes):
        raise ValueError("files and expected_volumes must have equal length")
    lines = ["pload ALL"]
    for index, path in enumerate(files, 1):
        lines.extend([
            f"NewDocument V{index}",
            f"ReadStep V{index} {_tcl_path(path)}",
            f"XGetOneShape check_{index} V{index}",
            f"puts \"@@NBSHAPES_BEGIN {index}\"",
            f"puts [nbshapes check_{index} -t]",
            f"puts \"@@NBSHAPES_END {index}\"",
            f"puts \"@@VOLUME_BEGIN {index}\"",
            f"puts [vprops check_{index} 1.e-9 -full]",
            f"puts \"@@VOLUME_END {index}\"",
            f"puts \"@@CHECK_BEGIN {index}\"",
            f"puts [checkshape check_{index}]",
            f"puts \"@@CHECK_END {index}\"",
        ])
    output = _run_draw(drawexe, "\n".join(lines))
    results = []
    for index, path in enumerate(files, 1):
        match = re.search(rf"@@CHECK_BEGIN\s+{index}\s*(.*?)@@CHECK_END\s+{index}", output, re.S)
        detail = match.group(1).strip() if match else "missing validation output"
        count_block = re.search(rf"@@NBSHAPES_BEGIN\s+{index}\s*(.*?)@@NBSHAPES_END\s+{index}", output, re.S)
        count_match = re.search(r"^\s*SOLID\s*:\s*(\d+)", count_block.group(1), re.M) if count_block else None
        actual_count = int(count_match.group(1)) if count_match else -1
        volume_block = re.search(rf"@@VOLUME_BEGIN\s+{index}\s*(.*?)@@VOLUME_END\s+{index}", output, re.S)
        volume_match = re.search(r"Mass\s*:\s*([-+0-9.eE]+)", volume_block.group(1)) if volume_block else None
        actual_volume = float(volume_match.group(1)) if volume_match else float("nan")
        expected_volume = expected_volumes[index - 1] if expected_volumes is not None else actual_volume
        volume_relative_error = abs(actual_volume - expected_volume) / max(abs(expected_volume), 1e-15)
        volume_valid = volume_relative_error <= volume_relative_tolerance
        shape_valid = "valid" in detail.lower() and "faulty" not in detail.lower() and "invalid" not in detail.lower()
        valid = shape_valid and actual_count == expected_counts[index - 1] and volume_valid
        results.append({
            "file": path.name, "valid": valid, "shape_valid": shape_valid,
            "expected_solid_count": expected_counts[index - 1], "actual_solid_count": actual_count,
            "expected_volume": expected_volume, "actual_volume": actual_volume,
            "volume_relative_error": volume_relative_error, "volume_valid": volume_valid,
            "volume_relative_tolerance": volume_relative_tolerance,
            "detail": detail[-500:],
        })
    return results


def verify_rigid_pairs_with_boolean(
    source: Path,
    verifications: list,
    part_volumes: dict[int, float],
    drawexe: Path,
    relative_tolerance: float = 1e-6,
    workers: int = 4,
    normalized_dir: Path | None = None,
    result_callback=None,
) -> list:
    """Independently verify aligned pairs using bidirectional OCCT Boolean cuts."""
    aligned = [item for item in verifications if item.transform is not None]
    if not aligned:
        return verifications

    def run_batch(batch: list) -> str:
        if normalized_dir is None:
            lines = [
                "pload ALL", "NewDocument PrecisionDoc", f"ReadStep PrecisionDoc {_tcl_path(source)}",
                "XGetOneShape precision_model PrecisionDoc", "explode precision_model So",
            ]
        else:
            lines = ["pload ALL"]
        for job, item in enumerate(batch, 1):
            transform = item.transform
            axis = transform.axis
            translation = transform.translation
            if normalized_dir is None:
                lines.extend([
                    f"tcopy precision_model_{item.reference_part} aligned_{job}",
                    f"tcopy precision_model_{item.candidate_part} candidate_{job}",
                ])
            else:
                reference = normalized_dir / f"part_{item.reference_part:04d}.brep"
                candidate = normalized_dir / f"part_{item.candidate_part:04d}.brep"
                lines.extend([
                    f"restore {_tcl_path(reference)} reference_{job}",
                    f"restore {_tcl_path(candidate)} candidate_{job}",
                    f"tcopy reference_{job} aligned_{job}",
                ])
            if abs(transform.angle_degrees) > 1e-10:
                lines.append(
                    f"trotate aligned_{job} 0 0 0 {axis[0]:.17g} {axis[1]:.17g} {axis[2]:.17g} "
                    f"{transform.angle_degrees:.17g}"
                )
            lines.extend([
                f"ttranslate aligned_{job} {translation[0]:.17g} {translation[1]:.17g} {translation[2]:.17g}",
                f"bcut forward_{job} aligned_{job} candidate_{job}",
                f"bcut reverse_{job} candidate_{job} aligned_{job}",
                f"puts \"@@FORWARD_BEGIN {job}\"", f"puts [vprops forward_{job} 1.e-9 -full]",
                f"puts \"@@FORWARD_END {job}\"",
                f"puts \"@@REVERSE_BEGIN {job}\"", f"puts [vprops reverse_{job} 1.e-9 -full]",
                f"puts \"@@REVERSE_END {job}\"",
            ])
        timeout = (120 + 20 * (len(batch) - 1)) if normalized_dir is not None else 1800
        output = _run_draw(drawexe, "\n".join(lines), timeout=timeout)
        return output

    worker_count = max(1, min(int(workers), len(aligned)))
    if normalized_dir is None:
        batches = [aligned[offset::worker_count] for offset in range(worker_count)]
    else:
        # Amortize the expensive assembly import, then recursively isolate a batch
        # if a pathological B-Rep fails or times out. Only the failing singleton is
        # conservatively rejected; successful siblings retain their exact evidence.
        batch_size = 4
        batches = [aligned[offset:offset + batch_size] for offset in range(0, len(aligned), batch_size)]

    def run_resilient(batch: list) -> list[tuple[list, str | None, str | None]]:
        try:
            return [(batch, run_batch(batch), None)]
        except Exception as exc:
            if len(batch) == 1:
                return [(batch, None, f"{type(exc).__name__}: {exc}"[-1000:])]
            middle = len(batch) // 2
            return run_resilient(batch[:middle]) + run_resilient(batch[middle:])

    def apply_batch_result(batch: list, output: str | None, error: str | None) -> None:
        if error is not None or output is None:
            for item in batch:
                item.status = "boolean_failed"
                item.reason = f"Isolated OCCT Boolean batch failed: {error}"
                item.passed = False
        else:
            for job, item in enumerate(batch, 1):
                forward_block = re.search(rf"@@FORWARD_BEGIN\s+{job}\s*(.*?)@@FORWARD_END\s+{job}", output, re.S)
                reverse_block = re.search(rf"@@REVERSE_BEGIN\s+{job}\s*(.*?)@@REVERSE_END\s+{job}", output, re.S)
                forward_mass = re.search(r"Mass\s*:\s*([-+0-9.eE]+)", forward_block.group(1)) if forward_block else None
                reverse_mass = re.search(r"Mass\s*:\s*([-+0-9.eE]+)", reverse_block.group(1)) if reverse_block else None
                if not forward_mass or not reverse_mass:
                    item.status = "boolean_failed"
                    item.reason = "OCCT Boolean difference did not produce measurable results"
                    item.passed = False
                    continue
                item.forward_difference_volume = abs(float(forward_mass.group(1)))
                item.reverse_difference_volume = abs(float(reverse_mass.group(1)))
                reference_volume = max(
                    abs(part_volumes[item.reference_part]), abs(part_volumes[item.candidate_part]), 1e-15
                )
                item.boolean_relative_error = max(
                    item.forward_difference_volume, item.reverse_difference_volume
                ) / reference_volume
                item.passed = item.boolean_relative_error <= relative_tolerance
                item.status = "verified" if item.passed else "different"
                item.reason = (
                    "Rigid congruence and bidirectional Boolean difference passed"
                    if item.passed
                    else "Bidirectional Boolean difference exceeds tolerance"
                )
        if result_callback is not None:
            result_callback(batch)

    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="occt_boolean") as executor:
        futures = [executor.submit(run_resilient, batch) for batch in batches]
        for future in as_completed(futures):
            for batch, output, error in future.result():
                apply_batch_result(batch, output, error)
    return verifications
