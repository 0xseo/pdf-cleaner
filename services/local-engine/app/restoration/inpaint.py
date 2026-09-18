from __future__ import annotations

import cv2
import numpy as np

BACKGROUND_FILL_SIZE = 31


def _redraw_structural_lines(
    source_rgb: np.ndarray,
    restored: np.ndarray,
    remove_mask: np.ndarray,
    structural_mask: np.ndarray,
) -> None:
    binary_structure = np.where(structural_mask > 0, 255, 0).astype(np.uint8)
    count, labels = cv2.connectedComponents(binary_structure, connectivity=8)
    for label in range(1, count):
        component = labels == label
        overlap = component & (remove_mask > 0)
        if not np.any(overlap):
            continue
        sample_pixels = source_rgb[component & (remove_mask == 0)]
        if sample_pixels.size == 0:
            continue
        visible_samples = sample_pixels[np.max(sample_pixels, axis=1) < 245]
        if visible_samples.size == 0:
            continue
        line_color = np.median(visible_samples, axis=0).astype(np.uint8)
        restored[overlap] = line_color


def restore_image(
    source_rgb: np.ndarray,
    remove_mask: np.ndarray,
    structural_mask: np.ndarray | None = None,
) -> np.ndarray:
    binary_mask = np.where(remove_mask > 0, 255, 0).astype(np.uint8)
    if cv2.countNonZero(binary_mask) == 0:
        return source_rgb.copy()
    restored = source_rgb.copy()
    background = cv2.morphologyEx(
        source_rgb,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (BACKGROUND_FILL_SIZE, BACKGROUND_FILL_SIZE)
        ),
    )
    restored[binary_mask > 0] = background[binary_mask > 0]
    if structural_mask is not None:
        _redraw_structural_lines(source_rgb, restored, binary_mask, structural_mask)
    return restored


def restore_with_manual_clear(
    source_rgb: np.ndarray,
    remove_mask: np.ndarray,
    automatic_mask: np.ndarray,
    structural_mask: np.ndarray | None = None,
) -> np.ndarray:
    binary_remove = np.where(remove_mask > 0, 255, 0).astype(np.uint8)
    binary_automatic = np.where(automatic_mask > 0, 255, 0).astype(np.uint8)
    automatic_remove = cv2.bitwise_and(binary_remove, binary_automatic)
    manual_clear = cv2.bitwise_and(binary_remove, cv2.bitwise_not(binary_automatic))
    restored = restore_image(source_rgb, automatic_remove, structural_mask)
    restored[manual_clear > 0] = 255
    return restored
