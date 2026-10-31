# UI handoff — data integration change

The UI must now use the local API for district geography and values; it must
not construct its own district shapes, names, scores, or report replies.

Before running the UI, start the local data service from the repository root:

```powershell
uv run nycp init
uv run nycp data sync
uv run nycp serve
```

The existing static UI server runs on `http://127.0.0.1:4173`, which is
allowed by the local API CORS configuration. Use:

```text
http://127.0.0.1:8000/api/v1
```

for the API base.

## Current interface contract

- Fetch 59 official Community District geometries from `/geo/cd.geojson`.
  Each feature has `properties.geo_id` such as `cd:101`.
- Fetch district names, boroughs, and population from `/geographies?level=cd`.
- Fetch map values from
  `/scores?level=cd&node_type=indicator&node_id=public_parks.acreage_per_1000`.
  A non-`ok` status is unavailable, not zero.
- The current map data slice is only public-park acreage per 1,000 residents.
  Other priorities and the 10-minute walk-access indicator should be shown as
  unavailable until their local analysis is added.
- Report submission is available through `/uploads/presign`, the returned
  raw `PUT` upload URL, `/submissions`, then its `poll_url`. A report needs a
  browser-provided location. Do not put a Gemini key in browser code.
- Gemini interpretations are optional cached additions. Fetch
  `/geographies/{geo_id}/insight?node_type=indicator&node_id=public_parks.acreage_per_1000`.
  A `404` simply means no local interpretation has been generated.

The static UI in `NYC Civic Atlas Website/` has already been changed to follow
this contract.
