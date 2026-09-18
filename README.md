# PDF Cleaner

Local-first review tool for removing later handwriting from irregular exam PDFs while preserving printed content. The browser UI talks only to a FastAPI engine bound to `127.0.0.1`; input PDFs are copied into random local job directories and are never overwritten.

## Development

Requirements: Node.js 20.19+, 22.13+, or 24+, Python 3.11+, and Tesseract available on `PATH`.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The local API listens on `http://127.0.0.1:8000`.

## Web Deployment

Pushes that change the web app on `main` deploy `apps/web/dist` through GitHub Pages. The production custom domain is `https://handwriting-eraser.0xseo94.com`, which should use a DNS `CNAME` record targeting `0xseo.github.io`.

The deployed HTTPS page still sends all PDF data only to the engine on `127.0.0.1`. The engine allows the exact production origin in addition to localhost development origins. Current Chrome versions ask the user for Local Network Access permission when a public page first contacts the loopback engine; denying that permission leaves the app offline.

### Search registration

After the custom domain resolves over HTTPS, verify that the following production URLs return `200` before requesting indexing:

- `https://handwriting-eraser.0xseo94.com/robots.txt`
- `https://handwriting-eraser.0xseo94.com/sitemap.xml`
- `https://handwriting-eraser.0xseo94.com/site.webmanifest`
- `https://handwriting-eraser.0xseo94.com/og-image.png`

In Google Search Console, add the domain or exact HTTPS URL-prefix property, complete ownership verification, submit `sitemap.xml` in the Sitemaps report, and inspect the canonical home URL. Validate the deployed JSON-LD with Google's Rich Results Test even though search appearance is not guaranteed.

In Naver Search Advisor, register the exact HTTPS site, complete ownership verification, then submit `sitemap.xml` under `요청 > 사이트맵 제출` and confirm that robots.txt is readable. If either service provides an HTML meta verification token, add only that service-issued token to `apps/web/index.html`; never commit account credentials.

The canonical URL, Open Graph URL, JSON-LD URL, sitemap, robots.txt, and manifest currently assume the production site is hosted at the domain root. Update all of them together if the public URL changes.

## Verification

```bash
npm run lint
npm test
npm run build
```

The engine tests generate and process a small fixture containing digital text, a table, colored strokes, an ink annotation, and a rotated page. Every export is reopened, compared with the source page geometry, and rendered page by page before the API reports success.

## PDF Export

The UI provides one `PDF로 내보내기` action. It keeps the source PDF structure and places the cleaned page result over it. Covered source content can remain inside the exported file, so this export is not suitable for securely deleting sensitive answers.

Runtime jobs are stored under `services/local-engine/runtime/` by default and are excluded from Git. Closing a job in the UI deletes its local job directory.

## Local Project Files

`작업 파일 저장` downloads a `.pdferaser` archive to the user's computer. It contains the original PDF, verified job metadata, and the current page artifacts and masks so the work can be reopened without an account. `작업 파일 열기` sends the archive only to the engine on `127.0.0.1`; the engine assigns a new random job ID and verifies archive paths, the source PDF hash, page count, and artifact dimensions before loading it. Because the original PDF is included, a project file must be protected like the original document.

Detected handwriting candidates are removed by default. The preserve brush restores exceptions and every completed stroke is applied automatically without a separate save action. The baseline protects PDF text glyphs, high-confidence OCR strokes, dark print-like connected components, and horizontal or vertical document lines. It never protects a full OCR rectangle. Install the relevant local Tesseract language data for scanned documents; without Korean language data, Korean scanned text remains review-biased and should not be auto-approved.
