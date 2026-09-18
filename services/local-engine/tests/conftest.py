from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from app import config, storage
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir()
    monkeypatch.setattr(config, "JOBS_ROOT", jobs_root)
    monkeypatch.setattr(storage, "JOBS_ROOT", jobs_root)
    with TestClient(app) as test_client:
        yield test_client
