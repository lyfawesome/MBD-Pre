#!/usr/bin/env python3
"""Download and verify the assembly corpus described by research/assembly_sources.json."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "research" / "assembly_sources.json"
DEFAULT_OUTPUT = ROOT / "data" / "assemblies"
LOG_PATH = ROOT / "research" / "acquisition_log.csv"
INVENTORY_PATH = ROOT / "research" / "raw_data_file_inventory.csv"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_url(source: dict) -> str:
    if source.get("download_url"):
        return source["download_url"]
    path = urllib.parse.quote(source["path"], safe="/")
    if source.get("transport") == "github_media":
        host = "https://media.githubusercontent.com/media"
    else:
        host = "https://raw.githubusercontent.com"
    return f"{host}/{source['owner']}/{source['repo']}/{source['ref']}/{path}"


def extension(source: dict) -> str:
    candidate = source.get("path") or source.get("filename") or urllib.parse.urlparse(source_url(source)).path
    suffix = Path(candidate).suffix.lower()
    return ".step" if suffix not in {".step", ".stp"} else suffix


def inspect_existing(path: Path, source: dict) -> tuple[bool, str, int, str]:
    if not path.exists():
        return False, "missing", 0, ""
    size = path.stat().st_size
    digest = sha256_file(path)
    if source.get("expected_bytes") and size != source["expected_bytes"]:
        return False, f"size_mismatch:{size}", size, digest
    if source.get("expected_sha256") and digest != source["expected_sha256"]:
        return False, "sha256_mismatch", size, digest
    with path.open("rb") as handle:
        prefix = handle.read(128)
    if prefix.startswith(b"version https://git-lfs.github.com/spec/v1"):
        return False, "git_lfs_pointer", size, digest
    if b"ISO-10303-21" not in prefix.upper():
        return False, "not_step_header", size, digest
    return True, "verified_existing", size, digest


def download_range(url: str, start: int, end: int, destination: Path, retries: int) -> None:
    expected = end - start + 1
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers={
                "User-Agent": "MBD-Pre-corpus/1.0", "Accept": "application/octet-stream",
                "Range": f"bytes={start}-{end}",
            })
            with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as out:
                if response.status != 206:
                    raise ValueError(f"range_not_honored:{response.status}")
                shutil.copyfileobj(response, out, length=1024 * 1024)
            if destination.stat().st_size != expected:
                raise ValueError(f"range_size_mismatch:{destination.stat().st_size}:{expected}")
            return
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = f"attempt_{attempt}:{type(exc).__name__}:{exc}"
            destination.unlink(missing_ok=True)
            if attempt < retries:
                time.sleep(min(2 ** attempt, 10))
    raise OSError(last_error)


def download_segmented(url: str, partial: Path, total: int, retries: int, segments: int) -> None:
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > total:
        partial.unlink()
        offset = 0
    if offset == total:
        return
    remaining = total - offset
    count = min(segments, remaining)
    chunk_size = (remaining + count - 1) // count
    ranges = []
    for index in range(count):
        start = offset + index * chunk_size
        end = min(total - 1, start + chunk_size - 1)
        if start <= end:
            ranges.append((index, start, end, partial.with_suffix(partial.suffix + f".chunk{index}")))
    for _, _, _, chunk in ranges:
        chunk.unlink(missing_ok=True)
    with ThreadPoolExecutor(max_workers=len(ranges)) as executor:
        futures = [executor.submit(download_range, url, start, end, chunk, retries)
                   for _, start, end, chunk in ranges]
        for future in as_completed(futures):
            future.result()
    with partial.open("ab") as out:
        for _, _, _, chunk in ranges:
            with chunk.open("rb") as handle:
                shutil.copyfileobj(handle, out, length=1024 * 1024)
            chunk.unlink()
    if partial.stat().st_size != total:
        raise ValueError(f"segmented_size_mismatch:{partial.stat().st_size}:{total}")


def download_one(source: dict, output_dir: Path, retries: int, segments: int) -> dict:
    destination = output_dir / f"{source['id']}{extension(source)}"
    url = source_url(source)
    started = utc_now()
    valid, reason, size, digest = inspect_existing(destination, source)
    if valid:
        return {"id": source["id"], "status": "verified", "reason": reason,
                "url": url, "path": str(destination), "bytes": size,
                "sha256": digest, "started_at": started, "finished_at": utc_now()}

    partial = destination.with_suffix(destination.suffix + ".part")
    last_error = reason
    for attempt in range(1, retries + 1):
        try:
            if segments > 1 and source.get("expected_bytes", 0) >= 50 * 1024 * 1024:
                download_segmented(url, partial, source["expected_bytes"], retries, segments)
                os.replace(partial, destination)
                valid, reason, size, digest = inspect_existing(destination, source)
                if not valid:
                    destination.unlink(missing_ok=True)
                    raise ValueError(reason)
                return {"id": source["id"], "status": "downloaded", "reason": reason,
                        "url": url, "path": str(destination), "bytes": size,
                        "sha256": digest, "started_at": started, "finished_at": utc_now()}
            offset = partial.stat().st_size if partial.exists() else 0
            headers = {"User-Agent": "MBD-Pre-corpus/1.0", "Accept": "application/octet-stream"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            request = urllib.request.Request(
                url,
                headers=headers,
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                resume_accepted = offset > 0 and response.status == 206
                mode = "ab" if resume_accepted else "wb"
                if offset and not resume_accepted:
                    offset = 0
                with partial.open(mode) as out:
                    shutil.copyfileobj(response, out, length=1024 * 1024)
            os.replace(partial, destination)
            valid, reason, size, digest = inspect_existing(destination, source)
            if not valid:
                destination.unlink(missing_ok=True)
                raise ValueError(reason)
            return {"id": source["id"], "status": "downloaded", "reason": reason,
                    "url": url, "path": str(destination), "bytes": size,
                    "sha256": digest, "started_at": started, "finished_at": utc_now()}
        except (OSError, ValueError, urllib.error.URLError) as exc:
            last_error = f"attempt_{attempt}:{type(exc).__name__}:{exc}"
            if attempt < retries:
                time.sleep(min(2 ** attempt, 10))
    return {"id": source["id"], "status": "failed", "reason": last_error,
            "url": url, "path": str(destination), "bytes": 0, "sha256": "",
            "started_at": started, "finished_at": utc_now()}


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: row.get(field, "") for field in fields} for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--log", type=Path, default=LOG_PATH)
    parser.add_argument("--inventory", type=Path, default=INVENTORY_PATH)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--segments", type=int, default=1,
                        help="Parallel byte ranges per file of at least 50 MiB")
    parser.add_argument("--include-quarantine", action="store_true")
    parser.add_argument("--ids", nargs="*", help="Download only selected source IDs")
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    sources = manifest["sources"]
    if not args.include_quarantine:
        sources = [source for source in sources if source.get("tier") != "quarantine"]
    if args.ids:
        selected = set(args.ids)
        sources = [source for source in sources if source["id"] in selected]
    args.output.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(download_one, source, args.output, args.retries, max(1, args.segments)): source
                   for source in sources}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"[{result['status']}] {result['id']}: {result['reason']}", flush=True)

    order = {source["id"]: index for index, source in enumerate(manifest["sources"])}
    results.sort(key=lambda row: order[row["id"]])
    for result in results:
        if result["status"] in {"verified", "downloaded"}:
            Path(result["path"] + ".part").unlink(missing_ok=True)
    write_csv(args.log, results, ["id", "status", "reason", "started_at", "finished_at", "url"])

    by_id = {source["id"]: source for source in manifest["sources"]}
    inventory = []
    for result in results:
        source = by_id[result["id"]]
        inventory.append({
            "id": result["id"], "title": source["title"], "local_path": result["path"],
            "source_url": result["url"], "license": source["license"],
            "bytes": result["bytes"], "sha256": result["sha256"],
            "retrieved_at": result["finished_at"], "status": result["status"],
        })
    write_csv(args.inventory, inventory,
              ["id", "title", "local_path", "source_url", "license", "bytes",
               "sha256", "retrieved_at", "status"])
    failures = [row for row in results if row["status"] == "failed"]
    print(f"Completed {len(results)} sources; failures={len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
