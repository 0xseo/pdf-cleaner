from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject
from reportlab.lib.colors import HexColor, black
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIR = ROOT / "tests" / "fixtures"
OUTPUT = FIXTURE_DIR / "baseline_exam.pdf"


def draw_exam_page(pdf: canvas.Canvas, width: float, height: float, title: str) -> None:
    pdf.setFillColor(black)
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(42, height - 45, title)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(42, height - 68, "Name: ____________________    Score: __________")
    pdf.drawString(42, height - 100, "1. Solve the equation and show your work.")
    pdf.setFont("Helvetica-Bold", 13)
    pdf.drawString(72, height - 130, "2x + 7 = 19")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(42, height - 170, "2. Complete the table.")
    table_left = 52
    table_top = height - 195
    column_width = 92
    row_height = 30
    for column in range(4):
        x = table_left + column * column_width
        pdf.line(x, table_top, x, table_top - row_height * 3)
    for row in range(4):
        y = table_top - row * row_height
        pdf.line(table_left, y, table_left + column_width * 3, y)
    pdf.drawString(table_left + 12, table_top - 20, "x")
    pdf.drawString(table_left + column_width + 12, table_top - 20, "1")
    pdf.drawString(table_left + column_width * 2 + 12, table_top - 20, "2")
    pdf.drawString(42, table_top - 125, "3. Circle the correct graph and explain your choice.")
    pdf.circle(120, table_top - 210, 46)
    pdf.line(74, table_top - 210, 166, table_top - 210)
    pdf.line(120, table_top - 256, 120, table_top - 164)
    pdf.line(84, table_top - 242, 154, table_top - 177)

    # Deliberately colored, thin strokes exercise the conservative ink baseline.
    pdf.setStrokeColor(HexColor("#315ec7"))
    pdf.setLineWidth(1.4)
    path = pdf.beginPath()
    path.moveTo(205, height - 123)
    path.curveTo(235, height - 98, 250, height - 155, 285, height - 120)
    pdf.drawPath(path)
    pdf.circle(330, table_top - 45, 18)
    pdf.setStrokeColor(black)


def add_ink_annotation(writer: PdfWriter, page_number: int) -> None:
    annotation = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Ink"),
            NameObject("/Rect"): ArrayObject(
                [FloatObject(300), FloatObject(600), FloatObject(420), FloatObject(680)]
            ),
            NameObject("/InkList"): ArrayObject(
                [
                    ArrayObject(
                        [
                            FloatObject(305),
                            FloatObject(620),
                            FloatObject(340),
                            FloatObject(660),
                            FloatObject(380),
                            FloatObject(615),
                            FloatObject(415),
                            FloatObject(650),
                        ]
                    )
                ]
            ),
            NameObject("/C"): ArrayObject([FloatObject(0.8), FloatObject(0.1), FloatObject(0.1)]),
            NameObject("/F"): NumberObject(4),
        }
    )
    writer.add_annotation(page_number=page_number, annotation=annotation)


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    draft = FIXTURE_DIR / "baseline_exam.draft.pdf"
    pdf = canvas.Canvas(str(draft), pagesize=A4)
    draw_exam_page(pdf, *A4, "Fixture Mathematics Review")
    pdf.showPage()
    page_size = landscape(A4)
    pdf.setPageSize(page_size)
    draw_exam_page(pdf, *page_size, "Fixture Landscape Review")
    pdf.showPage()
    pdf.save()

    reader = PdfReader(draft)
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    writer.pages[1].rotate(270)
    add_ink_annotation(writer, 0)
    with OUTPUT.open("wb") as stream:
        writer.write(stream)
    draft.unlink()


if __name__ == "__main__":
    main()
