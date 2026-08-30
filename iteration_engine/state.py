"""Recoverable cycle state and subprocess stage recording."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from .io import atomic_write_json, load_json, stable_id, utc_now


class CycleState:
    def __init__(self, path: Path, config_path: Path):
        self.path = path
        previous = load_json(path, None)
        if previous and previous.get("status") in {"running", "failed"}:
            self.value = previous
            self.value["status"] = "running"
        else:
            timestamp = utc_now().replace("+00:00", "Z").replace(":", "")
            self.value = {
                "schema_version": 1,
                "cycle_id": timestamp + "-" + stable_id(str(config_path), utc_now(), length=8),
                "config": str(config_path),
                "started_at": utc_now(),
                "status": "running",
                "stages": [],
            }
        self.save()

    def save(self) -> None:
        atomic_write_json(self.path, self.value)

    def record_python_stage(self, name: str, command: list[str], cwd: Path) -> int:
        if any(stage.get("name") == name and stage.get("status") == "completed"
               for stage in self.value["stages"]):
            return 0
        started = utc_now()
        begin = time.monotonic()
        completed = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, check=False)
        stage = {
            "name": name, "started_at": started, "finished_at": utc_now(),
            "elapsed_seconds": round(time.monotonic() - begin, 3),
            "returncode": completed.returncode,
            "status": "completed" if completed.returncode == 0 else "failed",
            "command": command,
            "output_tail": completed.stdout[-4000:],
        }
        self.value["stages"].append(stage)
        if completed.returncode:
            self.value["status"] = "failed"
        self.save()
        return completed.returncode

    def record_internal_stage(self, name: str, summary: dict) -> None:
        self.value["stages"].append({
            "name": name, "started_at": utc_now(), "finished_at": utc_now(),
            "elapsed_seconds": 0.0, "returncode": 0, "status": "completed",
            "summary": summary,
        })
        self.save()

    def finish(self, status: str = "completed") -> None:
        self.value.update(status=status, finished_at=utc_now())
        self.save()
