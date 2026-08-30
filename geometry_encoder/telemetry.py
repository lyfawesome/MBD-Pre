"""Run manifests, stage events, quality gates, and artifact checksums."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_revision(workdir: Path) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=workdir, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


class WorkflowRecorder:
    def __init__(self, output: Path, config: dict, source_hash: str):
        self.output = output
        self.output.mkdir(parents=True, exist_ok=True)
        self.manifest_path = output / "workflow_manifest.json"
        self.events_path = output / "workflow_events.jsonl"
        self.manifest = {
            "schema": 1,
            "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ"),
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "source_sha256": source_hash,
            "git_revision": _git_revision(Path.cwd()),
            "runtime": {"python": platform.python_version(), "platform": platform.platform()},
            "config": config,
            "stages": [],
            "quality_gates": [],
            "artifacts": [],
        }
        self._write_manifest()

    def _write_manifest(self) -> None:
        temporary = self.manifest_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(self.manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.manifest_path)

    def event(self, event_type: str, **payload) -> None:
        record = {"timestamp": datetime.now(timezone.utc).isoformat(), "type": event_type, **payload}
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    @contextmanager
    def stage(self, name: str):
        record = {"name": name, "status": "running", "started_at": datetime.now(timezone.utc).isoformat()}
        self.manifest["stages"].append(record)
        self.event("stage_started", stage=name)
        self._write_manifest()
        started = time.perf_counter()
        try:
            yield record
        except Exception as error:
            record.update({
                "status": "failed", "duration_seconds": time.perf_counter() - started,
                "error": str(error), "traceback": traceback.format_exc()[-8000:],
            })
            self.manifest["status"] = "failed"
            self.event("stage_failed", stage=name, error=str(error))
            self._write_manifest()
            raise
        else:
            record.update({"status": "completed", "duration_seconds": time.perf_counter() - started})
            self.event("stage_completed", stage=name, metrics=record.get("metrics", {}))
            self._write_manifest()

    def gate(self, name: str, passed: bool, evidence: dict) -> None:
        result = {"name": name, "passed": passed, "evidence": evidence}
        self.manifest["quality_gates"].append(result)
        self.event("quality_gate", **result)
        if not passed:
            self.manifest["status"] = "failed"
            self._write_manifest()
            raise RuntimeError(f"Quality gate failed: {name}: {evidence}")
        self._write_manifest()

    def collect_artifacts(self, paths: list[Path]) -> list[dict]:
        artifacts = []
        for path in paths:
            if path.is_file():
                artifacts.append({
                    "path": str(path.relative_to(self.output)), "bytes": path.stat().st_size,
                    "sha256": file_sha256(path),
                })
        self.manifest["artifacts"] = artifacts
        self._write_manifest()
        return artifacts

    def complete(self, metrics: dict) -> None:
        self.manifest.update({
            "status": "completed", "completed_at": datetime.now(timezone.utc).isoformat(),
            "metrics": metrics,
        })
        self.event("workflow_completed", metrics=metrics)
        self._write_manifest()
