"""Pluggable, auditable internet discovery for STEP assembly candidates."""

from __future__ import annotations

import json
import multiprocessing
import os
import queue
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable

from .io import atomic_write_json, stable_id, utc_now


USER_AGENT = "MBD-Pre-continuous-discovery/1.0"
STEP_SUFFIXES = (".step", ".stp")


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    provider: str
    matched_type: str
    title: str
    filename: str
    download_url: str
    landing_url: str
    license: str
    expected_bytes: int | None
    repository: str
    discovered_at: str
    score: int
    decision: str
    decision_reason: str


def _get_json(url: str, token: str | None = None) -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def _decision(license_id: str, size: int | None, allowed: set[str], maximum: int) -> tuple[str, str]:
    if not license_id or license_id.casefold() not in allowed:
        return "manual_review", "license_not_in_allowlist"
    if size is not None and size > maximum:
        return "rejected", "file_too_large"
    return "staged", "license_and_size_gate_passed"


def discover_zenodo(
    entity_type: str,
    keywords: list[str],
    rows: int,
    allowed: set[str],
    maximum: int,
) -> tuple[list[Candidate], list[dict]]:
    phrase = " OR ".join(f'"{word}"' for word in keywords[:3])
    query = f"({phrase}) AND (STEP OR STP) AND (assembly OR CAD)"
    url = "https://zenodo.org/api/records?" + urllib.parse.urlencode({"q": query, "size": rows})
    events = [{"provider": "zenodo", "entity_type": entity_type, "url": url,
               "attempted_at": utc_now(), "status": "started"}]
    candidates: list[Candidate] = []
    try:
        payload = _get_json(url)
        for record in payload.get("hits", {}).get("hits", []):
            metadata = record.get("metadata", {})
            license_value = metadata.get("license", {})
            license_id = license_value.get("id", "") if isinstance(license_value, dict) else str(license_value)
            for file in record.get("files", []):
                filename = file.get("key", "")
                if not filename.casefold().endswith(STEP_SUFFIXES):
                    continue
                links = file.get("links", {})
                download = links.get("content") or links.get("self", "")
                size = file.get("size")
                decision, reason = _decision(license_id, size, allowed, maximum)
                candidates.append(Candidate(
                    candidate_id="zenodo_" + stable_id(str(record.get("id")), filename),
                    provider="zenodo", matched_type=entity_type,
                    title=metadata.get("title", filename), filename=filename,
                    download_url=download, landing_url=record.get("links", {}).get("html", ""),
                    license=license_id, expected_bytes=size, repository="",
                    discovered_at=utc_now(), score=4 + int("assembl" in filename.casefold()),
                    decision=decision, decision_reason=reason,
                ))
        events[-1].update(status="completed", candidates=len(candidates))
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
        events[-1].update(status="failed", error=f"{type(exc).__name__}: {exc}")
    return candidates, events


def discover_github(
    entity_type: str,
    keywords: list[str],
    rows: int,
    allowed: set[str],
    maximum: int,
) -> tuple[list[Candidate], list[dict]]:
    token = os.environ.get("GITHUB_TOKEN")
    phrase = " ".join(keywords[:2])
    query = f"{phrase} assembly extension:step"
    url = "https://api.github.com/search/code?" + urllib.parse.urlencode({"q": query, "per_page": rows})
    events = [{"provider": "github", "entity_type": entity_type, "url": url,
               "attempted_at": utc_now(), "status": "started"}]
    candidates: list[Candidate] = []
    try:
        payload = _get_json(url, token)
        repositories: dict[str, dict] = {}
        for item in payload.get("items", []):
            repo_api = item.get("repository", {}).get("url", "")
            if repo_api not in repositories:
                repositories[repo_api] = _get_json(repo_api, token)
            repo = repositories[repo_api]
            details = _get_json(item["url"], token)
            license_data = repo.get("license") or {}
            license_id = license_data.get("spdx_id", "")
            size = details.get("size")
            decision, reason = _decision(license_id, size, allowed, maximum)
            filename = item.get("name", "")
            candidates.append(Candidate(
                candidate_id="github_" + stable_id(repo.get("full_name", ""), item.get("path", "")),
                provider="github", matched_type=entity_type,
                title=f"{repo.get('full_name', '')}: {item.get('path', filename)}",
                filename=filename, download_url=details.get("download_url", ""),
                landing_url=item.get("html_url", ""), license=license_id,
                expected_bytes=size, repository=repo.get("full_name", ""),
                discovered_at=utc_now(), score=5 + int("assembl" in item.get("path", "").casefold()),
                decision=decision, decision_reason=reason,
            ))
        events[-1].update(status="completed", candidates=len(candidates), authenticated=bool(token))
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError) as exc:
        events[-1].update(status="failed", error=f"{type(exc).__name__}: {exc}", authenticated=bool(token))
    return candidates, events


def _provider_worker(result_queue, provider: str, entity_type: str, keywords: list[str],
                     rows: int, allowed: set[str], maximum: int) -> None:
    adapters = {"zenodo": discover_zenodo, "github": discover_github}
    try:
        candidates, events = adapters[provider](entity_type, keywords, rows, allowed, maximum)
        result_queue.put((provider, entity_type, candidates, events))
    except BaseException as exc:
        result_queue.put((provider, entity_type, [], [{
            "provider": provider, "entity_type": entity_type,
            "attempted_at": utc_now(), "status": "failed",
            "error": f"worker:{type(exc).__name__}: {exc}",
        }]))


def discover(
    missing_types: Iterable[str],
    taxonomy: dict[str, list[str]],
    providers: Iterable[str],
    rows: int,
    allowed_licenses: Iterable[str],
    maximum_bytes: int,
    output: Path,
    log_output: Path,
    deadline_seconds: float = 75.0,
) -> dict:
    allowed = {value.casefold() for value in allowed_licenses}
    all_candidates: list[Candidate] = []
    events: list[dict] = []
    adapters = {"zenodo": discover_zenodo, "github": discover_github}
    jobs = []
    for entity_type in missing_types:
        for provider in providers:
            adapter = adapters.get(provider)
            if adapter is None:
                events.append({"provider": provider, "entity_type": entity_type,
                               "attempted_at": utc_now(), "status": "unsupported"})
            else:
                jobs.append((provider, entity_type, adapter))
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    processes = {}
    for provider, entity_type, _ in jobs:
        process = context.Process(
            target=_provider_worker,
            args=(result_queue, provider, entity_type, taxonomy[entity_type], rows,
                  allowed, maximum_bytes),
        )
        process.start()
        processes[(provider, entity_type)] = process
    deadline = time.monotonic() + deadline_seconds
    received = set()
    while len(received) < len(processes) and time.monotonic() < deadline:
        try:
            provider, entity_type, candidates, attempts = result_queue.get(
                timeout=min(0.5, max(0.01, deadline - time.monotonic()))
            )
        except queue.Empty:
            continue
        received.add((provider, entity_type))
        all_candidates.extend(candidates)
        events.extend(attempts)
    for key, process in processes.items():
        if key not in received:
            events.append({"provider": key[0], "entity_type": key[1],
                           "attempted_at": utc_now(), "status": "failed",
                           "error": f"hard_deadline_exceeded:{deadline_seconds:g}s"})
        if process.is_alive():
            process.terminate()
        process.join(timeout=5)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
    result_queue.close()
    deduplicated = {}
    for candidate in all_candidates:
        key = candidate.download_url or candidate.landing_url
        previous = deduplicated.get(key)
        if previous is None or candidate.score > previous.score:
            deduplicated[key] = candidate
    ranked = sorted(deduplicated.values(), key=lambda item: (-item.score, item.candidate_id))
    successful = sum(event.get("status") == "completed" for event in events)
    failed = sum(event.get("status") == "failed" for event in events)
    payload = {"schema_version": 1, "generated_at": utc_now(),
               "query_count": len(jobs),
               "successful_queries": successful, "failed_queries": failed,
               "candidates": [asdict(item) for item in ranked]}
    atomic_write_json(output, payload)
    atomic_write_json(log_output, {"schema_version": 1, "events": events})
    return payload
