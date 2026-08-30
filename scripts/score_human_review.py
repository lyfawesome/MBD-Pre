#!/usr/bin/env python3
"""Score completed labels exported from the human-review contact sheet."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def wilson(successes: float, total: float, z: float = 1.959963984540054) -> list[float | None]:
    if total <= 0:
        return [None, None]
    estimate = successes / total
    denominator = 1 + z * z / total
    center = (estimate + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(estimate * (1 - estimate) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]


def aggregate(records: list[dict]) -> dict:
    decided = [record for record in records if record["label"] != "uncertain"]
    successes = sum(record["correct"] for record in decided)
    weight = sum(record["weight"] for record in decided)
    weighted_success = sum(record["weight"] * record["correct"] for record in decided)
    low, high = wilson(successes, len(decided))
    return {
        "labeled": len(records), "decided": len(decided),
        "uncertain": len(records) - len(decided), "correct": successes,
        "estimate": weighted_success / weight if weight else None,
        "wilson_low": low, "wilson_high": high,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("labels", type=Path, help="human_labels.csv exported by index.html")
    parser.add_argument("--queue", type=Path, default=ROOT / "research" / "human_review" / "review_queue.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "research" / "human_review" / "human_accuracy_report.json")
    args = parser.parse_args()
    queue = {row["task_id"]: row for row in rows(args.queue)}
    labels = {row["task_id"]: row for row in rows(args.labels)}
    strata = defaultdict(lambda: {
        "labeled": 0, "correct": 0, "uncertain": 0,
        "weighted_correct": 0.0, "weight": 0.0,
    })
    aggregate_records = []
    for task_id, label_row in labels.items():
        if task_id not in queue or not label_row.get("human_label"):
            continue
        task = queue[task_id]
        label = label_row["human_label"]
        bucket = strata[task["selection_stratum"]]
        bucket["labeled"] += 1
        weight = 1.0 / max(float(task["inclusion_probability"]), 1e-15)
        if label == "uncertain":
            bucket["uncertain"] += 1
            aggregate_records.append({"predicted_relation": task["predicted_relation"],
                                      "stratum": task["selection_stratum"], "label": label,
                                      "correct": 0, "weight": weight})
            continue
        correct = ((task["predicted_relation"] == "same" and label == "correct_merge") or
                   (task["predicted_relation"] == "different" and label == "correct_split"))
        bucket["correct"] += int(correct)
        bucket["weighted_correct"] += weight * int(correct)
        bucket["weight"] += weight
        aggregate_records.append({"predicted_relation": task["predicted_relation"],
                                  "stratum": task["selection_stratum"], "label": label,
                                  "correct": int(correct), "weight": weight})
    result = {"schema_version": 2, "queue_size": len(queue), "label_file": str(args.labels), "strata": {}}
    for name, bucket in sorted(strata.items()):
        decided = bucket["labeled"] - bucket["uncertain"]
        estimate = bucket["weighted_correct"] / bucket["weight"] if bucket["weight"] else None
        result["strata"][name] = {
            **{key: bucket[key] for key in ("labeled", "correct", "uncertain")},
            "decided": decided, "weighted_accuracy": estimate,
            "wilson_95": wilson(bucket["correct"], decided),
        }
    result["merge_precision"] = aggregate([
        record for record in aggregate_records if record["predicted_relation"] == "same"
    ])
    result["random_cross_correct_split"] = aggregate([
        record for record in aggregate_records
        if record["predicted_relation"] == "different"
        and record["stratum"] == "random_cross_baseline"
    ])
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
