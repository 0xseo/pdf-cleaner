from __future__ import annotations

from pathlib import Path

import pikepdf
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from ..analysis import analyze_page
from ..qa import validate_export
from ..storage import get_job_dir, get_page_dir, load_job, safe_download_stem, write_json

HANDWRITING_ANNOTATIONS = {"/Ink", "/FreeText", "/Stamp"}
BOX_NAMES = ("/MediaBox", "/CropBox", "/BleedBox", "/TrimBox", "/ArtBox")


def _create_raster_pdf(job: dict[str, object], output_path: Path) -> None:
    pdf_canvas = canvas.Canvas(str(output_path), pagesize=(1, 1), pageCompression=1)
    for page in job["pages"]:
        index = int(page["index"])
        image = Image.open(get_page_dir(str(job["id"]), index) / "cleaned.png").convert("RGB")
        rotation = int(page["rotation"]) % 360
        if rotation:
            image = image.rotate(rotation, expand=True)
        crop_box = [float(value) for value in page["crop_box"]]
        width = abs(crop_box[2] - crop_box[0])
        height = abs(crop_box[3] - crop_box[1])
        pdf_canvas.setPageSize((width, height))
        pdf_canvas.drawImage(
            ImageReader(image), 0, 0, width=width, height=height, preserveAspectRatio=False
        )
        pdf_canvas.showPage()
    pdf_canvas.save()


def _copy_page_geometry(source_page: pikepdf.Page, target_page: pikepdf.Page) -> None:
    for name in BOX_NAMES:
        if name in source_page.obj:
            target_page.obj[name] = pikepdf.Array([float(value) for value in source_page.obj[name]])


def _set_rotation(page: pikepdf.Page, rotation: int) -> None:
    if rotation:
        page.obj["/Rotate"] = rotation
    elif "/Rotate" in page.obj:
        del page.obj["/Rotate"]


def _remove_handwriting_annotations(page: pikepdf.Page) -> None:
    annotations = page.obj.get("/Annots")
    if not annotations:
        return
    retained = pikepdf.Array()
    for annotation in annotations:
        subtype = str(annotation.get("/Subtype", ""))
        if subtype not in HANDWRITING_ANNOTATIONS:
            retained.append(annotation)
    if retained:
        page.obj["/Annots"] = retained
    else:
        del page.obj["/Annots"]


def _compose_pdf(source_path: Path, raster_path: Path, output_path: Path, secure: bool) -> None:
    with pikepdf.open(source_path) as source, pikepdf.open(raster_path) as raster:
        if secure:
            output = pikepdf.Pdf.new()
            for index, source_page in enumerate(source.pages):
                media_box = [float(value) for value in source_page.obj["/MediaBox"]]
                width = abs(media_box[2] - media_box[0])
                height = abs(media_box[3] - media_box[1])
                target_page = output.add_blank_page(page_size=(width, height))
                _copy_page_geometry(source_page, target_page)
                crop_box = [float(value) for value in source_page.obj.get("/CropBox", media_box)]
                target_page.add_overlay(raster.pages[index], pikepdf.Rectangle(*crop_box))
                _set_rotation(target_page, int(source_page.obj.get("/Rotate", 0)) % 360)
            output.save(output_path)
            output.close()
            return

        output = pikepdf.Pdf.new()
        output.pages.extend(source.pages)
        for index, page in enumerate(output.pages):
            media_box = [float(value) for value in page.obj["/MediaBox"]]
            crop_box = [float(value) for value in page.obj.get("/CropBox", media_box)]
            rotation = int(page.obj.get("/Rotate", 0)) % 360
            _set_rotation(page, 0)
            page.add_overlay(raster.pages[index], pikepdf.Rectangle(*crop_box))
            _set_rotation(page, rotation)
            _remove_handwriting_annotations(page)
        output.save(output_path)
        output.close()


def export_job(job_id: str, mode: str) -> tuple[Path, dict[str, object]]:
    if mode not in {"secure", "overlay"}:
        raise ValueError("Unsupported export mode")
    job = load_job(job_id)
    for page in job["pages"]:
        analyze_page(job_id, int(page["index"]))
    job = load_job(job_id)

    job_dir = get_job_dir(job_id)
    export_dir = job_dir / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    raster_path = export_dir / "cleaned-raster.pdf"
    _create_raster_pdf(job, raster_path)
    stem = safe_download_stem(str(job["display_name"]))
    output_name = f"{stem}_cleaned.pdf" if mode == "overlay" else f"{stem}_cleaned_secure.pdf"
    output_path = export_dir / output_name
    _compose_pdf(job_dir / "source.pdf", raster_path, output_path, secure=mode == "secure")
    report = validate_export(job_dir / "source.pdf", output_path, secure=mode == "secure")
    report_name = (
        f"{stem}_cleaned.validation.json"
        if mode == "overlay"
        else f"{stem}_cleaned_secure.validation.json"
    )
    write_json(export_dir / report_name, report)
    if not report["valid"]:
        output_path.unlink(missing_ok=True)
        raise RuntimeError("Export validation failed: " + "; ".join(report["errors"]))
    return output_path, report
