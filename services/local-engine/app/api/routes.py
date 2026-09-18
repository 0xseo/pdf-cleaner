from __future__ import annotations

import base64
import binascii
import hashlib
import io
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import numpy as np
from fastapi import APIRouter, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

from ..analysis import MASK_FILES, analyze_page, update_masks
from ..config import DEFAULT_ANALYSIS_DPI, STREAM_CHUNK_SIZE
from ..export import export_job
from ..models import (
    AnalysisResult,
    ExportRequest,
    ExportResult,
    JobInfo,
    MaskUpdate,
    ProjectExportResult,
)
from ..pdf.inspect import inspect_pdf
from ..project import export_project, import_project
from ..storage import get_job_dir, get_page_dir, load_job, save_job

router = APIRouter(prefix="/api")
ARTIFACT_FILES = {
    "source": "source.png",
    "cleaned": "cleaned.png",
    **MASK_FILES,
}


def _not_found(message: str = "Job not found") -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)


def _decode_mask(data_url: str) -> np.ndarray:
    if not data_url.startswith("data:image/png;base64,"):
        raise ValueError("Mask must be a base64-encoded PNG data URL")
    try:
        payload = base64.b64decode(data_url.split(",", 1)[1], validate=True)
        image = Image.open(io.BytesIO(payload))
        if image.mode in {"RGBA", "LA"}:
            return np.asarray(image.getchannel("A"))
        return np.asarray(image.convert("L"))
    except (binascii.Error, UnidentifiedImageError, OSError) as error:
        raise ValueError("Mask PNG is invalid") from error


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "scope": "localhost-only"}


@router.post("/jobs", response_model=JobInfo, status_code=status.HTTP_201_CREATED)
async def create_job(file: Annotated[UploadFile, File()]) -> JobInfo:
    display_name = Path(file.filename or "document.pdf").name
    job_id = uuid.uuid4().hex
    job_dir = get_job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=False)
    source_path = job_dir / "source.pdf"
    digest = hashlib.sha256()
    first_chunk = True
    try:
        with source_path.open("wb") as output:
            while chunk := await file.read(STREAM_CHUNK_SIZE):
                if first_chunk and not chunk.lstrip().startswith(b"%PDF-"):
                    raise ValueError("The selected file is not a PDF")
                first_chunk = False
                digest.update(chunk)
                output.write(chunk)
        if first_chunk:
            raise ValueError("The selected PDF is empty")
        pages = inspect_pdf(source_path)
        job = {
            "id": job_id,
            "display_name": display_name,
            "source_sha256": digest.hexdigest(),
            "page_count": len(pages),
            "created_at": datetime.now(UTC).isoformat(),
            "pages": pages,
        }
        save_job(job)
        return JobInfo.model_validate(job)
    except Exception as error:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        await file.close()


@router.post("/projects", response_model=JobInfo, status_code=status.HTTP_201_CREATED)
async def open_project(file: Annotated[UploadFile, File()]) -> JobInfo:
    job_id = uuid.uuid4().hex
    job_dir = get_job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=False)
    upload_path = job_dir / "uploaded.pdferaser"
    first_chunk = True
    try:
        with upload_path.open("wb") as output:
            while chunk := await file.read(STREAM_CHUNK_SIZE):
                if first_chunk and not chunk.startswith(b"PK"):
                    raise ValueError("The selected file is not a PDF Eraser project")
                first_chunk = False
                output.write(chunk)
        if first_chunk:
            raise ValueError("The selected project is empty")
        job = import_project(upload_path, job_id)
        upload_path.unlink(missing_ok=True)
        return JobInfo.model_validate(job)
    except Exception as error:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(error)) from error
    finally:
        await file.close()


@router.get("/jobs/{job_id}", response_model=JobInfo)
def get_job(job_id: str) -> JobInfo:
    try:
        return JobInfo.model_validate(load_job(job_id))
    except (ValueError, FileNotFoundError) as error:
        raise _not_found() from error


@router.post("/jobs/{job_id}/pages/{page_index}/analyze", response_model=AnalysisResult)
def analyze_job_page(job_id: str, page_index: int) -> AnalysisResult:
    try:
        return analyze_page(job_id, page_index, DEFAULT_ANALYSIS_DPI)
    except (ValueError, FileNotFoundError, IndexError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/jobs/{job_id}/pages/{page_index}/analysis", response_model=AnalysisResult)
def get_page_analysis(job_id: str, page_index: int) -> AnalysisResult:
    try:
        return analyze_page(job_id, page_index, DEFAULT_ANALYSIS_DPI)
    except (ValueError, FileNotFoundError, IndexError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/jobs/{job_id}/pages/{page_index}/artifacts/{artifact}")
def get_page_artifact(job_id: str, page_index: int, artifact: str) -> FileResponse:
    filename = ARTIFACT_FILES.get(artifact)
    if filename is None:
        raise _not_found("Artifact not found")
    try:
        path = get_page_dir(job_id, page_index) / filename
    except ValueError as error:
        raise _not_found() from error
    if not path.is_file():
        raise _not_found("Artifact not found")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.patch("/jobs/{job_id}/pages/{page_index}/mask", response_model=AnalysisResult)
def patch_page_mask(job_id: str, page_index: int, update: MaskUpdate) -> AnalysisResult:
    try:
        remove = _decode_mask(update.remove_mask)
        preserve = _decode_mask(update.preserve_mask)
        return update_masks(job_id, page_index, remove, preserve)
    except (ValueError, FileNotFoundError, IndexError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.post("/jobs/{job_id}/export", response_model=ExportResult)
def create_export(job_id: str, request: ExportRequest) -> ExportResult:
    try:
        output_path, report = export_job(job_id, request.mode)
    except (ValueError, FileNotFoundError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return ExportResult(
        mode=request.mode,
        filename=output_path.name,
        download_url=f"/api/jobs/{job_id}/download/{output_path.name}",
        validated=True,
        validation_report=report,
    )


@router.post("/jobs/{job_id}/project", response_model=ProjectExportResult)
def create_project_export(job_id: str) -> ProjectExportResult:
    try:
        output_path = export_project(job_id)
    except (ValueError, FileNotFoundError, RuntimeError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return ProjectExportResult(
        filename=output_path.name,
        download_url=f"/api/jobs/{job_id}/download-project/{output_path.name}",
    )


@router.get("/jobs/{job_id}/download-project/{filename}")
def download_project(job_id: str, filename: str) -> FileResponse:
    try:
        project_dir = (get_job_dir(job_id) / "projects").resolve()
    except ValueError as error:
        raise _not_found() from error
    path = (project_dir / Path(filename).name).resolve()
    if path.parent != project_dir or not path.is_file() or path.suffix.lower() != ".pdferaser":
        raise _not_found("Project not found")
    return FileResponse(
        path,
        media_type="application/vnd.pdf-eraser+zip",
        filename=path.name,
    )


@router.get("/jobs/{job_id}/download/{filename}")
def download_export(job_id: str, filename: str) -> FileResponse:
    try:
        export_dir = (get_job_dir(job_id) / "exports").resolve()
    except ValueError as error:
        raise _not_found() from error
    path = (export_dir / Path(filename).name).resolve()
    if path.parent != export_dir or not path.is_file() or path.suffix.lower() != ".pdf":
        raise _not_found("Export not found")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: str) -> Response:
    try:
        job_dir = get_job_dir(job_id)
    except ValueError as error:
        raise _not_found() from error
    if not job_dir.is_dir():
        raise _not_found()
    shutil.rmtree(job_dir)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
