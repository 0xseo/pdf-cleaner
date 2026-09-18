from __future__ import annotations

import base64
import hashlib
import io
import zipfile
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests" / "fixtures" / "baseline_exam.pdf"


def _upload(client: TestClient) -> dict[str, object]:
    with FIXTURE.open("rb") as stream:
        response = client.post(
            "/api/jobs", files={"file": ("baseline_exam.pdf", stream, "application/pdf")}
        )
    assert response.status_code == 201, response.text
    return response.json()


def _as_data_url(content: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(content).decode("ascii")


def _mask_alpha(content: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(content)).getchannel("A"))


def test_health_is_local(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "scope": "localhost-only"}


def test_cors_allows_only_local_and_production_origins(client: TestClient) -> None:
    for origin in (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "https://handwriting-eraser.0xseo94.com",
    ):
        response = client.options(
            "/api/health",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin

    rejected = client.options(
        "/api/health",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers


def test_end_to_end_analysis_mask_and_exports(client: TestClient) -> None:
    original_hash = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    job = _upload(client)
    assert job["page_count"] == 2
    assert job["source_sha256"] == original_hash
    assert job["pages"][0]["ink_annotation_count"] == 1
    assert job["pages"][1]["rotation"] == 270

    analyses: list[dict[str, object]] = []
    for page_index in range(2):
        response = client.post(f"/api/jobs/{job['id']}/pages/{page_index}/analyze")
        assert response.status_code == 200, response.text
        analysis = response.json()
        analyses.append(analysis)
        assert analysis["pixel_width"] > 1000
        assert analysis["pixel_height"] > 1000
        assert analysis["candidate_ratio"] > 0
        assert analysis["preserve_ratio"] > 0
        assert analysis["automatic_remove_ratio"] == analysis["candidate_ratio"]
        assert analysis["pdf_text_regions"] > 0
        for artifact in (
            "source",
            "candidate",
            "remove",
            "preserve",
            "structural",
            "cleaned",
        ):
            artifact_response = client.get(
                f"/api/jobs/{job['id']}/pages/{page_index}/artifacts/{artifact}"
            )
            assert artifact_response.status_code == 200
            assert artifact_response.headers["content-type"] == "image/png"

        candidate_response = client.get(
            f"/api/jobs/{job['id']}/pages/{page_index}/artifacts/candidate"
        )
        remove_response = client.get(
            f"/api/jobs/{job['id']}/pages/{page_index}/artifacts/remove"
        )
        assert np.array_equal(
            _mask_alpha(candidate_response.content), _mask_alpha(remove_response.content)
        )

    remove_response = client.get(f"/api/jobs/{job['id']}/pages/0/artifacts/remove")
    preserve_response = client.get(f"/api/jobs/{job['id']}/pages/0/artifacts/preserve")
    update_response = client.patch(
        f"/api/jobs/{job['id']}/pages/0/mask",
        json={
            "remove_mask": _as_data_url(remove_response.content),
            "preserve_mask": _as_data_url(preserve_response.content),
        },
    )
    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["revision"] == analyses[0]["revision"] + 1

    project_response = client.post(f"/api/jobs/{job['id']}/project")
    assert project_response.status_code == 200, project_response.text
    project_download = client.get(project_response.json()["download_url"])
    assert project_download.status_code == 200
    assert project_download.headers["content-type"].startswith(
        "application/vnd.pdf-eraser+zip"
    )
    with zipfile.ZipFile(io.BytesIO(project_download.content)) as project_archive:
        project_names = set(project_archive.namelist())
        assert {"project.json", "job.json", "source.pdf"}.issubset(project_names)
        assert "pages/00000/remove.png" in project_names
        assert project_archive.read("source.pdf") == FIXTURE.read_bytes()

    imported_response = client.post(
        "/api/projects",
        files={
            "file": (
                project_response.json()["filename"],
                project_download.content,
                "application/vnd.pdf-eraser+zip",
            )
        },
    )
    assert imported_response.status_code == 201, imported_response.text
    imported_job = imported_response.json()
    assert imported_job["id"] != job["id"]
    assert imported_job["source_sha256"] == original_hash
    assert all(page["status"] == "ready" for page in imported_job["pages"])
    imported_analysis_response = client.post(
        f"/api/jobs/{imported_job['id']}/pages/0/analyze"
    )
    assert imported_analysis_response.status_code == 200
    assert imported_analysis_response.json()["revision"] == update_response.json()["revision"]
    imported_remove = client.get(
        f"/api/jobs/{imported_job['id']}/pages/0/artifacts/remove"
    )
    assert imported_remove.content == remove_response.content

    for mode in ("secure", "overlay"):
        export_response = client.post(f"/api/jobs/{job['id']}/export", json={"mode": mode})
        assert export_response.status_code == 200, export_response.text
        export = export_response.json()
        assert export["validated"] is True
        assert export["validation_report"]["all_pages_rendered"] is True
        assert export["validation_report"]["visual_alignment_passed"] is True
        assert min(export["validation_report"]["visual_correlations"]) > 0.8
        downloaded = client.get(export["download_url"])
        assert downloaded.status_code == 200
        reader = PdfReader(io.BytesIO(downloaded.content))
        assert len(reader.pages) == 2
        if mode == "secure":
            assert all(not page.get("/Annots") for page in reader.pages)

    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == original_hash


def test_rejects_non_pdf_and_invalid_job_id(client: TestClient) -> None:
    response = client.post("/api/jobs", files={"file": ("notes.txt", b"not a pdf", "text/plain")})
    assert response.status_code == 400
    assert client.get("/api/jobs/not-valid").status_code == 404

    unsafe_project = io.BytesIO()
    with zipfile.ZipFile(unsafe_project, "w") as archive:
        archive.writestr("../outside", b"unsafe")
        archive.writestr("project.json", b"{}")
        archive.writestr("job.json", b"{}")
        archive.writestr("source.pdf", b"%PDF-invalid")
    project_response = client.post(
        "/api/projects",
        files={"file": ("unsafe.pdferaser", unsafe_project.getvalue(), "application/zip")},
    )
    assert project_response.status_code == 400
    assert "unsafe path" in project_response.json()["detail"]
