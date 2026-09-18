from pathlib import Path

import cv2
import numpy as np
import pytest
from app.detection.base import DetectionContext
from app.detection.opencv_detector import OpenCvBaselineDetector, _filter_line_components


def test_printed_components_are_preserved_and_pencil_candidates_are_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.full((260, 420, 3), 255, dtype=np.uint8)
    cv2.putText(image, "PRINTED TEXT", (24, 78), cv2.FONT_HERSHEY_SIMPLEX, 1, (35, 35, 35), 2)
    pencil_points = np.array([[35, 170], [90, 145], [145, 190], [210, 150], [275, 182]])
    cv2.polylines(image, [pencil_points], False, (195, 195, 195), 3, cv2.LINE_AA)

    detector = OpenCvBaselineDetector()
    monkeypatch.setattr(
        detector,
        "_pdf_text_regions",
        lambda shape, context: (np.zeros(shape, dtype=np.uint8), 0),
    )
    monkeypatch.setattr(
        detector,
        "_ocr_regions",
        lambda source: (
            np.zeros(source.shape[:2], dtype=np.uint8),
            np.zeros(source.shape[:2], dtype=np.uint8),
            0,
        ),
    )
    monkeypatch.setattr(
        detector,
        "_annotation_regions",
        lambda shape, context: np.zeros(shape, dtype=np.uint8),
    )
    context = DetectionContext(
        pdf_path=Path("unused.pdf"),
        page_index=0,
        dpi=300,
        crop_box=[0, 0, 420, 260],
        rotation=0,
    )

    result = detector.detect(image, context)
    foreground = detector._foreground(image)
    printed = foreground[35:95, 15:390]
    pencil = foreground[125:205, 20:300]

    assert cv2.countNonZero(result.preserve_mask[35:95, 15:390]) >= int(
        cv2.countNonZero(printed) * 0.9
    )
    assert cv2.countNonZero(result.remove_mask[125:205, 20:300]) >= int(
        cv2.countNonZero(pencil) * 0.8
    )
    assert np.array_equal(result.candidate_mask, result.remove_mask)
    assert np.array_equal(result.candidate_mask, result.review_mask)


def test_foreground_includes_faint_pencil_pixels() -> None:
    image = np.full((80, 120, 3), 255, dtype=np.uint8)
    cv2.line(image, (20, 40), (100, 40), (236, 236, 236), 3)

    foreground = OpenCvBaselineDetector()._foreground(image)

    assert cv2.countNonZero(foreground[35:46, 15:106]) > 0


def test_structural_filter_keeps_long_thin_lines_only() -> None:
    mask = np.zeros((80, 120), dtype=np.uint8)
    mask[20:22, 10:110] = 255
    mask[40:52, 60:63] = 255

    filtered = _filter_line_components(mask, minimum_span=40, horizontal=True)

    assert cv2.countNonZero(filtered[20:22, 10:110]) == 200
    assert cv2.countNonZero(filtered[40:52, 60:63]) == 0


def test_ocr_requires_93_confidence_before_protecting_print(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.full((60, 100, 3), 255, dtype=np.uint8)
    image[20:30, 10:40] = 180
    monkeypatch.setattr(
        "app.detection.opencv_detector.pytesseract.image_to_data",
        lambda *args, **kwargs: {
            "text": ["answer"],
            "conf": ["92"],
            "left": [10],
            "top": [20],
            "width": [30],
            "height": [10],
        },
    )

    printed, handwriting, count = OpenCvBaselineDetector()._ocr_regions(image)

    assert count == 1
    assert cv2.countNonZero(printed) == 0
    assert cv2.countNonZero(handwriting) > 0


def test_ocr_protects_print_at_93_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.full((60, 100, 3), 255, dtype=np.uint8)
    monkeypatch.setattr(
        "app.detection.opencv_detector.pytesseract.image_to_data",
        lambda *args, **kwargs: {
            "text": ["printed"],
            "conf": ["93"],
            "left": [10],
            "top": [20],
            "width": [30],
            "height": [10],
        },
    )

    printed, handwriting, count = OpenCvBaselineDetector()._ocr_regions(image)

    assert count == 1
    assert cv2.countNonZero(printed) > 0
    assert cv2.countNonZero(handwriting) == 0


def test_low_confidence_ocr_protects_only_very_dark_print_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.full((60, 100, 3), 255, dtype=np.uint8)
    image[23:27, 15:25] = 60
    monkeypatch.setattr(
        "app.detection.opencv_detector.pytesseract.image_to_data",
        lambda *args, **kwargs: {
            "text": ["mixed"],
            "conf": ["60"],
            "left": [10],
            "top": [20],
            "width": [30],
            "height": [10],
        },
    )

    printed, handwriting, count = OpenCvBaselineDetector()._ocr_regions(image)

    assert count == 1
    assert cv2.countNonZero(printed) == 40
    assert cv2.countNonZero(handwriting) == 0


def test_high_confidence_ocr_is_safe_as_the_first_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.full((40, 80, 3), 255, dtype=np.uint8)
    monkeypatch.setattr(
        "app.detection.opencv_detector.pytesseract.image_to_data",
        lambda *args, **kwargs: {
            "text": ["printed"],
            "conf": ["99"],
            "left": [10],
            "top": [10],
            "width": [30],
            "height": [10],
        },
    )

    printed, handwriting, count = OpenCvBaselineDetector()._ocr_regions(image)

    assert count == 1
    assert cv2.countNonZero(printed) > 0
    assert cv2.countNonZero(handwriting) == 0


def test_print_protection_uses_five_pixel_dilation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.full((21, 21, 3), 255, dtype=np.uint8)
    foreground = np.zeros((21, 21), dtype=np.uint8)
    foreground[10, 10] = 255
    detector = OpenCvBaselineDetector()
    monkeypatch.setattr(detector, "_foreground", lambda source: foreground)
    monkeypatch.setattr(
        detector,
        "_pdf_text_regions",
        lambda shape, context: (np.zeros(shape, dtype=np.uint8), 0),
    )
    monkeypatch.setattr(
        detector,
        "_ocr_regions",
        lambda source: (
            np.zeros(source.shape[:2], dtype=np.uint8),
            np.zeros(source.shape[:2], dtype=np.uint8),
            0,
        ),
    )
    monkeypatch.setattr(
        detector,
        "_structural_lines",
        lambda source: (np.zeros(source.shape, dtype=np.uint8), 0),
    )
    monkeypatch.setattr(
        detector,
        "_printed_components",
        lambda source, source_foreground: foreground,
    )
    monkeypatch.setattr(
        detector,
        "_annotation_regions",
        lambda shape, context: np.zeros(shape, dtype=np.uint8),
    )
    monkeypatch.setattr(
        detector,
        "_colored_strokes",
        lambda source, source_foreground: np.zeros(source.shape[:2], dtype=np.uint8),
    )
    context = DetectionContext(
        pdf_path=Path("unused.pdf"),
        page_index=0,
        dpi=300,
        crop_box=[0, 0, 21, 21],
        rotation=0,
    )

    result = detector.detect(image, context)

    assert cv2.countNonZero(result.preserve_mask) == 25
    assert cv2.countNonZero(cv2.bitwise_and(result.remove_mask, result.preserve_mask)) == 0


def test_remove_candidates_use_seven_pixel_elliptical_dilation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.full((21, 21, 3), 255, dtype=np.uint8)
    foreground = np.zeros((21, 21), dtype=np.uint8)
    foreground[10, 10] = 255
    detector = OpenCvBaselineDetector()
    monkeypatch.setattr(detector, "_foreground", lambda source: foreground)
    monkeypatch.setattr(
        detector,
        "_pdf_text_regions",
        lambda shape, context: (np.zeros(shape, dtype=np.uint8), 0),
    )
    monkeypatch.setattr(
        detector,
        "_ocr_regions",
        lambda source: (
            np.zeros(source.shape[:2], dtype=np.uint8),
            np.zeros(source.shape[:2], dtype=np.uint8),
            0,
        ),
    )
    monkeypatch.setattr(
        detector,
        "_structural_lines",
        lambda source: (np.zeros(source.shape, dtype=np.uint8), 0),
    )
    monkeypatch.setattr(
        detector,
        "_printed_components",
        lambda source, source_foreground: np.zeros(source_foreground.shape, dtype=np.uint8),
    )
    monkeypatch.setattr(
        detector,
        "_annotation_regions",
        lambda shape, context: np.zeros(shape, dtype=np.uint8),
    )
    monkeypatch.setattr(
        detector,
        "_colored_strokes",
        lambda source, source_foreground: np.zeros(source_foreground.shape, dtype=np.uint8),
    )
    context = DetectionContext(
        pdf_path=Path("unused.pdf"),
        page_index=0,
        dpi=300,
        crop_box=[0, 0, 21, 21],
        rotation=0,
    )

    result = detector.detect(image, context)

    assert result.remove_mask[10, 13] == 255
    assert result.remove_mask[10, 14] == 0
    assert result.remove_mask[7, 10] == 255
    assert result.remove_mask[6, 10] == 0


def test_faint_strokes_grow_only_near_existing_handwriting() -> None:
    image = np.full((41, 41, 3), 255, dtype=np.uint8)
    image[20, 20] = 150
    image[20, 23] = 246
    image[5, 5] = 246
    seeds = np.zeros((41, 41), dtype=np.uint8)
    seeds[20, 20] = 255

    grown = OpenCvBaselineDetector()._grow_faint_strokes(image, seeds)

    assert grown[20, 23] == 255
    assert grown[5, 5] == 0


def test_handwriting_overrides_soft_print_and_structural_preserve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = np.full((31, 31, 3), 255, dtype=np.uint8)
    foreground = np.zeros((31, 31), dtype=np.uint8)
    foreground[15, 2:29] = 255
    foreground[7:24, 15] = 255
    structure = np.zeros_like(foreground)
    structure[15, 2:29] = 255
    handwriting = np.zeros_like(foreground)
    handwriting[7:24, 15] = 255
    detector = OpenCvBaselineDetector()
    monkeypatch.setattr(detector, "_foreground", lambda source: foreground)
    monkeypatch.setattr(
        detector,
        "_pdf_text_regions",
        lambda shape, context: (np.zeros(shape, dtype=np.uint8), 0),
    )
    monkeypatch.setattr(
        detector,
        "_ocr_regions",
        lambda source: (
            np.zeros(source.shape[:2], dtype=np.uint8),
            np.zeros(source.shape[:2], dtype=np.uint8),
            0,
        ),
    )
    monkeypatch.setattr(detector, "_structural_lines", lambda source: (structure, 1))
    monkeypatch.setattr(
        detector,
        "_printed_components",
        lambda source, source_foreground: source_foreground,
    )
    monkeypatch.setattr(
        detector,
        "_annotation_regions",
        lambda shape, context: np.zeros(shape, dtype=np.uint8),
    )
    monkeypatch.setattr(
        detector,
        "_colored_strokes",
        lambda source, source_foreground: handwriting,
    )
    context = DetectionContext(
        pdf_path=Path("unused.pdf"),
        page_index=0,
        dpi=300,
        crop_box=[0, 0, 31, 31],
        rotation=0,
    )

    result = detector.detect(image, context)

    assert result.remove_mask[15, 15] == 255
    assert result.preserve_mask[15, 15] == 0
    assert result.preserve_mask[15, 3] == 255
    assert result.structural_line_mask[15, 15] == 255
    assert cv2.countNonZero(cv2.bitwise_and(result.remove_mask, result.preserve_mask)) == 0
