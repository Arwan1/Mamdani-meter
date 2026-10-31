# Platform debugging reference

The platform is a loopback-only FastAPI process, SQLite database, and local
files. Start it with `uv run nycp serve`; it binds only to `127.0.0.1:8000`.

## Execution paths

```text
nycp data sync → official NYC Open Data → SQLite scores + data/geo/cd.geojson
HTTP request → api.py route → Database / contract YAML → JSON response
policy document → policy.py parser → GeminiService → reviewed SQLite commitment
citizen report → local upload → background worker → GeminiService → SQLite status
```

## Files and public components

| File | Component | Purpose | Connects to |
| --- | --- | --- | --- |
| `src/nyc_civic/cli.py` | `app`, `init`, `data sync`, `serve` | CLI entry points for an empty local store, official-data sync, and loopback API. | `Database`, `sync_parks_data`, `create_app`, `uvicorn`. |
| `src/nyc_civic/real_data.py` | `sync_parks_data` | Downloads official CD boundaries, DCP population, and Parks acreage; writes the 59-CD local snapshot. | `Database`, `scoring.py`, `data/geo/cd.geojson`. |
| `src/nyc_civic/real_data.py` | `_feature_collection`, `_population_by_cd`, `_park_acres_by_cd` | Validate and normalize source rows before any database write. | `sync_parks_data`. |
| `src/nyc_civic/scoring.py` | `normalize_value`, `aggregate_scores`, citywide functions | Pure normalization and coverage-aware aggregation. | `real_data.py`, tests. |
| `src/nyc_civic/db.py` | `Database` | SQLite schema, data-version updates, score/geography reads, uploads, and policy storage. | API, policy, insights, real-data sync. |
| `src/nyc_civic/api.py` | `create_app` | CORS and all local HTTP routes. | `Database`, contract YAML, Gemini and image helpers. |
| `src/nyc_civic/api.py` | `/geo/{level}.geojson`, `/geographies`, `/scores` | The current UI map data path. | `data/geo/cd.geojson`, `geography`, `score_value`. |
| `src/nyc_civic/insights.py` | `district_score_context`, `generate_district_insight` | Builds evidence strictly from stored values, then caches Gemini output by data version. | `Database`, `GeminiService`. |
| `src/nyc_civic/gemini.py` | `GeminiService` | Schema-constrained Gemini boundary for reports, policy extraction, and district interpretation. | API worker, policy extraction, insights. |
| `src/nyc_civic/policy.py` | `ingest_document`, `extract_document` | Parses policy sources and saves only source-verified proposed commitments. | `Database`, Gemini, RapidFuzz. |
| `src/nyc_civic/media.py` | `sanitize_image` | Verifies image data and removes metadata before Gemini receives it. | API submission worker. |
| `src/nyc_civic/schemas.py` | Pydantic models | API validation and generated OpenAPI components. | API and Gemini. |

## Data locations

| Location | Contents |
| --- | --- |
| `contracts/indicators/*.yaml` | Formula, normalization, source datasets, reference period, limitations. |
| `contracts/datasets/*.yaml` | Source provenance and known limitations. |
| `data/nyc_civic.sqlite3` | Geographies, scores, submissions, policy records, and insight cache. |
| `data/geo/cd.geojson` | Locally synced official community-district geometry. |
| `data/uploads/` | Local uploaded images and cleaned derivatives. |
| `data/policy/` | Immutable copies of ingested policy documents. |

## Debugging by symptom

| Symptom | Inspect first | Likely resolution |
| --- | --- | --- |
| Map has no shapes or values | `nycp data sync`, then `data/geo/cd.geojson` | Re-run the official-data sync with an internet connection. |
| UI cannot contact the API | `nycp serve`, port 8000, browser console | Start the loopback API before `node server.js`. |
| District map shows unavailable | `/scores` response status and indicator metadata | Do not render unavailable as zero; check its source limitation. |
| Insight endpoint returns 404 | `nycp insights generate`, current `data_version` | Cache was not generated, or the data sync invalidated the previous cache. |
| Report becomes `failed` | `.env`, API terminal output, submission worker | Check Gemini configuration or photo validity; the API withholds provider details. |
| Commitment is absent from API | `docs list`, `review_status` | Human-review and approve the source-faithful record. |

## Tests

`tests/test_scoring.py` covers scoring math. `tests/test_api.py` and
`tests/test_insights.py` use an isolated temporary SQLite database to validate
the response and cache contracts. Run all tests with `uv run pytest`.
