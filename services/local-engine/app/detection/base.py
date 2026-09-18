from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np


@dataclass(slots=True)
class DetectionContext:
    pdf_path: Path
    page_index: int
    dpi: int
    crop_box: list[float]
    rotation: int


@dataclass(slots=True)
class DetectionResult:
    candidate_mask: np.ndarray
    remove_mask: np.ndarray
    preserve_mask: np.ndarray
    review_mask: np.ndarray
    structural_line_mask: np.ndarray
    risk_score: float
    risk_level: str
    pdf_text_regions: int
    ocr_text_regions: int
    structural_line_regions: int


class PageDetector(Protocol):
    name: str
    version: str

    def detect(self, image: np.ndarray, context: DetectionContext) -> DetectionResult: ...
