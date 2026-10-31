from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from nyc_civic.config import Settings
from nyc_civic.contracts import indicator_specs, taxonomy
from nyc_civic.db import Database, json_load
from nyc_civic.gemini import GeminiService
from nyc_civic.schemas import DistrictEvidence, DistrictInsight


DATA_CAVEAT = (
    "This is a Gemini-written interpretation of the locally loaded source data and its stated "
    "reference periods. It is not a finding, causal explanation, or determination about city performance."
)


def indicator_ids_for_node(node_type: str, node_id: str) -> list[str]:
    specs = indicator_specs()
    if node_type == "indicator":
        return [node_id] if node_id in specs else []
    if node_type == "subcategory":
        return [identifier for identifier, spec in specs.items() if spec["subcategory"] == node_id]
    if node_type == "dimension":
        return [identifier for identifier, spec in specs.items() if node_id in spec.get("dimensions", [])]
    if node_type == "domain":
        subcategories = {
            subcategory["slug"]
            for domain in taxonomy()["domains"]
            if domain["slug"] == node_id
            for subcategory in domain.get("subcategories", [])
        }
        return [identifier for identifier, spec in specs.items() if spec["subcategory"] in subcategories]
    return []


def _policy_context(commitments: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "id": item["id"],
            "document_title": item["document_title"],
            "page": str(item["page"] or "n/a"),
            "tags": ", ".join(json_load(item["tags_json"])),
            "summary": item["summary"],
            "excerpt": item["excerpt"],
        }
        for item in commitments
    ]


def district_score_context(
    database: Database, geo_id: str, node_type: str, node_id: str
) -> tuple[dict[str, Any], list[DistrictEvidence]]:
    geography = database.geography(geo_id)
    if geography is None:
        raise ValueError("Geography not found")
    parent = database.score(node_type, node_id, geo_id)
    if parent is None:
        raise ValueError("No score data exists for the requested node and geography")
    evidence: list[DistrictEvidence] = []
    for indicator_id in indicator_ids_for_node(node_type, node_id):
        row = database.score("indicator", indicator_id, geo_id)
        spec = indicator_specs()[indicator_id]
        if row is None:
            continue
        evidence.append(
            DistrictEvidence(
                indicator_id=indicator_id,
                name=spec["name"],
                score=row["score"],
                raw_value=row["raw_value"],
                unit=row["unit"],
                status=row["status"],
                coverage=row["coverage"],
            )
        )
    version = database.current_data_version()
    context = {
        "geo_id": geo_id,
        "district_name": geography["name"],
        "borough": geography["borough"],
        "selected_node": {"node_type": node_type, "node_id": node_id},
        "selected_score": parent["score"],
        "selected_status": parent["status"],
        "selected_coverage": parent["coverage"],
        "data_version": version,
        "evidence": [item.model_dump(mode="json") for item in evidence],
    }
    return context, evidence


def generate_district_insight(
    database: Database,
    settings: Settings,
    geo_id: str,
    node_type: str,
    node_id: str,
) -> DistrictInsight:
    context, evidence = district_score_context(database, geo_id, node_type, node_id)
    gemini = GeminiService(settings.gemini_api_key, settings.gemini_model_fast)
    draft = gemini.explain_district(context, _policy_context(database.commitments()))
    insight = DistrictInsight(
        geo_id=geo_id,
        node_type=node_type,
        node_id=node_id,
        data_version=context["data_version"],
        headline=draft.headline,
        explanation=draft.explanation,
        priority_indicator_ids=draft.priority_indicator_ids,
        related_policy_ids=draft.related_policy_ids,
        evidence=evidence,
        caveat=DATA_CAVEAT,
        generated_at=datetime.now(UTC),
    )
    database.save_district_insight(
        geo_id=geo_id,
        node_type=node_type,
        node_id=node_id,
        data_version=insight.data_version,
        model_id=settings.gemini_model_fast,
        payload=insight.model_dump(mode="json"),
    )
    return insight
