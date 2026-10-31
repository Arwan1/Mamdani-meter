# Local policy source documents

Place downloaded **official** policy PDFs, HTML exports, Markdown, or text files
in this folder before ingesting them. The files themselves are intentionally
ignored by Git; `nycp docs ingest` copies each source into the local ignored
`data/policy/` archive and records its content hash.

For a Parks demonstration, start with the official [NYC Parks Five-Year
Accessibility Plan](https://static.nycgovparks.org/images/pagefiles/199/NYC-Parks-Five-Year-Plan-07-08-2024__668da17fce5ac.pdf),
then add the official [PlaNYC: Getting Sustainability Done full
report](https://www.nyc.gov/assets/climate/downloads/pdfs/PlaNYC-2023-Full-Report.pdf).
They contain parks/accessibility and citywide equity or public-space policy
context. Keep the original filename and source URL in your own notes so a
reviewer can verify the source.

Run, from the project root:

```powershell
.\.venv\Scripts\nycp.exe docs ingest .\policy_sources\your-policy.pdf
```
