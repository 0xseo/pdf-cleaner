from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from ..analysis import MASK_FILES, analyze_page
from ..models import JobInfo
from ..pdf.inspect import inspect_pdf
from ..storage import get_job_dir, get_page_dir, load_job, safe_download_stem, save_job

PROJECT_FORMAT = "pdf-eraser-project"
PROJECT_VERSION = 1
PAGE_PATH_PATTERN = re.compile(r"^pages/(\d{5})/([^/]+)$")
PAGE_FILES = {
    "analysis.json",
    "source.png",
    "cleaned.png",
    *MASK_FILES.values(),
}
ANALYSIS_FIELDS = {
    "pixel_width",
    "pixel_height",
    "dpi",
    "candidate_ratio",
    "automatic_remove_ratio",
    "preserve_ratio",
    "pdf_text_regions",
    "ocr_text_regions",
    "structural_line_regions",
    "revision",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _project_metadata(job: dict[str, object]) -> dict[str, object]:
    return {
        "format": PROJECT_FORMAT,
        "version": PROJECT_VERSION,
        "display_name": str(job["display_name"]),
        "source_sha256": str(job["source_sha256"]),
        "page_count": int(job["page_count"]),
        "saved_at": datetime.now(UTC).isoformat(),
    }


def export_project(job_id: str) -> Path:
    job = load_job(job_id)
    for page in job["pages"]:
        analyze_page(job_id, int(page["index"]))
    job = load_job(job_id)
    job_dir = get_job_dir(job_id)
    project_dir = job_dir / "projects"
    project_dir.mkdir(parents=True, exist_ok=True)
    stem = safe_download_stem(str(job["display_name"]))
    output_path = project_dir / f"{stem}.pdferaser"
    temporary_path = output_path.with_suffix(".pdferaser.tmp")

    with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(
            "project.json",
            json.dumps(_project_metadata(job), ensure_ascii=False, indent=2),
        )
        archive.write(job_dir / "source.pdf", "source.pdf")
        archive.write(job_dir / "job.json", "job.json")
        for page in job["pages"]:
            index = int(page["index"])
            page_dir = get_page_dir(job_id, index)
            for filename in sorted(PAGE_FILES):
                archive.write(page_dir / filename, f"pages/{index:05d}/{filename}")
    temporary_path.replace(output_path)
    return output_path


def _read_json_entry(archive: zipfile.ZipFile, name: str) -> dict[str, object]:
    info = archive.getinfo(name)
    if info.file_size > 1024 * 1024:
        raise ValueError(f"Project metadata is too large: {name}")
    try:
        value = json.loads(archive.read(name))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise ValueError(f"Project metadata is invalid: {name}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Project metadata is invalid: {name}")
    return value


def _validate_entries(archive: zipfile.ZipFile) -> set[str]:
    names = [info.filename for info in archive.infolist() if not info.is_dir()]
    if len(names) != len(set(names)):
        raise ValueError("Project contains duplicate files")
    allowed_roots = {"project.json", "source.pdf", "job.json"}
    for name in names:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError("Project contains an unsafe path")
        if name in allowed_roots:
            continue
        match = PAGE_PATH_PATTERN.fullmatch(name)
        if not match or match.group(2) not in PAGE_FILES:
            raise ValueError(f"Project contains an unsupported file: {name}")
    if not allowed_roots.issubset(names):
        raise ValueError("Project is missing required files")
    return set(names)


def _extract_entry(archive: zipfile.ZipFile, name: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(name) as source, destination.open("wb") as output:
        shutil.copyfileobj(source, output, length=1024 * 1024)


def _validate_page_artifacts(page_dir: Path) -> None:
    try:
        analysis = json.loads((page_dir / "analysis.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as error:
        raise ValueError("Project page analysis is invalid") from error
    if not isinstance(analysis, dict) or not ANALYSIS_FIELDS.issubset(analysis):
        raise ValueError("Project page analysis is incomplete")
    try:
        width = int(analysis["pixel_width"])
        height = int(analysis["pixel_height"])
        dpi = int(analysis["dpi"])
        revision = int(analysis["revision"])
    except (TypeError, ValueError) as error:
        raise ValueError("Project page dimensions are invalid") from error
    if width <= 0 or height <= 0 or dpi <= 0 or revision <= 0:
        raise ValueError("Project page dimensions are invalid")
    try:
        for filename in PAGE_FILES - {"analysis.json"}:
            with Image.open(page_dir / filename) as image:
                image.load()
                if image.size != (width, height):
                    raise ValueError("Project page image dimensions do not match")
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError("Project page image is invalid") from error


def import_project(archive_path: Path, job_id: str) -> dict[str, object]:
    job_dir = get_job_dir(job_id)
    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as error:
        raise ValueError("The selected file is not a PDF Eraser project") from error

    with archive:
        expanded_size = sum(info.file_size for info in archive.infolist())
        archive_size = max(archive_path.stat().st_size, 1)
        if expanded_size > max(archive_size * 50, archive_size + 64 * 1024 * 1024):
            raise ValueError("Project expands beyond the safe archive ratio")
        names = _validate_entries(archive)
        metadata = _read_json_entry(archive, "project.json")
        archived_job_data = _read_json_entry(archive, "job.json")
        try:
            archived_job = JobInfo.model_validate(archived_job_data)
        except ValueError as error:
            raise ValueError("Project job metadata is invalid") from error
        if archived_job.page_count != len(archived_job.pages):
            raise ValueError("Project job page count does not match")
        if metadata.get("format") != PROJECT_FORMAT or metadata.get("version") != PROJECT_VERSION:
            raise ValueError("Project format or version is not supported")
        if int(metadata.get("page_count", -1)) != archived_job.page_count:
            raise ValueError("Project page count does not match")

        source_path = job_dir / "source.pdf"
        _extract_entry(archive, "source.pdf", source_path)
        source_hash = _sha256(source_path)
        if (
            source_hash != metadata.get("source_sha256")
            or source_hash != archived_job.source_sha256
        ):
            raise ValueError("Project source PDF hash does not match")
        pages = inspect_pdf(source_path)
        if len(pages) != archived_job.page_count:
            raise ValueError("Project source PDF page count does not match")

        for index, archived_page in enumerate(archived_job.pages):
            if archived_page.status != "ready":
                continue
            page_names = {f"pages/{index:05d}/{filename}" for filename in PAGE_FILES}
            if not page_names.issubset(names):
                raise ValueError(f"Project page {index + 1} is incomplete")
            page_dir = get_page_dir(job_id, index)
            for name in page_names:
                _extract_entry(archive, name, page_dir / Path(name).name)
            _validate_page_artifacts(page_dir)
            pages[index]["status"] = "ready"
            pages[index]["risk_level"] = archived_page.risk_level
            pages[index]["risk_score"] = archived_page.risk_score
            pages[index]["error"] = None

    job = {
        "id": job_id,
        "display_name": Path(archived_job.display_name).name,
        "source_sha256": source_hash,
        "page_count": len(pages),
        "created_at": datetime.now(UTC).isoformat(),
        "pages": pages,
    }
    save_job(job)
    return job
