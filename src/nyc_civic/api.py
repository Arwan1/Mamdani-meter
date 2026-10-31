from __future__ import annotations

import json
import mimetypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from nyc_civic.config import Settings, get_settings
from nyc_civic.contracts import dataset_specs, indicator_specs, methodology, taxonomy
from nyc_civic.db import Database, json_load, upload_path
from nyc_civic.gemini import GeminiService
from nyc_civic.media import sanitize_image
from nyc_civic.schemas import (
    CitywideResponse,
    CitywideValue,
    Commitment,
    CommitmentList,
    Dataset,
    DatasetList,
    DistrictInsight,
    Geography,
    GeographyList,
    IndicatorDetails,
    Legend,
    MeasureGroupsResponse,
    ReportsSummary,
    ScoreNode,
    ScoreStatus,
    ScoreTreeNode,
    ScoreTreeResponse,
    ScoreValue,
    ScoresResponse,
    SubmissionClassification,
    SubmissionCreate,
    SubmissionResponse,
    UploadPresignRequest,
    UploadPresignResponse,
)


def _node_name(node_type: str, node_id: str) -> str:
    if node_type == "indicator":
        spec = indicator_specs().get(node_id)
        if spec:
            return str(spec["name"])
    content = taxonomy()
    if node_type == "domain":
        for domain in content["domains"]:
            if domain["slug"] == node_id:
                return str(domain["name"])
    if node_type == "subcategory":
        for domain in content["domains"]:
            for subcategory in domain.get("subcategories", []):
                if subcategory["slug"] == node_id:
                    return str(subcategory["name"])
    if node_type == "dimension":
        for dimension in content["dimensions"]:
            if dimension["slug"] == node_id:
                return str(dimension["name"])
    return node_id.replace("_", " ").title()


def _versioned(response: Response, database: Database) -> str:
    version = database.current_data_version()
    response.headers["X-Data-Version"] = version
    return version


def _score_value(row: dict[str, Any] | None, geo_id: str) -> ScoreValue:
    if row is None:
        return ScoreValue(
            geo_id=geo_id,
            score=None,
            coverage=0,
            status=ScoreStatus.UNAVAILABLE,
            reason="No locally computed value is available yet.",
        )
    return ScoreValue(
        geo_id=geo_id,
        score=row["score"],
        coverage=row["coverage"],
        status=row["status"],
        raw_value=row["raw_value"],
        unit=row["unit"],
        reason=row["reason"],
        reference_period=row["reference_period"],
    )


def _commitment(row: dict[str, Any]) -> Commitment:
    return Commitment(
        id=row["id"],
        document_id=row["document_id"],
        document_title=row["document_title"],
        statement_type=row["statement_type"],
        summary=row["summary"],
        excerpt=row["excerpt"],
        section_ref=row["section_ref"],
        page=row["page"],
        agencies=json_load(row["agencies_json"]),
        target_value=row["target_value"],
        target_unit=row["target_unit"],
        deadline=row["deadline"],
        review_status=row["review_status"],
        tags=json_load(row["tags_json"]),
    )


def _submission_response(row: dict[str, Any], api_prefix: str = "/api/v1") -> SubmissionResponse:
    classification = (
        SubmissionClassification.model_validate(json_load(row["classification_json"]))
        if row["classification_json"]
        else None
    )
    return SubmissionResponse(
        id=row["id"],
        status=row["status"],
        poll_url=f"{api_prefix}/submissions/{row['id']}",
        error=row["error"],
        classification=classification,
    )


def _taxonomy_indicator_ids(domain_id: str) -> list[str]:
    for domain in taxonomy()["domains"]:
        if domain["slug"] == domain_id:
            return [
                indicator["id"]
                for subcategory in domain.get("subcategories", [])
                for indicator in subcategory.get("indicators", [])
            ]
    return []


def _submission_worker(database: Database, settings: Settings, submission_id: str) -> None:
    row = database.submission(submission_id)
    if row is None:
        return
    try:
        keys: list[str] = json_load(row["photo_keys_json"])
        cleaned_image: Path | None = None
        if keys:
            original = upload_path(settings, keys[0])
            if not original.exists():
                raise ValueError("The uploaded image cannot be found in local storage")
            cleaned_image = sanitize_image(original)
        approved_commitments = database.commitments()
        policy_context = [
            {
                "id": item["id"],
                "document_title": item["document_title"],
                "page": str(item["page"] or "n/a"),
                "tags": ", ".join(json_load(item["tags_json"])),
                "summary": item["summary"],
                "excerpt": item["excerpt"],
            }
            for item in approved_commitments
        ]
        gemini = GeminiService(settings.gemini_api_key, settings.gemini_model_fast)
        classification = gemini.classify_submission(
            row["description"], cleaned_image, policy_context=policy_context
        )
        # The deterministic template avoids Gemini making a claim of illegality or violation.
        policy_note = None
        commitments_by_id = {item["id"]: item for item in approved_commitments}
        selected = [
            commitments_by_id[identifier]
            for identifier in classification.related_policy_ids
            if identifier in commitments_by_id
        ]
        if selected:
            candidate = selected[0]
            policy_note = (
                f"This observation may relate to the city's commitment to {candidate['summary']} "
                f"({candidate['document_title']}, page {candidate['page']}). "
                "It does not by itself establish a violation."
            )
        result = classification.model_copy(update={"policy_note": policy_note})
        database.update_submission(
            submission_id, status="classified", classification=result.model_dump(mode="json")
        )
    except Exception:  # provider details are deliberately not exposed to API clients
        database.update_submission(
            submission_id,
            status="failed",
            error="Classification could not be completed. Check local Gemini configuration or retry.",
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    database = Database(settings)
    database.initialize()
    app = FastAPI(
        title="NYC Civic Priorities Local Platform",
        version="0.1.0",
        description="Local-only companion API for the NYC Civic Priorities UI.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type", "X-Requested-With"],
    )

    @app.exception_handler(HTTPException)
    async def problem_response(_: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request could not be completed."
        return JSONResponse(
            status_code=exc.status_code,
            content={"type": "about:blank", "title": detail, "status": exc.status_code, "detail": detail},
            media_type="application/problem+json",
        )

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok", "mode": "local"}

    @app.get("/api/v1/taxonomy", tags=["platform"])
    def get_taxonomy(response: Response) -> dict[str, Any]:
        _versioned(response, database)
        return taxonomy()

    @app.get("/api/v1/geographies", response_model=GeographyList, tags=["platform"])
    def get_geographies(level: str, response: Response) -> GeographyList:
        version = _versioned(response, database)
        items = [
            Geography(**{**row, "is_residential": bool(row["is_residential"])})
            for row in database.list_geographies(level)
        ]
        return GeographyList(data_version=version, items=items)

    @app.get("/api/v1/geo/{level}.geojson", tags=["platform"])
    def get_geometry(level: str, response: Response) -> dict[str, Any]:
        _versioned(response, database)
        path = settings.storage_dir / "geo" / f"{level}.geojson"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return {"type": "FeatureCollection", "features": []}

    @app.get("/api/v1/scores", response_model=ScoresResponse, tags=["scores"])
    def get_scores(level: str, node_type: str, node_id: str, response: Response) -> ScoresResponse:
        if node_type not in {"domain", "subcategory", "dimension", "indicator"}:
            raise HTTPException(status_code=422, detail="Unknown node_type")
        version = _versioned(response, database)
        geography_rows = database.list_geographies(level)
        scores = {row["geo_id"]: row for row in database.list_scores(node_type, node_id, level)}
        indicator = indicator_specs().get(node_id) if node_type == "indicator" else None
        is_relative = bool(indicator and indicator["normalization"].get("is_relative", False))
        return ScoresResponse(
            node=ScoreNode(node_type=node_type, node_id=node_id, name=_node_name(node_type, node_id)),
            level=level,
            legend=Legend(is_relative=is_relative),
            data_version=version,
            values=[_score_value(scores.get(row["geo_id"]), row["geo_id"]) for row in geography_rows],
        )

    @app.get("/api/v1/geographies/{geo_id}/score-tree", response_model=ScoreTreeResponse, tags=["scores"])
    def get_score_tree(geo_id: str, response: Response, domain: str = "public_amenities_spaces") -> ScoreTreeResponse:
        if database.geography(geo_id) is None:
            raise HTTPException(status_code=404, detail="Geography not found")
        indicator_ids = _taxonomy_indicator_ids(domain)
        children: list[ScoreTreeNode] = []
        for indicator_id in indicator_ids:
            spec = indicator_specs()[indicator_id]
            row = database.score("indicator", indicator_id, geo_id)
            value = _score_value(row, geo_id)
            children.append(
                ScoreTreeNode(
                    node_type="indicator", node_id=indicator_id, name=spec["name"], score=value.score,
                    coverage=value.coverage, status=value.status, raw_value=value.raw_value, unit=value.unit,
                    reference_period=spec.get("reference_period"),
                    is_relative=bool(spec["normalization"].get("is_relative", False)),
                )
            )
        root_row = database.score("domain", domain, geo_id)
        root_value = _score_value(root_row, geo_id)
        return ScoreTreeResponse(
            data_version=_versioned(response, database),
            geo_id=geo_id,
            root=ScoreTreeNode(
                node_type="domain", node_id=domain, name=_node_name("domain", domain),
                score=root_value.score, coverage=root_value.coverage, status=root_value.status,
                children=children,
            ),
        )

    @app.get("/api/v1/geographies/{geo_id}/insight", response_model=DistrictInsight, tags=["insights"])
    def get_district_insight(
        geo_id: str,
        response: Response,
        node_type: str = "subcategory",
        node_id: str = "public_parks",
    ) -> DistrictInsight:
        if database.geography(geo_id) is None:
            raise HTTPException(status_code=404, detail="Geography not found")
        version = _versioned(response, database)
        stored = database.district_insight(geo_id, node_type, node_id, version)
        if stored is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "No precomputed district interpretation is available. "
                    "Run `nycp insights generate` after configuring Gemini."
                ),
            )
        return DistrictInsight.model_validate(json_load(stored["payload_json"]))

    def measures(geo_id: str, field: str, response: Response) -> MeasureGroupsResponse:
        geography = database.geography(geo_id)
        if geography is None:
            raise HTTPException(status_code=404, detail="Geography not found")
        label = "Demographics" if field == "context_json" else "Infrastructure"
        return MeasureGroupsResponse(
            data_version=_versioned(response, database),
            geo_id=geo_id,
            groups=[{"key": label.lower(), "label": label, "measures": json_load(geography[field])}],
        )

    @app.get("/api/v1/geographies/{geo_id}/context", response_model=MeasureGroupsResponse, tags=["platform"])
    def get_context(geo_id: str, response: Response) -> MeasureGroupsResponse:
        return measures(geo_id, "context_json", response)

    @app.get("/api/v1/geographies/{geo_id}/infrastructure", response_model=MeasureGroupsResponse, tags=["platform"])
    def get_infrastructure(geo_id: str, response: Response) -> MeasureGroupsResponse:
        return measures(geo_id, "infrastructure_json", response)

    @app.get("/api/v1/compare", tags=["scores"])
    def compare(geo_ids: str, response: Response, domain: str = "public_amenities_spaces") -> dict[str, Any]:
        requested_ids = [item for item in geo_ids.split(",") if item]
        if len(requested_ids) < 2:
            raise HTTPException(status_code=422, detail="At least two geo_ids are required")
        _versioned(response, database)
        return {
            "data_version": database.current_data_version(),
            "domain": domain,
            "items": [
                {"geography": database.geography(identifier), "score": database.score("domain", domain, identifier)}
                for identifier in requested_ids
                if database.geography(identifier) is not None
            ],
        }

    @app.get("/api/v1/citywide", response_model=CitywideResponse, tags=["scores"])
    def get_citywide(node_type: str, node_id: str, response: Response) -> CitywideResponse:
        rows = database.city_scores(node_type, node_id)
        return CitywideResponse(
            node=ScoreNode(node_type=node_type, node_id=node_id, name=_node_name(node_type, node_id)),
            data_version=_versioned(response, database),
            values=[
                CitywideValue(
                    agg_method=row["unit"], score=row["score"], coverage=row["coverage"], status=row["status"]
                )
                for row in rows
            ],
        )

    @app.get("/api/v1/indicators/{indicator_id}", response_model=IndicatorDetails, tags=["platform"])
    def get_indicator(indicator_id: str, response: Response) -> IndicatorDetails:
        spec = indicator_specs().get(indicator_id)
        if spec is None:
            raise HTTPException(status_code=404, detail="Indicator not found")
        _versioned(response, database)
        datasets = [Dataset(**dataset_specs()[slug]) for slug in spec.get("datasets", []) if slug in dataset_specs()]
        commitments = [
            _commitment(item) for item in database.commitments()
            if indicator_id in json_load(item["tags_json"])
        ]
        return IndicatorDetails(
            id=indicator_id, name=spec["name"], definition=spec["name"], formula=spec["formula"],
            direction=spec["direction"], unit=spec["unit"], normalization=spec["normalization"],
            datasets=datasets, reference_period=spec.get("reference_period"), limitations=spec["limitations"],
            commitments=commitments, run_id=f"local-{database.current_data_version()}",
        )

    @app.get("/api/v1/commitments", response_model=CommitmentList, tags=["policy"])
    def get_commitments(response: Response) -> CommitmentList:
        return CommitmentList(
            data_version=_versioned(response, database),
            items=[_commitment(row) for row in database.commitments()],
        )

    @app.get("/api/v1/commitments/{commitment_id}", response_model=Commitment, tags=["policy"])
    def get_commitment(commitment_id: str, response: Response) -> Commitment:
        row = database.commitment(commitment_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Commitment not found")
        _versioned(response, database)
        return _commitment(row)

    @app.get("/api/v1/datasets", response_model=DatasetList, tags=["platform"])
    def get_datasets(response: Response) -> DatasetList:
        return DatasetList(
            data_version=_versioned(response, database),
            items=[Dataset(**item) for item in dataset_specs().values()],
        )

    @app.get("/api/v1/datasets/{slug}", response_model=Dataset, tags=["platform"])
    def get_dataset(slug: str, response: Response) -> Dataset:
        spec = dataset_specs().get(slug)
        if spec is None:
            raise HTTPException(status_code=404, detail="Dataset not found")
        _versioned(response, database)
        return Dataset(**spec)

    @app.get("/api/v1/methodology", tags=["platform"])
    def get_methodology(response: Response) -> dict[str, Any]:
        result = methodology()
        result["data_version"] = _versioned(response, database)
        return result

    @app.post("/api/v1/uploads/presign", response_model=UploadPresignResponse, tags=["submissions"])
    def presign_upload(payload: UploadPresignRequest, request: Request) -> UploadPresignResponse:
        if payload.size_bytes > settings.max_upload_bytes:
            raise HTTPException(status_code=413, detail="Image exceeds the 10 MB local upload limit")
        extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}[payload.content_type]
        key = f"uploads/{datetime.now(UTC):%Y/%m/%d}/{uuid4().hex}{extension}"
        return UploadPresignResponse(key=key, upload_url=str(request.base_url) + f"api/v1/uploads/local/{key}")

    @app.put("/api/v1/uploads/local/{key:path}", status_code=status.HTTP_204_NO_CONTENT, tags=["submissions"])
    async def upload_local(key: str, request: Request) -> Response:
        if not key.startswith("uploads/"):
            raise HTTPException(status_code=404, detail="Unknown local upload path")
        content_type = request.headers.get("content-type") or mimetypes.guess_type(key)[0]
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise HTTPException(status_code=415, detail="Only JPEG, PNG, and WebP images are accepted locally")
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > settings.max_upload_bytes:
                raise HTTPException(status_code=413, detail="Image exceeds the 10 MB local upload limit")
        path = upload_path(settings, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(content))
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/api/v1/submissions", response_model=SubmissionResponse, status_code=status.HTTP_202_ACCEPTED, tags=["submissions"])
    def create_submission(payload: SubmissionCreate, background_tasks: BackgroundTasks) -> SubmissionResponse:
        observed_at = payload.observed_at
        if observed_at.tzinfo is None:
            raise HTTPException(status_code=422, detail="observed_at must include a UTC offset")
        if observed_at.astimezone(UTC) > datetime.now(UTC):
            raise HTTPException(status_code=422, detail="observed_at cannot be in the future")
        identifier = database.create_submission(payload.model_dump(mode="json"))
        background_tasks.add_task(_submission_worker, database, settings, identifier)
        row = database.submission(identifier)
        assert row is not None
        return _submission_response(row)

    @app.get("/api/v1/submissions/{submission_id}", response_model=SubmissionResponse, tags=["submissions"])
    def get_submission(submission_id: str) -> SubmissionResponse:
        row = database.submission(submission_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Submission not found")
        return _submission_response(row)

    @app.get("/api/v1/submissions", tags=["submissions"])
    def list_submissions(response: Response, bbox: str | None = None, category: str | None = None, validation_level: str | None = None) -> dict[str, Any]:
        # Public visibility remains false until a later local review workflow is deliberately added.
        _versioned(response, database)
        features = []
        for item in database.visible_submissions():
            classification = json_load(item["classification_json"]) if item["classification_json"] else None
            if category and (not classification or classification.get("domain") != category):
                continue
            features.append(
                {
                    "type": "Feature", "id": item["id"],
                    "geometry": {"type": "Point", "coordinates": [item["lng"], item["lat"]]},
                    "properties": {"validation_level": "ai_classified", "classification": classification},
                }
            )
        return {"type": "FeatureCollection", "features": features}

    @app.get("/api/v1/submissions/clusters", tags=["submissions"])
    def submission_clusters(response: Response, bbox: str | None = None) -> dict[str, Any]:
        _versioned(response, database)
        return {"type": "FeatureCollection", "features": []}

    @app.get("/api/v1/geographies/{geo_id}/reports-summary", response_model=ReportsSummary, tags=["submissions"])
    def reports_summary(geo_id: str) -> ReportsSummary:
        geography = database.geography(geo_id)
        if geography is None:
            raise HTTPException(status_code=404, detail="Geography not found")
        return ReportsSummary(geo_id=geo_id, count=0, per_10000_residents=0 if geography["population"] else None)

    return app
