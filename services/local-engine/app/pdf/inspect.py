from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
from pypdf import PdfReader

HANDWRITING_ANNOTATIONS = {"/Ink", "/FreeText", "/Stamp"}


def _box_values(box: object) -> list[float]:
    return [float(value) for value in box]


def inspect_pdf(path: Path) -> list[dict[str, object]]:
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise ValueError("Encrypted PDFs are not supported")

    pdf = pdfium.PdfDocument(path)
    pages: list[dict[str, object]] = []
    try:
        for index, source_page in enumerate(reader.pages):
            annotations = source_page.get("/Annots") or []
            annotation_count = len(annotations)
            ink_count = 0
            for annotation_ref in annotations:
                try:
                    subtype = str(annotation_ref.get_object().get("/Subtype", ""))
                    if subtype in HANDWRITING_ANNOTATIONS:
                        ink_count += 1
                except Exception:
                    continue

            text_count = 0
            try:
                text_page = pdf[index].get_textpage()
                text_count = text_page.count_chars()
                text_page.close()
            except Exception:
                text_count = 0

            media_box = _box_values(source_page.mediabox)
            crop_box = _box_values(source_page.cropbox)
            rotation = int(source_page.get("/Rotate", 0) or 0) % 360
            crop_width = abs(crop_box[2] - crop_box[0])
            crop_height = abs(crop_box[3] - crop_box[1])
            width_points, height_points = (
                (crop_height, crop_width) if rotation in {90, 270} else (crop_width, crop_height)
            )
            pages.append(
                {
                    "index": index,
                    "width_points": width_points,
                    "height_points": height_points,
                    "media_box": media_box,
                    "crop_box": crop_box,
                    "rotation": rotation,
                    "annotation_count": annotation_count,
                    "ink_annotation_count": ink_count,
                    "text_character_count": text_count,
                    "status": "pending",
                    "risk_level": "review",
                    "risk_score": 0.0,
                    "error": None,
                }
            )
    finally:
        pdf.close()
    return pages
