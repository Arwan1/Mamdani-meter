from __future__ import annotations

import pytest

from nyc_civic.gemini import GeminiService
from nyc_civic.schemas import SubmissionClassification


def test_policy_links_are_limited_to_the_approved_context() -> None:
    classification = SubmissionClassification(
        is_urban_issue=True,
        domain="public_amenities_spaces",
        subcategory="public_parks",
        related_policy_ids=["commitment-1"],
    )
    GeminiService._validate_classification_taxonomy(
        classification, allowed_policy_ids={"commitment-1"}
    )


def test_unknown_policy_link_is_rejected() -> None:
    classification = SubmissionClassification(is_urban_issue=True, related_policy_ids=["invented"])
    with pytest.raises(ValueError, match="approved local policy corpus"):
        GeminiService._validate_classification_taxonomy(classification, allowed_policy_ids=set())
