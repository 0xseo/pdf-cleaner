from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config import JOBS_ROOT

JOB_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


def get_job_dir(job_id: str) -> Path:
    if not JOB_ID_PATTERN.fullmatch(job_id):
        raise ValueError("Invalid job id")
    path = (JOBS_ROOT / job_id).resolve()
    if path.parent != JOBS_ROOT.resolve():
        raise ValueError("Invalid job path")
    return path


def get_page_dir(job_id: str, page_index: int) -> Path:
    if page_index < 0:
        raise ValueError("Invalid page index")
    return get_job_dir(job_id) / "pages" / f"{page_index:05d}"


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    temporary.replace(path)


def load_job(job_id: str) -> dict[str, Any]:
    return read_json(get_job_dir(job_id) / "job.json")


def save_job(job: dict[str, Any]) -> None:
    write_json(get_job_dir(str(job["id"])) / "job.json", job)


def safe_download_stem(display_name: str) -> str:
    stem = Path(display_name).stem
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
    return cleaned[:80] or "document"
