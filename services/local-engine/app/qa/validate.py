from __future__ import annotations

from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from pypdf import PdfReader


def _box(page: object, name: str) -> list[float]:
    box = getattr(page, name)
    return [round(float(value), 3) for value in box]


def _render_pages(path: Path) -> tuple[list[np.ndarray], list[dict[str, float | int]]]:
    document = pdfium.PdfDocument(path)
    pages: list[np.ndarray] = []
    stats: list[dict[str, float | int]] = []
    try:
        for index in range(len(document)):
            page = document[index]
            try:
                bitmap = page.render(scale=1, rev_byteorder=True, prefer_bgrx=True)
                pixels = np.asarray(bitmap.to_pil().convert("L"))
                pages.append(pixels)
                stats.append(
                    {
                        "page": index,
                        "width": int(pixels.shape[1]),
                        "height": int(pixels.shape[0]),
                        "standard_deviation": round(float(pixels.std()), 3),
                        "dark_pixel_ratio": round(float(np.mean(pixels < 245)), 6),
                    }
                )
            finally:
                page.close()
    finally:
        document.close()
    return pages, stats


def _embedded_files_present(reader: PdfReader) -> bool:
    try:
        names = reader.trailer["/Root"].get("/Names")
        return bool(names and names.get("/EmbeddedFiles"))
    except Exception:
        return False


def validate_export(source_path: Path, output_path: Path, secure: bool) -> dict[str, object]:
    source = PdfReader(source_path)
    output = PdfReader(output_path)
    errors: list[str] = []
    if len(source.pages) != len(output.pages):
        errors.append("Page count differs from the source PDF")

    compared_pages = min(len(source.pages), len(output.pages))
    for index in range(compared_pages):
        source_page = source.pages[index]
        output_page = output.pages[index]
        if _box(source_page, "mediabox") != _box(output_page, "mediabox"):
            errors.append(f"Page {index + 1} MediaBox differs")
        if _box(source_page, "cropbox") != _box(output_page, "cropbox"):
            errors.append(f"Page {index + 1} CropBox differs")
        source_rotation = int(source_page.get("/Rotate", 0) or 0) % 360
        output_rotation = int(output_page.get("/Rotate", 0) or 0) % 360
        if source_rotation != output_rotation:
            errors.append(f"Page {index + 1} rotation differs")
        if secure and output_page.get("/Annots"):
            errors.append(f"Page {index + 1} retains annotations in secure output")

    source_renders, source_stats = _render_pages(source_path)
    output_renders, output_stats = _render_pages(output_path)
    visual_correlations: list[float] = []
    for source_page, output_page, source_pixels, output_pixels in zip(
        source_stats, output_stats, source_renders, output_renders, strict=False
    ):
        if output_page["width"] <= 0 or output_page["height"] <= 0:
            errors.append(f"Page {int(output_page['page']) + 1} did not render")
        if (
            float(source_page["standard_deviation"]) > 2
            and float(output_page["standard_deviation"]) < 0.5
        ):
            errors.append(f"Page {int(output_page['page']) + 1} rendered blank")
        correlation = 0.0
        if source_pixels.shape == output_pixels.shape:
            source_flat = source_pixels.astype(np.float32).ravel()
            output_flat = output_pixels.astype(np.float32).ravel()
            if source_flat.std() > 1 and output_flat.std() > 1:
                correlation = float(np.corrcoef(source_flat, output_flat)[0, 1])
        visual_correlations.append(round(correlation, 4))
        if correlation < 0.25:
            errors.append(f"Page {int(output_page['page']) + 1} visual orientation differs")

    if secure and _embedded_files_present(output):
        errors.append("Secure output retains embedded files")

    return {
        "valid": not errors,
        "errors": errors,
        "page_count": len(output.pages),
        "boxes_and_rotation_match": not any(
            "Box differs" in error or "rotation differs" in error for error in errors
        ),
        "all_pages_rendered": not any(
            "did not render" in error or "rendered blank" in error for error in errors
        ),
        "visual_alignment_passed": not any(
            "visual orientation differs" in error for error in errors
        ),
        "secure_output": secure,
        "annotations_removed": secure and not any("annotations" in error for error in errors),
        "embedded_files_removed": secure and not _embedded_files_present(output),
        "render_stats": output_stats,
        "visual_correlations": visual_correlations,
    }
