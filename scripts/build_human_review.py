#!/usr/bin/env python3
"""Build a risk-based visual review queue from completed corpus runs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import html
import json
import math
import random
import re
import struct
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geometry_encoder.occt_backend import _run_draw, _tcl_path, find_drawexe


def stream_cross_rows(path: Path, max_near: int, random_pool_size: int,
                      seed: str) -> tuple[list[dict], list[dict], int]:
    """Keep only high-risk and deterministic-random cross-group rows in memory."""
    nearest: list[tuple[float, int, int, int, dict]] = []
    random_pool: list[tuple[int, int, dict]] = []
    cross_count = 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for serial, row in enumerate(csv.DictReader(handle)):
            if str(row["same_group"]).lower() not in {"false", "0"}:
                continue
            cross_count += 1
            part_a, part_b = int(row["part_a"]), int(row["part_b"])
            similarity = float(row["similarity"])
            near_entry = (similarity, -part_a, -part_b, serial, row)
            if len(nearest) < max_near:
                heapq.heappush(nearest, near_entry)
            elif max_near and near_entry > nearest[0]:
                heapq.heapreplace(nearest, near_entry)

            priority = int.from_bytes(hashlib.sha256(
                f"{seed}:{part_a}:{part_b}".encode("utf-8")
            ).digest()[:8], "big")
            random_entry = (-priority, serial, row)
            if len(random_pool) < random_pool_size:
                heapq.heappush(random_pool, random_entry)
            elif random_pool_size and random_entry > random_pool[0]:
                heapq.heapreplace(random_pool, random_entry)
    nearest_rows = [item[-1] for item in sorted(
        nearest, key=lambda item: (-item[0], -item[1], -item[2])
    )]
    random_rows = [item[-1] for item in sorted(
        random_pool, key=lambda item: -item[0]
    )]
    return nearest_rows, random_rows, cross_count


def select_tasks(run_dir: Path, max_groups: int, max_near: int, cross_sample: int,
                 internal_sample: int, max_unresolved: int, max_boundary: int) -> list[dict]:
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    groups = report["groups"]
    dataset_id = run_dir.name
    tasks: list[dict] = []

    multi = [group for group in groups if group["part_count"] > 1]
    multi.sort(key=lambda group: (group["minimum_internal_similarity"], -group["part_count"]))
    for group in multi[:max_groups]:
        tasks.append({
            "dataset_id": dataset_id, "item_type": "group_merge", "group_a": group["group"],
            "group_b": "", "part_ids": group["parts"][:3], "group_size": group["part_count"],
            "predicted_relation": "same", "risk_score": 1.0 - group["minimum_internal_similarity"],
            "selection_stratum": "high_risk_internal", "inclusion_probability": 1.0,
            "evidence": f"min_internal_similarity={group['minimum_internal_similarity']:.6f}",
        })

    precision_path = run_dir / "precision_report.json"
    if precision_path.is_file():
        precision = json.loads(precision_path.read_text(encoding="utf-8"))
        pairs = precision.get("pairs", [])
        unresolved = [pair for pair in pairs if pair.get("status") in {"alignment_failed", "boolean_failed"}]
        for pair in unresolved[:max_unresolved]:
            tasks.append({
                "dataset_id": dataset_id, "item_type": "unresolved_precision", "group_a": pair.get("group", ""),
                "group_b": "", "part_ids": [pair["reference_part"], pair["candidate_part"]],
                "group_size": 2, "predicted_relation": "different", "risk_score": 1.0,
                "selection_stratum": "unresolved_precision", "inclusion_probability": 1.0,
                "evidence": pair.get("reason", "precision verification unresolved"),
            })
        boundary = [pair for pair in pairs if pair.get("status") == "different"]
        boundary.sort(key=lambda pair: float(pair.get("boolean_relative_error") or float("inf")))
        for pair in boundary[:max_boundary]:
            tasks.append({
                "dataset_id": dataset_id, "item_type": "boolean_boundary_split",
                "group_a": pair.get("group", ""), "group_b": "",
                "part_ids": [pair["reference_part"], pair["candidate_part"]],
                "group_size": 2, "predicted_relation": "different",
                "risk_score": 1.0 / max(float(pair.get("boolean_relative_error") or 1.0), 1e-15),
                "selection_stratum": "boolean_boundary_split", "inclusion_probability": 1.0,
                "evidence": f"boolean_relative_error={pair.get('boolean_relative_error')}",
            })

    seed = f"MBD-Pre-review-v1:{dataset_id}"
    pool_size = max(64, cross_sample * 20 + max_near + max_unresolved + max_boundary)
    nearest, random_pool, cross_count = stream_cross_rows(
        run_dir / "similarities.csv", max_near, pool_size, seed
    )
    for row in nearest:
        tasks.append({
            "dataset_id": dataset_id, "item_type": "near_miss_pair", "group_a": "",
            "group_b": "", "part_ids": [int(row["part_a"]), int(row["part_b"])],
            "group_size": 2, "predicted_relation": "different",
            "risk_score": float(row["similarity"]), "selection_stratum": "high_risk_cross_group",
            "inclusion_probability": 1.0,
            "evidence": f"cross_group_similarity={float(row['similarity']):.6f}",
        })

    chosen_pairs = {tuple(sorted(task["part_ids"])) for task in tasks if len(task["part_ids"]) == 2}
    rng = random.Random(f"MBD-Pre-review-v1:{dataset_id}")
    random_rows = []
    for row in random_pool:
        pair = tuple(sorted((int(row["part_a"]), int(row["part_b"]))))
        if pair not in chosen_pairs:
            random_rows.append(row)
        if len(random_rows) == cross_sample:
            break
    for row in random_rows:
        tasks.append({
            "dataset_id": dataset_id, "item_type": "random_cross_pair", "group_a": "",
            "group_b": "", "part_ids": [int(row["part_a"]), int(row["part_b"])],
            "group_size": 2, "predicted_relation": "different", "risk_score": float(row["similarity"]),
            "selection_stratum": "random_cross_baseline",
            "inclusion_probability": min(1.0, cross_sample / max(1, cross_count)),
            "evidence": f"random_cross_similarity={float(row['similarity']):.6f}",
        })
    internal_pairs = [
        (left, right)
        for group in groups if group["part_count"] > 1
        for position, right in enumerate(group["parts"])
        for left in group["parts"][:position]
    ]
    for left, right in rng.sample(internal_pairs, min(internal_sample, len(internal_pairs))):
        tasks.append({
            "dataset_id": dataset_id, "item_type": "random_internal_pair", "group_a": "",
            "group_b": "", "part_ids": [left, right], "group_size": 2,
            "predicted_relation": "same", "risk_score": 0.0,
            "selection_stratum": "random_internal_baseline",
            "inclusion_probability": min(1.0, internal_sample / max(1, len(internal_pairs))),
            "evidence": "random pair from a retained multi-member group",
        })
    priority = {
        "unresolved_precision": 0, "boolean_boundary_split": 1, "group_merge": 2,
        "near_miss_pair": 3, "random_internal_pair": 4, "random_cross_pair": 5,
    }
    tasks.sort(key=lambda task: (priority.get(task["item_type"], 9), -task["risk_score"]))
    deduplicated = []
    seen_pairs = set()
    for task in tasks:
        if len(task["part_ids"]) == 2:
            key = tuple(sorted(task["part_ids"]))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
        deduplicated.append(task)
    return deduplicated


def stl_triangles(path: Path) -> list[tuple[tuple[float, float, float], ...]]:
    data = path.read_bytes()
    triangles = []
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        if 84 + count * 50 == len(data):
            for index in range(count):
                values = struct.unpack_from("<12fH", data, 84 + index * 50)
                triangles.append((values[3:6], values[6:9], values[9:12]))
            return triangles
    for match in re.finditer(
        rb"vertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)", data, re.I
    ):
        point = tuple(float(value) for value in match.groups())
        if len(triangles) == 0 or len(triangles[-1]) == 3:
            triangles.append((point,))
        else:
            triangles[-1] = triangles[-1] + (point,)
    return [triangle for triangle in triangles if len(triangle) == 3]


def render_stl(path: Path, size: int = 240, view: str = "iso") -> Image.Image:
    triangles = stl_triangles(path)
    if not triangles:
        raise ValueError(f"No triangles in {path}")
    stride = max(1, len(triangles) // 40000)
    triangles = triangles[::stride]
    points = np.asarray(triangles, dtype=float)
    flattened = points.reshape(-1, 3)
    center = flattened.mean(axis=0)
    centered = flattened - center
    _, basis = np.linalg.eigh(np.cov(centered, rowvar=False))
    basis = basis[:, ::-1]
    for axis in range(3):
        coordinate = centered @ basis[:, axis]
        skew = float(np.sum(coordinate ** 3))
        if skew < 0:
            basis[:, axis] *= -1
    if np.linalg.det(basis) < 0:
        basis[:, 2] *= -1
    points = ((flattened - center) @ basis).reshape(-1, 3, 3)
    projected = []
    xs, ys = [], []
    for triangle in points:
        face = []
        depth = 0.0
        for x, y, z in triangle:
            if view == "front":
                px, py, point_depth = x, z, y
            elif view == "top":
                px, py, point_depth = x, y, z
            else:
                px = 0.70710678 * (x - y)
                py = 0.40824829 * (x + y) - 0.81649658 * z
                point_depth = x + y + z
            face.append((px, py))
            xs.append(px)
            ys.append(py)
            depth += point_depth
        projected.append((depth / 3.0, face))
    width = max(xs) - min(xs) or 1.0
    height = max(ys) - min(ys) or 1.0
    scale = 0.86 * size / max(width, height)
    cx, cy = (max(xs) + min(xs)) / 2.0, (max(ys) + min(ys)) / 2.0
    image = Image.new("RGB", (size, size), "#f7f8fa")
    draw = ImageDraw.Draw(image)
    for _, face in sorted(projected, key=lambda item: item[0]):
        points = [(size / 2 + (x - cx) * scale, size / 2 - (y - cy) * scale) for x, y in face]
        draw.polygon(points, fill="#a9b8c8", outline="#647789")
    return image


def render_task(task: dict, run_dir: Path, image_path: Path, drawexe: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="mbd_review_") as folder:
        temp = Path(folder)
        lines = ["pload ALL"]
        stls = []
        for position, part_id in enumerate(task["part_ids"], 1):
            step = run_dir / "normalized_parts" / f"part_{part_id:04d}.step"
            stl = temp / f"part_{position}.stl"
            shape = f"shape_{position}"
            document = f"ReviewDoc{position}"
            lines.extend([f"NewDocument {document}", f"ReadStep {document} {_tcl_path(step)}",
                          f"XGetOneShape {shape} {document}", f"incmesh {shape} 0.5",
                          f"writestl {shape} {_tcl_path(stl)} 0", "newmodel"])
            stls.append((part_id, stl))
        _run_draw(drawexe, "\n".join(lines), timeout=900)
        panels = []
        font = ImageFont.load_default()
        for part_id, stl in stls:
            views = [("ISO", render_stl(stl, view="iso")),
                     ("FRONT", render_stl(stl, view="front")),
                     ("TOP", render_stl(stl, view="top"))]
            panel = Image.new("RGB", (240 * len(views), 240), "white")
            for view_index, (view_name, rendered) in enumerate(views):
                panel.paste(rendered, (240 * view_index, 0))
            draw = ImageDraw.Draw(panel)
            for view_index, (view_name, _) in enumerate(views):
                left = 240 * view_index
                draw.rectangle((left, 0, left + 118, 22), fill="#ffffff")
                draw.text((left + 6, 5), f"Part {part_id} · {view_name}", fill="#17202a", font=font)
            panels.append(panel)
        sheet = Image.new("RGB", (720 * len(panels), 240), "white")
        for index, panel in enumerate(panels):
            sheet.paste(panel, (720 * index, 0))
        image_path.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(image_path, optimize=True)


def build_html(tasks: list[dict], destination: Path) -> None:
    labels = {
        "": "--请选择--", "correct_merge": "合并正确", "wrong_merge": "错误合并",
        "missed_merge": "漏合并", "correct_split": "拆分正确", "uncertain": "不确定",
    }
    body = []
    for task in tasks:
        allowed = (["", "correct_merge", "wrong_merge", "uncertain"]
                   if task["predicted_relation"] == "same"
                   else ["", "correct_split", "missed_merge", "uncertain"])
        options = "".join(
            f'<option value="{value}">{labels[value]}</option>' for value in allowed
        )
        links = "　".join(
            f'<a href="../../runs/assembly_corpus/{html.escape(task["dataset_id"])}/normalized_parts/'
            f'part_{int(part_id):04d}.step">Part {int(part_id)} STEP</a>'
            for part_id in task["part_ids"].split(";")
        )
        body.append(f"""
<article data-task="{html.escape(task['task_id'])}">
  <h2>{html.escape(task['task_id'])} · {html.escape(task['dataset_id'])} · {html.escape(task['item_type'])}</h2>
  <img src="{html.escape(task['image'])}" alt="{html.escape(task['task_id'])}">
  <p>预测：<b>{html.escape(task['predicted_relation'])}</b>；组规模：{int(task['group_size'])}；抽样层：{html.escape(task['selection_stratum'])}</p>
  <p>零件：{html.escape(task['part_ids'])}；{html.escape(task['evidence'])}；{links}</p>
  <p>标注：<select>{options}</select>　备注：<input type="text" size="48"></p>
</article>""")
    page = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>MBD-Pre 人工复核联系表</title><style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:24px;background:#eef1f4;color:#17202a}}
header{{position:sticky;top:0;background:#eef1f4;padding:8px 0;z-index:2}} article{{background:white;padding:16px;margin:16px 0;border-radius:10px}}
img{{max-width:100%;border:1px solid #ccd3da}} input,select,button{{font-size:15px;padding:7px}} h2{{font-size:18px}}
</style></head><body><header><h1>MBD-Pre 风险分层人工复核</h1>
<p>共 {len(tasks)} 项。完成选择后点击导出，不需要逐个打开 STEP。　<strong id="progress"></strong></p><button onclick="save()">导出标注 CSV</button></header>
{''.join(body)}<script>
function q(v){{return '"'+String(v).replaceAll('"','""')+'"'}}
function progress(){{let all=[...document.querySelectorAll('article')],done=all.filter(a=>a.querySelector('select').value).length;document.getElementById('progress').textContent=`已判断 ${{done}} / ${{all.length}}`}}
function persist(a){{localStorage.setItem('mbd-review-'+a.dataset.task,JSON.stringify({{label:a.querySelector('select').value,note:a.querySelector('input').value}}));progress()}}
function save(){{let rows=['task_id,human_label,human_note'];document.querySelectorAll('article').forEach(a=>{{rows.push([a.dataset.task,a.querySelector('select').value,a.querySelector('input').value].map(q).join(','))}});let b=new Blob(['\\ufeff'+rows.join('\\n')],{{type:'text/csv;charset=utf-8'}});let x=document.createElement('a');x.href=URL.createObjectURL(b);x.download='human_labels.csv';x.click()}}
document.querySelectorAll('article').forEach(a=>{{let saved=localStorage.getItem('mbd-review-'+a.dataset.task);if(saved){{let v=JSON.parse(saved);a.querySelector('select').value=v.label||'';a.querySelector('input').value=v.note||''}}a.querySelector('select').addEventListener('change',()=>persist(a));a.querySelector('input').addEventListener('input',()=>persist(a))}});progress();
</script></body></html>"""
    destination.write_text(page, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=Path, default=ROOT / "runs" / "assembly_corpus")
    parser.add_argument("--output", type=Path, default=ROOT / "research" / "human_review")
    parser.add_argument("--max-groups-per-run", type=int, default=8)
    parser.add_argument("--max-near-per-run", type=int, default=5)
    parser.add_argument("--random-cross-per-run", type=int, default=2)
    parser.add_argument("--random-internal-per-run", type=int, default=2)
    parser.add_argument("--max-unresolved-per-run", type=int, default=6)
    parser.add_argument("--max-boundary-splits-per-run", type=int, default=4)
    parser.add_argument("--include-nonboolean", action="store_true")
    parser.add_argument("--drawexe", type=Path)
    args = parser.parse_args()
    run_dirs = [path.parent for path in sorted(args.runs.glob("*/report.json"))]
    if not args.include_nonboolean:
        run_dirs = [run_dir for run_dir in run_dirs if
                    json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
                    .get("config", {}).get("precision_mode") == "boolean"]
    tasks = []
    for run_dir in run_dirs:
        tasks.extend(select_tasks(
            run_dir, args.max_groups_per_run, args.max_near_per_run, args.random_cross_per_run,
            args.random_internal_per_run, args.max_unresolved_per_run,
            args.max_boundary_splits_per_run,
        ))
    drawexe = find_drawexe(args.drawexe)
    args.output.mkdir(parents=True, exist_ok=True)
    for index, task in enumerate(tasks, 1):
        task["task_id"] = f"R{index:05d}"
        task["part_ids"] = ";".join(str(value) for value in task["part_ids"])
        image_rel = Path("images") / f"{task['task_id']}.png"
        task["image"] = image_rel.as_posix()
        part_ids = [int(value) for value in task["part_ids"].split(";")]
        task_for_render = dict(task, part_ids=part_ids)
        print(f"[render] {task['task_id']} {task['dataset_id']} {task['item_type']}", flush=True)
        render_task(task_for_render, args.runs / task["dataset_id"], args.output / image_rel, drawexe)
        task["human_label"] = ""
        task["human_note"] = ""
    fields = ["task_id", "dataset_id", "item_type", "group_a", "group_b", "part_ids", "group_size",
              "predicted_relation", "risk_score", "selection_stratum", "inclusion_probability",
              "evidence", "image", "human_label", "human_note"]
    with (args.output / "review_queue.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(tasks)
    build_html(tasks, args.output / "index.html")
    print(f"Built {len(tasks)} review tasks at {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
