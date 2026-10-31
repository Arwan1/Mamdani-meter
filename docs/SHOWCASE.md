# Local data showcase

This workflow shows the live local slice: 59 official NYC community districts,
NYC Parks property acreage, and Department of City Planning 2010 population.
All records are stored in the ignored local `data/` directory after retrieval.

## Start the data service

From `C:\Projects\MamdaniMeter`:

```powershell
uv run nycp init
uv run nycp data sync
uv run nycp contract export
uv run nycp serve
```

In another PowerShell window, start the UI:

```powershell
Set-Location "C:\Projects\MamdaniMeter\NYC Civic Atlas Website"
node server.js
```

Open <http://127.0.0.1:4173>. The map reads `/geo/cd.geojson`,
`/geographies`, and `/scores` from the local API.

## Add policy context for Gemini

Place original official documents under `policy_sources/`, then run:

```powershell
uv run nycp docs ingest .\policy_sources\city-plan.pdf
uv run nycp docs extract <document-id>
uv run nycp docs list
uv run nycp docs show <commitment-id>
uv run nycp docs approve <commitment-id>
```

Generate cached, data-constrained interpretations only when you are ready for
one Gemini call per district (59 calls):

```powershell
uv run nycp insights generate
```

The UI remains useful without interpretations. They can be inspected directly:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/geographies/cd:101/insight?node_type=indicator&node_id=public_parks.acreage_per_1000" |
  ConvertTo-Json -Depth 8
```

## Current limitation

Park acreage per 1,000 residents is a real, source-labeled measure. It does
not establish walking access, park condition, capacity, or current population.
The walking-access indicator is explicitly unavailable until a local routing
analysis is introduced; it is never filled with a fabricated value.
