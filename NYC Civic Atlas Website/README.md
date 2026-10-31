# Mamdani Metre — NYC Civic Atlas

The locally hosted website reads priorities, district records, scores, district
context, and report classifications from the companion FastAPI backend in the
parent project. The browser contains no generated district scores or shapes.

## Start the app on Windows

Use two PowerShell windows, both opened in the project folder.

**Window 1 — backend**, from `HaverHack 2`:

```powershell
uv run nycp demo seed
uv run nycp serve
```

Seed the demo data once, or again when you intentionally want to reset the
demo results. The API listens at `http://127.0.0.1:8000`.

**Window 2 — website**, from `HaverHack 2\NYC Civic Atlas Website`:

```powershell
node server.js
```

Open <http://127.0.0.1:4173>. Leave both windows running while using the site.
Refresh the page after starting the API. Directly opening `index.html` does not
work for API calls because the browser needs the local website server origin.

## Connected features

- Priorities and measures come from `/api/v1/taxonomy`.
- District records come from `/api/v1/geographies?level=cd` and scores from
  `/api/v1/scores`.
- Community-district shapes come from `/api/v1/geo/cd.geojson`. The backend
  currently returns an empty shape collection until NYC boundaries are
  imported, so the satellite map stays visible and the list shows the real
  district records in the API.
- Selecting a district loads its score tree, context, and infrastructure.
- User reports require an NYC location. Photos are uploaded using the local
  presign-and-PUT flow, then submissions are polled for classification.
- Reports, uploaded images, and the database remain in the backend's local
  `data/` folder. Reports are not sent to the City. If Gemini is not configured,
  the backend may return a normal `failed` classification status.

The UI's default API address is in `api-config.js`. The backend CORS defaults
include the website's `127.0.0.1:4173` and `localhost:4173` origins.

Satellite imagery uses Esri World Imagery tiles via Leaflet and requires an
internet connection. Red means more problems or less access, yellow shows the
middle of the score range, blue means better conditions or more access, and
gray means evidence is unavailable.
