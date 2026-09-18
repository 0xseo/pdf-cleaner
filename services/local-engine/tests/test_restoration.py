from __future__ import annotations

import numpy as np
from app.restoration import restore_image, restore_with_manual_clear


def test_restoration_never_changes_pixels_outside_mask() -> None:
    source = np.full((80, 120, 3), 245, dtype=np.uint8)
    source[38:42, 10:110] = 20
    mask = np.zeros((80, 120), dtype=np.uint8)
    mask[30:50, 48:66] = 255

    restored = restore_image(source, mask)

    assert np.array_equal(restored[mask == 0], source[mask == 0])
    assert np.all(restored[mask > 0] == 245)


def test_manual_removal_is_white_instead_of_inpainted() -> None:
    source = np.full((40, 60, 3), 245, dtype=np.uint8)
    source[18:22, 5:55] = 15
    automatic = np.zeros((40, 60), dtype=np.uint8)
    automatic[15:25, 8:18] = 255
    remove = automatic.copy()
    remove[15:25, 35:48] = 255

    restored = restore_with_manual_clear(source, remove, automatic)

    manual_only = (remove > 0) & (automatic == 0)
    assert np.all(restored[manual_only] == 255)
    assert np.array_equal(restored[remove == 0], source[remove == 0])
    assert np.all(restored[automatic > 0] == 245)


def test_structure_is_redrawn_after_overlapping_handwriting_is_cleared() -> None:
    source = np.full((40, 60, 3), 255, dtype=np.uint8)
    source[20, 5:55] = [20, 45, 60]
    source[10:31, 28:33] = 90
    remove = np.zeros((40, 60), dtype=np.uint8)
    remove[8:33, 26:35] = 255
    structure = np.zeros((40, 60), dtype=np.uint8)
    structure[20, 5:55] = 255

    restored = restore_image(source, remove, structure)

    assert np.all(restored[15, 30] == 255)
    assert np.array_equal(restored[20, 30], np.array([20, 45, 60], dtype=np.uint8))
    assert np.array_equal(restored[20, 10], source[20, 10])
    assert np.array_equal(restored[remove == 0], source[remove == 0])
