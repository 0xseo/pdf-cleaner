from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PageStatus = Literal["pending", "analyzing", "ready", "error"]
RiskLevel = Literal["auto", "review", "manual"]


class PageInfo(BaseModel):
    index: int
    width_points: float
    height_points: float
    media_box: list[float]
    crop_box: list[float]
    rotation: int
    annotation_count: int = 0
    ink_annotation_count: int = 0
    text_character_count: int = 0
    status: PageStatus = "pending"
    risk_level: RiskLevel = "review"
    risk_score: float = 0.0
    error: str | None = None


class JobInfo(BaseModel):
    id: str
    display_name: str
    source_sha256: str
    page_count: int
    created_at: str
    pages: list[PageInfo]


class AnalysisResult(BaseModel):
    page: PageInfo
    pixel_width: int
    pixel_height: int
    dpi: int
    candidate_ratio: float
    automatic_remove_ratio: float
    preserve_ratio: float
    pdf_text_regions: int
    ocr_text_regions: int
    structural_line_regions: int
    revision: int
    source_url: str
    cleaned_url: str
    candidate_mask_url: str
    remove_mask_url: str
    preserve_mask_url: str
    review_mask_url: str


class MaskUpdate(BaseModel):
    remove_mask: str = Field(description="PNG data URL for the removal mask")
    preserve_mask: str = Field(description="PNG data URL for the hard-preserve mask")


class ExportRequest(BaseModel):
    mode: Literal["secure", "overlay"] = "overlay"


class ExportResult(BaseModel):
    mode: Literal["secure", "overlay"]
    filename: str
    download_url: str
    validated: bool
    validation_report: dict[str, object]


class ProjectExportResult(BaseModel):
    filename: str
    download_url: str
