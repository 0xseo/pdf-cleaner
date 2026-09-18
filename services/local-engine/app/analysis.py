from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .config import DEFAULT_ANALYSIS_DPI
from .detection import OpenCvBaselineDetector
from .detection.base import DetectionContext
from .models import AnalysisResult, JobInfo
from .pdf.render import render_page
from .restoration import restore_image, restore_with_manual_clear
from .storage import get_job_dir, get_page_dir, load_job, read_json, save_job, write_json

MASK_FILES = {
    "candidate": "candidate.png",
    "remove": "remove.png",
    "preserve": "preserve.png",
    "review": "review.png",
    "structural": "structural.png",
}


def _save_mask(path: Path, mask: np.ndarray) -> None:
    alpha = mask.astype(np.uint8)
    rgba = np.full((*alpha.shape, 4), 255, dtype=np.uint8)
    rgba[:, :, 3] = alpha
    Image.fromarray(rgba, mode="RGBA").save(path, format="PNG", optimize=True)


def _load_mask(path: Path) -> np.ndarray:
    image = Image.open(path)
    if image.mode in {"RGBA", "LA"}:
        return np.asarray(image.getchannel("A"))
    return np.asarray(image.convert("L"))


def _ratio(mask: np.ndarray) -> float:
    return round(float(cv2.countNonZero(mask)) / float(mask.size), 6)


def _urls(job_id: str, page_index: int, revision: int) -> dict[str, str]:
    base = f"/api/jobs/{job_id}/pages/{page_index}/artifacts"
    suffix = f"?revision={revision}"
    return {
        "source_url": f"{base}/source{suffix}",
        "cleaned_url": f"{base}/cleaned{suffix}",
        "candidate_mask_url": f"{base}/candidate{suffix}",
        "remove_mask_url": f"{base}/remove{suffix}",
        "preserve_mask_url": f"{base}/preserve{suffix}",
        "review_mask_url": f"{base}/review{suffix}",
    }


def _build_result(job: dict[str, object], page_index: int) -> AnalysisResult:
    job_id = str(job["id"])
    page_dir = get_page_dir(job_id, page_index)
    analysis = read_json(page_dir / "analysis.json")
    page = JobInfo.model_validate(job).pages[page_index]
    return AnalysisResult(
        page=page,
        **analysis,
        **_urls(job_id, page_index, int(analysis["revision"])),
    )


def analyze_page(job_id: str, page_index: int, dpi: int = DEFAULT_ANALYSIS_DPI) -> AnalysisResult:
    job = load_job(job_id)
    pages = job["pages"]
    if page_index < 0 or page_index >= len(pages):
        raise IndexError("Page index out of range")
    page_dir = get_page_dir(job_id, page_index)
    page_dir.mkdir(parents=True, exist_ok=True)
    existing = page_dir / "analysis.json"
    if existing.exists():
        return _build_result(job, page_index)

    pages[page_index]["status"] = "analyzing"
    pages[page_index]["error"] = None
    save_job(job)
    try:
        source_path = page_dir / "source.png"
        image = render_page(get_job_dir(job_id) / "source.pdf", page_index, dpi, source_path)
        source_rgb = np.asarray(image)
        page = pages[page_index]
        context = DetectionContext(
            pdf_path=get_job_dir(job_id) / "source.pdf",
            page_index=page_index,
            dpi=dpi,
            crop_box=[float(value) for value in page["crop_box"]],
            rotation=int(page["rotation"]),
        )
        detection = OpenCvBaselineDetector().detect(source_rgb, context)
        masks = {
            "candidate": detection.candidate_mask,
            "remove": detection.remove_mask,
            "preserve": detection.preserve_mask,
            "review": detection.review_mask,
            "structural": detection.structural_line_mask,
        }
        for name, mask in masks.items():
            _save_mask(page_dir / MASK_FILES[name], mask)

        cleaned = restore_image(
            source_rgb, detection.remove_mask, detection.structural_line_mask
        )
        Image.fromarray(cleaned, mode="RGB").save(
            page_dir / "cleaned.png", format="PNG", optimize=True
        )
        analysis = {
            "pixel_width": image.width,
            "pixel_height": image.height,
            "dpi": dpi,
            "candidate_ratio": _ratio(detection.candidate_mask),
            "automatic_remove_ratio": _ratio(detection.remove_mask),
            "preserve_ratio": _ratio(detection.preserve_mask),
            "pdf_text_regions": detection.pdf_text_regions,
            "ocr_text_regions": detection.ocr_text_regions,
            "structural_line_regions": detection.structural_line_regions,
            "revision": 1,
        }
        write_json(existing, analysis)
        page["status"] = "ready"
        page["risk_score"] = detection.risk_score
        page["risk_level"] = detection.risk_level
        save_job(job)
        return _build_result(job, page_index)
    except Exception as error:
        pages[page_index]["status"] = "error"
        pages[page_index]["error"] = str(error)[:500]
        save_job(job)
        raise


def update_masks(
    job_id: str, page_index: int, remove_mask: np.ndarray, preserve_mask: np.ndarray
) -> AnalysisResult:
    job = load_job(job_id)
    page_dir = get_page_dir(job_id, page_index)
    analysis_path = page_dir / "analysis.json"
    if not analysis_path.exists():
        raise FileNotFoundError("Page has not been analyzed")
    analysis = read_json(analysis_path)
    expected_shape = (int(analysis["pixel_height"]), int(analysis["pixel_width"]))
    if remove_mask.shape != expected_shape or preserve_mask.shape != expected_shape:
        raise ValueError("Mask dimensions do not match the rendered page")

    remove_mask = np.where(remove_mask > 0, 255, 0).astype(np.uint8)
    preserve_mask = np.where(preserve_mask > 0, 255, 0).astype(np.uint8)
    remove_mask[preserve_mask > 0] = 0
    candidate = _load_mask(page_dir / "candidate.png")
    structural_path = page_dir / "structural.png"
    structural = (
        _load_mask(structural_path)
        if structural_path.exists()
        else np.zeros(expected_shape, dtype=np.uint8)
    )
    review = cv2.bitwise_and(candidate, remove_mask)
    _save_mask(page_dir / "remove.png", remove_mask)
    _save_mask(page_dir / "preserve.png", preserve_mask)
    _save_mask(page_dir / "review.png", review)

    source = np.asarray(Image.open(page_dir / "source.png").convert("RGB"))
    cleaned = restore_with_manual_clear(source, remove_mask, candidate, structural)
    Image.fromarray(cleaned, mode="RGB").save(page_dir / "cleaned.png", format="PNG", optimize=True)
    analysis["automatic_remove_ratio"] = _ratio(remove_mask)
    analysis["preserve_ratio"] = _ratio(preserve_mask)
    analysis["revision"] = int(analysis["revision"]) + 1
    write_json(analysis_path, analysis)
    return _build_result(job, page_index)
