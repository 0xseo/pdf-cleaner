from __future__ import annotations

from collections.abc import Iterable

import cv2
import numpy as np
import pypdfium2 as pdfium
import pytesseract
from PIL import Image
from pypdf import PdfReader
from pytesseract import Output

from .base import DetectionContext, DetectionResult

FOREGROUND_DARK_CUTOFF = 240
OCR_PRINT_CONFIDENCE_THRESHOLD = 93
OCR_DARK_CORE_CUTOFF = 85
PRESERVE_DILATION_SIZE = 5
HARD_PRESERVE_DILATION_SIZE = 3
HANDWRITING_OVERRIDE_DILATION_SIZE = 3
REMOVE_DILATION_SIZE = 7
FAINT_GROW_SIZE = 11
FAINT_BACKGROUND_SIZE = 15
FAINT_GRAY_MAXIMUM = 250
FAINT_LOCAL_CONTRAST_MINIMUM = 5
STRUCTURAL_MIN_SPAN_DIVISOR = 25
STRUCTURAL_MIN_ASPECT_RATIO = 6


def _clean_binary(mask: np.ndarray, minimum_area: int = 4) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    cleaned = np.zeros_like(mask)
    for label in range(1, count):
        if int(stats[label, cv2.CC_STAT_AREA]) >= minimum_area:
            cleaned[labels == label] = 255
    return cleaned


def _filter_line_components(
    mask: np.ndarray, minimum_span: int, horizontal: bool
) -> np.ndarray:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    filtered = np.zeros_like(mask)
    for label in range(1, count):
        width = int(stats[label, cv2.CC_STAT_WIDTH])
        height = int(stats[label, cv2.CC_STAT_HEIGHT])
        span = width if horizontal else height
        thickness = height if horizontal else width
        if span >= minimum_span and span >= thickness * STRUCTURAL_MIN_ASPECT_RATIO:
            filtered[labels == label] = 255
    return filtered


def _page_point_to_pixel(
    x: float,
    y: float,
    crop_box: list[float],
    rotation: int,
    width: int,
    height: int,
) -> tuple[int, int]:
    x0, y0, x1, y1 = crop_box
    page_width = max(x1 - x0, 1e-6)
    page_height = max(y1 - y0, 1e-6)
    relative_x = min(max((x - x0) / page_width, 0.0), 1.0)
    relative_y = min(max((y - y0) / page_height, 0.0), 1.0)

    if rotation == 90:
        display_x, display_y = relative_y, relative_x
    elif rotation == 180:
        display_x, display_y = 1.0 - relative_x, relative_y
    elif rotation == 270:
        display_x, display_y = 1.0 - relative_y, 1.0 - relative_x
    else:
        display_x, display_y = relative_x, 1.0 - relative_y
    return round(display_x * (width - 1)), round(display_y * (height - 1))


def _draw_pdf_boxes(
    mask: np.ndarray,
    boxes: Iterable[tuple[float, float, float, float]],
    context: DetectionContext,
) -> int:
    height, width = mask.shape
    count = 0
    for left, bottom, right, top in boxes:
        corners = [
            _page_point_to_pixel(left, bottom, context.crop_box, context.rotation, width, height),
            _page_point_to_pixel(left, top, context.crop_box, context.rotation, width, height),
            _page_point_to_pixel(right, bottom, context.crop_box, context.rotation, width, height),
            _page_point_to_pixel(right, top, context.crop_box, context.rotation, width, height),
        ]
        xs = [point[0] for point in corners]
        ys = [point[1] for point in corners]
        x_start, x_end = max(min(xs) - 2, 0), min(max(xs) + 2, width - 1)
        y_start, y_end = max(min(ys) - 2, 0), min(max(ys) + 2, height - 1)
        if x_end > x_start and y_end > y_start:
            cv2.rectangle(mask, (x_start, y_start), (x_end, y_end), 255, thickness=-1)
            count += 1
    return count


class OpenCvBaselineDetector:
    name = "opencv-print-aware-baseline"
    version = "0.5.1"

    def _foreground(self, image: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        smooth = cv2.GaussianBlur(gray, (3, 3), 0)
        adaptive = cv2.adaptiveThreshold(
            smooth,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            35,
            13,
        )
        dark = np.where(gray < FOREGROUND_DARK_CUTOFF, 255, 0).astype(np.uint8)
        return _clean_binary(cv2.bitwise_and(adaptive, dark))

    def _pdf_text_regions(
        self, shape: tuple[int, int], context: DetectionContext
    ) -> tuple[np.ndarray, int]:
        region_mask = np.zeros(shape, dtype=np.uint8)
        document = pdfium.PdfDocument(context.pdf_path)
        boxes: list[tuple[float, float, float, float]] = []
        try:
            page = document[context.page_index]
            try:
                text_page = page.get_textpage()
                try:
                    for index in range(text_page.count_chars()):
                        try:
                            box = text_page.get_charbox(index, loose=True)
                        except TypeError:
                            box = text_page.get_charbox(index)
                        boxes.append(tuple(float(value) for value in box))
                finally:
                    text_page.close()
            finally:
                page.close()
        except Exception:
            boxes = []
        finally:
            document.close()
        return region_mask, _draw_pdf_boxes(region_mask, boxes, context)

    def _ocr_regions(self, image: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
        printed_mask = np.zeros(image.shape[:2], dtype=np.uint8)
        handwriting_mask = np.zeros(image.shape[:2], dtype=np.uint8)
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        count = 0
        try:
            data = pytesseract.image_to_data(
                Image.fromarray(image), output_type=Output.DICT, config="--psm 11"
            )
            for index, text in enumerate(data["text"]):
                try:
                    confidence = float(data["conf"][index])
                except (TypeError, ValueError):
                    confidence = -1
                if confidence < 0 or not str(text).strip():
                    continue
                left = int(data["left"][index])
                top = int(data["top"][index])
                right = left + int(data["width"][index])
                bottom = top + int(data["height"][index])
                if confidence >= OCR_PRINT_CONFIDENCE_THRESHOLD:
                    cv2.rectangle(printed_mask, (left, top), (right, bottom), 255, thickness=-1)
                else:
                    width = max(right - left, 1)
                    height = max(bottom - top, 1)
                    roi = gray[
                        max(top, 0) : min(bottom, gray.shape[0]),
                        max(left, 0) : min(right, gray.shape[1]),
                    ]
                    ink = roi[roi < 232]
                    if ink.size and float(ink.mean()) >= 165 and width / height <= 12:
                        cv2.rectangle(
                            handwriting_mask,
                            (left, top),
                            (right, bottom),
                            255,
                            thickness=-1,
                        )
                    elif ink.size:
                        clipped_top = max(top, 0)
                        clipped_left = max(left, 0)
                        target = printed_mask[
                            clipped_top : clipped_top + roi.shape[0],
                            clipped_left : clipped_left + roi.shape[1],
                        ]
                        target[roi < OCR_DARK_CORE_CUTOFF] = 255
                count += 1
        except (pytesseract.TesseractError, FileNotFoundError):
            return printed_mask, handwriting_mask, 0
        return printed_mask, handwriting_mask, count

    def _structural_lines(self, foreground: np.ndarray) -> tuple[np.ndarray, int]:
        height, width = foreground.shape
        horizontal_source = cv2.morphologyEx(
            foreground,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (9, 1)),
        )
        vertical_source = cv2.morphologyEx(
            foreground,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT, (1, 9)),
        )
        horizontal_span = max(width // STRUCTURAL_MIN_SPAN_DIVISOR, 40)
        vertical_span = max(height // STRUCTURAL_MIN_SPAN_DIVISOR, 40)
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (horizontal_span, 1))
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, vertical_span))
        horizontal = cv2.morphologyEx(horizontal_source, cv2.MORPH_OPEN, horizontal_kernel)
        vertical = cv2.morphologyEx(vertical_source, cv2.MORPH_OPEN, vertical_kernel)
        horizontal = _filter_line_components(horizontal, horizontal_span, horizontal=True)
        vertical = _filter_line_components(vertical, vertical_span, horizontal=False)
        lines = cv2.bitwise_or(horizontal, vertical)
        count, _, stats, _ = cv2.connectedComponentsWithStats(lines, connectivity=8)
        meaningful = sum(int(stats[label, cv2.CC_STAT_AREA]) >= 20 for label in range(1, count))
        return lines, meaningful

    def _printed_components(self, image: np.ndarray, foreground: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(foreground, connectivity=8)
        printed = np.zeros_like(foreground)
        for label in range(1, count):
            if int(stats[label, cv2.CC_STAT_AREA]) < 4:
                continue
            component = labels == label
            values = gray[component]
            mean_intensity = float(values.mean())
            dark_fraction = float(np.count_nonzero(values < 120)) / float(values.size)
            print_like = mean_intensity <= 145 and dark_fraction >= 0.35
            if print_like:
                printed[component] = 255
        return printed

    def _annotation_regions(self, shape: tuple[int, int], context: DetectionContext) -> np.ndarray:
        mask = np.zeros(shape, dtype=np.uint8)
        boxes: list[tuple[float, float, float, float]] = []
        try:
            page = PdfReader(context.pdf_path).pages[context.page_index]
            for annotation_ref in page.get("/Annots") or []:
                annotation = annotation_ref.get_object()
                if str(annotation.get("/Subtype", "")) not in {"/Ink", "/FreeText", "/Stamp"}:
                    continue
                rectangle = annotation.get("/Rect")
                if rectangle and len(rectangle) == 4:
                    boxes.append(tuple(float(value) for value in rectangle))
        except Exception:
            return mask
        _draw_pdf_boxes(mask, boxes, context)
        return mask

    def _colored_strokes(self, image: np.ndarray, foreground: np.ndarray) -> np.ndarray:
        hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
        colorful = np.where((hsv[:, :, 1] >= 70) & (hsv[:, :, 2] <= 245), 255, 0).astype(np.uint8)
        colorful = cv2.bitwise_and(colorful, foreground)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(colorful, connectivity=8)
        selected = np.zeros_like(colorful)
        maximum_area = max(int(foreground.size * 0.0015), 40)
        for label in range(1, count):
            area = int(stats[label, cv2.CC_STAT_AREA])
            box_area = int(stats[label, cv2.CC_STAT_WIDTH] * stats[label, cv2.CC_STAT_HEIGHT])
            fill_ratio = area / max(box_area, 1)
            if 6 <= area <= maximum_area and fill_ratio <= 0.62:
                selected[labels == label] = 255
        return selected

    def _grow_faint_strokes(self, image: np.ndarray, seeds: np.ndarray) -> np.ndarray:
        if cv2.countNonZero(seeds) == 0:
            return seeds.copy()
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        background = cv2.morphologyEx(
            gray,
            cv2.MORPH_CLOSE,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (FAINT_BACKGROUND_SIZE, FAINT_BACKGROUND_SIZE)
            ),
        )
        contrast = background.astype(np.int16) - gray.astype(np.int16)
        faint = np.where(
            (gray < FAINT_GRAY_MAXIMUM) & (contrast >= FAINT_LOCAL_CONTRAST_MINIMUM),
            255,
            0,
        ).astype(np.uint8)
        neighborhood = cv2.dilate(
            seeds,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (FAINT_GROW_SIZE, FAINT_GROW_SIZE)),
            iterations=1,
        )
        return cv2.bitwise_or(seeds, cv2.bitwise_and(faint, neighborhood))

    def detect(self, image: np.ndarray, context: DetectionContext) -> DetectionResult:
        foreground = self._foreground(image)
        pdf_regions, pdf_region_count = self._pdf_text_regions(foreground.shape, context)
        ocr_regions, ocr_handwriting_regions, ocr_region_count = self._ocr_regions(image)
        structural_lines, structural_line_count = self._structural_lines(foreground)

        pdf_text_strokes = cv2.bitwise_and(foreground, pdf_regions)
        ocr_text_strokes = cv2.bitwise_and(foreground, ocr_regions)
        printed_components = self._printed_components(image, foreground)
        soft_preserve = cv2.dilate(
            printed_components,
            np.ones((PRESERVE_DILATION_SIZE, PRESERVE_DILATION_SIZE), dtype=np.uint8),
            iterations=1,
        )

        annotation_regions = self._annotation_regions(foreground.shape, context)
        annotation_strokes = cv2.bitwise_and(foreground, annotation_regions)
        colored_strokes = self._colored_strokes(image, foreground)
        strong_handwriting_evidence = cv2.bitwise_or(annotation_strokes, colored_strokes)
        handwriting_evidence = strong_handwriting_evidence.copy()
        ocr_handwriting_strokes = cv2.bitwise_and(foreground, ocr_handwriting_regions)
        handwriting_evidence = cv2.bitwise_or(handwriting_evidence, ocr_handwriting_strokes)
        handwriting_override = cv2.dilate(
            strong_handwriting_evidence,
            cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (HANDWRITING_OVERRIDE_DILATION_SIZE, HANDWRITING_OVERRIDE_DILATION_SIZE),
            ),
            iterations=1,
        )
        hard_text_strokes = cv2.bitwise_or(pdf_text_strokes, ocr_text_strokes)
        hard_preserve = cv2.dilate(
            hard_text_strokes,
            np.ones(
                (HARD_PRESERVE_DILATION_SIZE, HARD_PRESERVE_DILATION_SIZE), dtype=np.uint8
            ),
            iterations=1,
        )
        soft_preserve = cv2.bitwise_and(soft_preserve, cv2.bitwise_not(handwriting_override))
        text_preserve = cv2.bitwise_or(hard_preserve, soft_preserve)

        candidate = cv2.bitwise_and(foreground, cv2.bitwise_not(text_preserve))
        candidate = cv2.bitwise_and(candidate, cv2.bitwise_not(structural_lines))
        candidate = cv2.bitwise_or(candidate, handwriting_evidence)
        candidate = self._grow_faint_strokes(image, candidate)
        remove_kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (REMOVE_DILATION_SIZE, REMOVE_DILATION_SIZE)
        )
        candidate = cv2.dilate(candidate, remove_kernel, iterations=1)
        candidate = cv2.bitwise_and(candidate, cv2.bitwise_not(text_preserve))
        visible_structure = cv2.bitwise_and(structural_lines, cv2.bitwise_not(candidate))
        preserve = cv2.bitwise_or(text_preserve, visible_structure)
        automatic = candidate.copy()
        review = candidate.copy()

        total_pixels = float(foreground.size)
        review_ratio = cv2.countNonZero(review) / total_pixels
        preserve_ratio = cv2.countNonZero(preserve) / total_pixels
        risk_score = min(1.0, review_ratio * 14 + preserve_ratio * 0.35)
        if review_ratio > 0.08:
            risk_level = "manual"
        elif review_ratio > 0.0005:
            risk_level = "review"
        else:
            risk_level = "auto"

        return DetectionResult(
            candidate_mask=candidate,
            remove_mask=automatic,
            preserve_mask=preserve,
            review_mask=review,
            structural_line_mask=structural_lines,
            risk_score=round(risk_score, 4),
            risk_level=risk_level,
            pdf_text_regions=pdf_region_count,
            ocr_text_regions=ocr_region_count,
            structural_line_regions=structural_line_count,
        )
