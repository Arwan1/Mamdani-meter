# Mamdani Metre — NYC Civic Atlas UI

This interface reads its district boundaries, names, score values, and report
classification results from the local Civic Priorities API. It does not create
its own district shapes or values.

## Run locally

In one PowerShell window at the repository root:

```powershell
uv run nycp init
uv run nycp data sync
uv run nycp serve
```

In a second PowerShell window:

```powershell
Set-Location "C:\Projects\MamdaniMeter\NYC Civic Atlas Website"
node server.js
```

Open <http://127.0.0.1:4173>. The UI defaults to
`http://127.0.0.1:8000/api/v1`. To point it at a different local API, append
an encoded `api` query parameter, for example:

```text
http://127.0.0.1:4173/?api=http%3A%2F%2F127.0.0.1%3A8001%2Fapi%2Fv1
```

The satellite map tiles, Leaflet library, and web fonts use the internet. The
platform data and uploaded report photos stay on the laptop.

## Current data scope

- 59 official NYC community-district boundaries.
- Current NYC Parks Properties acreage, joined by community-board code.
- NYC Department of City Planning 2010 community-district population.
- A benchmark score for public park acreage per 1,000 residents.

Park acreage is not an access, quality, capacity, or current-population
measure. The 10-minute walking-access indicator is intentionally unavailable
until its separate local routing analysis exists.

## Reports

Reports require a browser-provided location. The interface uploads an optional
photo into local storage and polls the local API for Gemini classification.
Gemini may link a report only to human-reviewed local policy records; no report
is sent to NYC government.
