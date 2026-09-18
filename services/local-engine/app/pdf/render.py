from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image


def render_page(pdf_path: Path, page_index: int, dpi: int, output_path: Path) -> Image.Image:
    document = pdfium.PdfDocument(pdf_path)
    try:
        if page_index < 0 or page_index >= len(document):
            raise IndexError("Page index out of range")
        page = document[page_index]
        try:
            bitmap = page.render(scale=dpi / 72, rev_byteorder=True, prefer_bgrx=True)
            image = bitmap.to_pil().convert("RGB")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(output_path, format="PNG", optimize=True)
            return image
        finally:
            page.close()
    finally:
        document.close()
