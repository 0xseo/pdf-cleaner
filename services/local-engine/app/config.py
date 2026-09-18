from __future__ import annotations

import os
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = Path(os.environ.get("PDF_CLEANER_RUNTIME_DIR", ENGINE_ROOT / "runtime")).resolve()
JOBS_ROOT = RUNTIME_ROOT / "jobs"
DEFAULT_ANALYSIS_DPI = 300
QA_RENDER_DPI = 72
STREAM_CHUNK_SIZE = 1024 * 1024


def ensure_runtime_dirs() -> None:
    JOBS_ROOT.mkdir(parents=True, exist_ok=True)
