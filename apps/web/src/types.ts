export type PageStatus = 'pending' | 'analyzing' | 'ready' | 'error'
export type RiskLevel = 'auto' | 'review' | 'manual'

export interface PageInfo {
  index: number
  width_points: number
  height_points: number
  media_box: number[]
  crop_box: number[]
  rotation: number
  annotation_count: number
  ink_annotation_count: number
  text_character_count: number
  status: PageStatus
  risk_level: RiskLevel
  risk_score: number
  error: string | null
}

export interface JobInfo {
  id: string
  display_name: string
  source_sha256: string
  page_count: number
  created_at: string
  pages: PageInfo[]
}

export interface AnalysisResult {
  page: PageInfo
  pixel_width: number
  pixel_height: number
  dpi: number
  candidate_ratio: number
  automatic_remove_ratio: number
  preserve_ratio: number
  pdf_text_regions: number
  ocr_text_regions: number
  structural_line_regions: number
  revision: number
  source_url: string
  cleaned_url: string
  candidate_mask_url: string
  remove_mask_url: string
  preserve_mask_url: string
  review_mask_url: string
}

export interface ExportResult {
  mode: 'secure' | 'overlay'
  filename: string
  download_url: string
  validated: boolean
  validation_report: Record<string, unknown>
}

export interface ProjectExportResult {
  filename: string
  download_url: string
}
