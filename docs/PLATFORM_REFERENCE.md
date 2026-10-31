# Platform debugging reference

This is the implementation map for the non-UI, local-first platform. The
normal entry point is `uv run nycp serve`, which exposes `api.py` on
`127.0.0.1:8000`. Do not bind it to a network interface.

## Execution paths

```text
CLI command → create_app / Database → SQLite or local files
HTTP request → api route → Database / contracts / scoring → JSON response
policy document → policy parser → GeminiService → verified SQLite commitment
citizen report → local upload → background worker → GeminiService → SQLite status
```

## Files and public components

| File | Component | Purpose | Connects to |
| --- | --- | --- | --- |
| `src/nyc_civic/cli.py` | `app` | Typer command group installed as `nycp`. | `create_app`, `Database`, `seed_demo`, policy commands. |
| `src/nyc_civic/cli.py` | `init`, `serve` | Initialize demo SQLite data; run only on loopback. | `Database.initialize`, `seed_demo`, `uvicorn`. |
| `src/nyc_civic/cli.py` | `contract export/check` | Generate or verify `contracts/openapi.json`. | `create_app().openapi()`. |
| `src/nyc_civic/cli.py` | `docs ingest/extract/list/approve/reject` | Local policy ingestion, Gemini extraction and review status. | `ingest_document`, `extract_document`, `GeminiService`, `Database.set_commitment_review_status`. |
| `src/nyc_civic/api.py` | `create_app(settings)` | Constructs all HTTP routes, CORS and HTTP errors. | `Database`, YAML contract loaders, `GeminiService`, `sanitize_image`. |
| `src/nyc_civic/api.py` | `get_scores`, `get_score_tree`, `get_citywide` | Read precomputed score rows for the UI. | `Database.list_scores/score/city_scores`, score schemas. |
| `src/nyc_civic/api.py` | `presign_upload`, `upload_local`, `create_submission`, `_submission_worker` | Local upload and Gemini classification flow. | `upload_path`, `sanitize_image`, `GeminiService.classify_submission`, `Database.update_submission`. |
| `src/nyc_civic/config.py` | `Settings`, `get_settings` | Reads `.env`, derives local storage paths and loopback CORS origins. | All runtime entry points. |
| `src/nyc_civic/db.py` | `Database` | Owns SQLite schema, connections and all persisted reads/writes. | `seed.py`, `api.py`, `policy.py`. |
| `src/nyc_civic/db.py` | `set_commitment_review_status` | Makes an extracted commitment visible or keeps it hidden. | `nycp docs approve/reject`, `/commitments`. |
| `src/nyc_civic/db.py` | `upload_path` | Rejects upload keys that escape `data/uploads`. | `api.upload_local`, `_submission_worker`. |
| `src/nyc_civic/contracts.py` | `taxonomy`, `indicator_specs`, `dataset_specs`, `methodology` | Loads YAML source-of-truth configuration. | `api.py`, `gemini.py`. |
| `src/nyc_civic/scoring.py` | `normalize_value`, `percentile_ranks` | Pure score normalization functions. | Future run pipeline code; covered by `test_scoring.py`. |
| `src/nyc_civic/scoring.py` | `aggregate_scores` | Coverage-aware weighted aggregation; unavailable data is never coerced to zero. | `seed_demo`; future indicator pipelines. |
| `src/nyc_civic/seed.py` | `seed_demo` | Creates three demo CDs, two Parks indicators, subcategory/domain and citywide scores. | `Database`, scoring functions. |
| `src/nyc_civic/gemini.py` | `GeminiService` | Gemini SDK boundary; creates schema-constrained calls. | `api._submission_worker`, `policy.extract_document`. |
| `src/nyc_civic/gemini.py` | `_validate_classification_taxonomy` | Rejects model tags outside the YAML taxonomy. | `GeminiService.classify_submission`, `contracts.taxonomy`. |
| `src/nyc_civic/policy.py` | `ingest_document`, `parse_document`, `split_chunks` | Copies a source, parses PDF/text and stores parser-owned page chunks. | `Database.create_policy_document`, `Database.replace_document_chunks`. |
| `src/nyc_civic/policy.py` | `extract_document` | Sends chunks to Gemini and saves only fuzzy-verified excerpts. | `GeminiService.extract_commitments`, `Database.add_commitment`, `rapidfuzz`. |
| `src/nyc_civic/media.py` | `sanitize_image` | Verifies image data, applies EXIF orientation, strips metadata, produces JPEG. | `_submission_worker`; Pillow. |
| `src/nyc_civic/schemas.py` | Pydantic request/response models | Defines API validation and generated OpenAPI components. | `api.py`, `gemini.py`, contract export. |

## Data and configuration

| Location | Owned data | Read by |
| --- | --- | --- |
| `contracts/taxonomy/*.yaml` | Domain, subcategory, dimension, observation enums. | `contracts.py`, `gemini.py`, `/taxonomy`. |
| `contracts/indicators/*.yaml` | Indicator definition, normalization and source datasets. | `contracts.py`, `/indicators/{id}`, demo scoring. |
| `contracts/datasets/*.yaml` | Dataset metadata and known limitations. | `/datasets`, indicator provenance. |
| `contracts/methodology.yaml` | Coverage and normalization policy. | `/methodology`; future run commands. |
| `data/nyc_civic.sqlite3` | Geographies, scores, submissions, documents, chunks and commitments. | `Database` only. |
| `data/uploads/` | Raw and cleaned local photos. | upload route and worker only. |
| `data/policy/` | Imported source-document copies. | `policy.ingest_document`. |

## Debugging by symptom

| Symptom | Inspect first | Likely connections |
| --- | --- | --- |
| API will not start | `.env`, `config.py`, then `Database.initialize` | Missing dependencies, invalid storage path, or port 8000 in use. |
| `/scores` has no values | `nycp demo seed`, `score_value` table | `seed_demo` supplies initial values; real pipelines will replace them. |
| UI map has no shapes | `data/geo/cd.geojson` | No geometry importer is implemented yet; empty GeoJSON is intentional initially. |
| Submission becomes `failed` | `.env` then `_submission_worker` | Missing Gemini key, unsupported/corrupt photo, Gemini response rejected by taxonomy validation. |
| Extracted commitment is missing | `policy.extract_document` | Excerpt did not meet fuzzy-verification threshold or numeric target was not literal in source. |
| Commitment endpoint is empty | `commitment.review_status` in SQLite | API intentionally returns only human-approved commitments. |

## Tests

- `tests/test_scoring.py` exercises pure normalization, inversion, coverage, and
  ranking behavior.
- `tests/test_api.py` starts the app against a temporary SQLite database and
  checks the score response shape and missing-data behavior.

Run all tests with `uv run pytest` once the setup in `README.md` is complete.
