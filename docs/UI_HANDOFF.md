# UI handoff — action required

Use this while developing against the local platform:

The static website uses `http://127.0.0.1:8000/api/v1` by default. To point it
to another local API, edit `NYC Civic Atlas Website/api-config.js`. The local
API allows the website's `127.0.0.1:4173` and `localhost:4173` origins by
default.

The API runs only after the platform developer starts `uv run nycp serve`.
Use the existing `/api/v1` endpoint paths and `snake_case` response keys.

Two current integration limits affect UI behavior:

1. The initial Parks demo has only three sample community districts, and
   `/geo/cd.geojson` is empty until real boundaries are imported. Support an
   empty map-data state; do not treat it as a request failure. Until then the
   satellite map remains available and the district list uses API records.
2. Photo uploads are local in development. Call `/uploads/presign`, then
   `PUT` the raw image file directly to the returned `upload_url` (not
   `FormData`).

No Gemini key belongs in the UI environment. If Gemini has not been configured
locally, the submission poll endpoint can return `status: "failed"`; render
that status normally.
