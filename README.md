# NYC Civic Priorities Platform — local-first

This is the local non-UI platform for Mamdani Metre. It uses a loopback-only
FastAPI API, SQLite, local files, and the Gemini API. There is no Docker,
cloud database, hosted backend, GPU setup, or network-accessible service.

The first complete local data slice is public parks: the sync downloads the
official NYC Community District boundaries, NYC Parks Properties acreage, and
NYC Department of City Planning 2010 community-district population. It then
scores public park acreage per 1,000 residents for all 59 standard districts.

## What is included

- local SQLite persistence and file-backed image uploads;
- local synchronization of official NYC geography, Parks, and population data;
- YAML indicator specifications, provenance, limitations, and a generated
  OpenAPI contract;
- coverage-aware scoring: unavailable measures are never made into zeroes;
- Gemini classification of local citizen reports and Gemini district
  interpretations constrained to stored data and human-approved policy text;
- a static UI that fetches real map and score data from the local API.

Gemini is the only remote platform dependency. Its API key remains in `.env`
and is never sent to the browser.

## One-time setup (Windows PowerShell)

From this project folder:

```powershell
uv python install 3.13
uv sync --extra dev
Copy-Item .env.example .env
notepad .env
```

Add `GEMINI_API_KEY` in `.env` if you want report classification, policy
extraction, or district interpretations. The map and official data sync do not
need the key.

If `uv` is not installed:

```powershell
winget install --id astral-sh.uv -e
```

## Load and run the local platform

```powershell
uv run nycp init
uv run nycp data sync
uv run nycp contract export
uv run nycp serve
```

`nycp data sync` intentionally downloads the source releases and replaces the
local geography and score snapshot. It preserves policy documents and report
records, while it invalidates cached district interpretations because their
underlying data version changed.

The API listens only at `http://127.0.0.1:8000`. It is not safe to expose it
directly to a network or deploy it unchanged.

## Run the UI

With the API running, open another PowerShell window:

```powershell
Set-Location "C:\Projects\MamdaniMeter\NYC Civic Atlas Website"
node server.js
```

Then open <http://127.0.0.1:4173>. The UI uses the local API at
`http://127.0.0.1:8000/api/v1` by default.

## Policy documents and Gemini

Put original city policy documents under `policy_sources/`, then run:

```powershell
uv run nycp docs ingest .\policy_sources\your-policy.pdf
uv run nycp docs extract <document-id>
uv run nycp docs list
uv run nycp docs show <commitment-id>
uv run nycp docs approve <commitment-id>
```

Only commitments that a person has reviewed and approved become API-visible or
available as Gemini policy context. To prepare optional district explanations
for the map, run:

```powershell
uv run nycp insights generate
```

This makes one Gemini request per district (59 requests). See
[the local showcase guide](docs/SHOWCASE.md) and
[the debugging reference](docs/PLATFORM_REFERENCE.md) for the complete flow.

## Commands

```powershell
uv run nycp init
uv run nycp data sync
uv run nycp serve
uv run nycp contract export
uv run nycp contract check
uv run nycp fixtures export
uv run nycp insights generate
uv run pytest
```

## Local files

`data/nyc_civic.sqlite3` is the database, `data/geo/cd.geojson` is the local
community-district geometry snapshot, `data/uploads/` contains report images,
and `data/policy/` holds ingested source documents. They are ignored by Git.
Back up the SQLite file while the API is stopped.

## Current limitation

Public park acreage per 1,000 residents is source-labeled, but it is not a
measure of walking access, park quality, capacity, or current population. The
10-minute walking-access indicator is intentionally `unavailable` until a
documented local walking-network and population-allocation pipeline is added.
