from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local PDF through the full QA pipeline")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--output-dir", type=Path, default=Path("tmp/pdfs/sample-qa"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.pdf.is_file():
        raise SystemExit("Input PDF does not exist")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    job_id: str | None = None
    with httpx.Client(base_url=args.api, timeout=180) as client:
        try:
            with args.pdf.open("rb") as stream:
                response = client.post(
                    "/api/jobs",
                    files={"file": ("qa-input.pdf", stream, "application/pdf")},
                )
            response.raise_for_status()
            job = response.json()
            job_id = job["id"]
            for page_index in range(job["page_count"]):
                analysis = client.post(f"/api/jobs/{job_id}/pages/{page_index}/analyze")
                analysis.raise_for_status()
                print(f"analyzed {page_index + 1}/{job['page_count']}", flush=True)

            export_response = client.post(f"/api/jobs/{job_id}/export", json={"mode": "overlay"})
            export_response.raise_for_status()
            export = export_response.json()
            download = client.get(export["download_url"])
            download.raise_for_status()
            output_path = args.output_dir / "exported-output.pdf"
            output_path.write_bytes(download.content)
            report_path = args.output_dir / "validation.json"
            report_path.write_text(
                json.dumps(export["validation_report"], indent=2), encoding="utf-8"
            )
            print(f"validated output: {output_path}")
        finally:
            if job_id:
                client.delete(f"/api/jobs/{job_id}")


if __name__ == "__main__":
    main()
