"""Bounded HTTP probes for STEP/ZIP candidates without full model downloads."""

from __future__ import annotations

import re
import struct
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from .discovery import USER_AGENT


def _request_bytes(url: str, byte_range: str | None, maximum: int, timeout: float) -> tuple[bytes, dict[str, Any]]:
    if urlparse(url).scheme != "https":
        raise ValueError("Only HTTPS remote probes are allowed")
    headers = {"User-Agent": USER_AGENT, "Accept": "application/octet-stream"}
    if byte_range:
        headers["Range"] = byte_range
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(maximum)
        info = {
            "http_status": response.status,
            "final_url": response.geturl(),
            "content_type": response.headers.get("Content-Type", ""),
            "content_length": int(response.headers.get("Content-Length", "0") or 0),
            "content_range": response.headers.get("Content-Range", ""),
            "accept_ranges": response.headers.get("Accept-Ranges", ""),
            "bytes_sampled": len(data),
        }
        return data, info


def _step_counts(data: bytes) -> dict[str, int]:
    upper = data.upper()
    return {
        "product_count": len(re.findall(rb"\bPRODUCT\s*\(", upper)),
        "assembly_occurrence_count": len(re.findall(rb"NEXT_ASSEMBLY_USAGE_OCCURRENCE", upper)),
        "solid_marker_count": sum(
            len(re.findall(marker, upper))
            for marker in (rb"MANIFOLD_SOLID_BREP", rb"BREP_WITH_VOIDS", rb"FACETED_BREP")
        ),
    }


def _zip_central_names(data: bytes) -> list[str]:
    """Read filenames from a ZIP central-directory tail; tolerate a partial prefix."""
    names: list[str] = []
    offset = 0
    signature = b"PK\x01\x02"
    while True:
        offset = data.find(signature, offset)
        if offset < 0 or offset + 46 > len(data):
            break
        try:
            filename_length, extra_length, comment_length = struct.unpack_from("<HHH", data, offset + 28)
        except struct.error:
            break
        start = offset + 46
        end = start + filename_length
        if end > len(data):
            break
        names.append(data[start:end].decode("utf-8", errors="replace"))
        offset = end + extra_length + comment_length
    return names


def probe_remote(url: str, filename: str = "", maximum_bytes: int = 1_048_576,
                 timeout: float = 20.0) -> dict[str, Any]:
    """Return bounded transport and weak assembly evidence; never downloads beyond samples."""
    result: dict[str, Any] = {"url": url, "filename": filename, "probe_status": "started"}
    try:
        front, info = _request_bytes(url, f"bytes=0-{maximum_bytes - 1}", maximum_bytes, timeout)
        result.update(info)
        lower_name = filename.casefold() or urlparse(info["final_url"]).path.casefold()
        is_zip = lower_name.endswith(".zip") or front.startswith(b"PK\x03\x04")
        content_range = info.get("content_range", "")
        match = re.search(r"/(\d+)$", content_range)
        total = int(match.group(1)) if match else info["content_length"]
        result["total_bytes"] = total
        if is_zip:
            tail = front
            if total > maximum_bytes:
                tail, tail_info = _request_bytes(
                    url, f"bytes={max(0, total - maximum_bytes)}-{total - 1}", maximum_bytes, timeout
                )
                result["tail_http_status"] = tail_info["http_status"]
                result["bytes_sampled"] += tail_info["bytes_sampled"]
            names = _zip_central_names(tail)
            step_names = [name for name in names if name.casefold().endswith((".step", ".stp"))]
            result.update({
                "archive_entry_count_sampled": len(names),
                "step_entry_count": len(step_names),
                "assembly_step_entries": [name for name in step_names if "assembl" in name.casefold()][:20],
                "bom_entries": [name for name in names if "bom" in name.casefold() or "bill of material" in name.casefold()][:20],
            })
        else:
            sample = front
            if total > maximum_bytes:
                tail, tail_info = _request_bytes(
                    url, f"bytes={max(0, total - maximum_bytes)}-{total - 1}", maximum_bytes, timeout
                )
                sample += tail
                result["tail_http_status"] = tail_info["http_status"]
                result["bytes_sampled"] += tail_info["bytes_sampled"]
            result.update(_step_counts(sample))
            result["step_header"] = b"ISO-10303-21" in front.upper()
        result["probe_status"] = "verified"
    except (OSError, ValueError, urllib.error.URLError) as exc:
        result.update(probe_status="failed", error=f"{type(exc).__name__}: {exc}")
    return result
