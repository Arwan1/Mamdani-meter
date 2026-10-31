from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from nyc_civic.config import PROJECT_ROOT


CONTRACTS_DIR = PROJECT_ROOT / "contracts"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        value = yaml.safe_load(source)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return value


def taxonomy() -> dict[str, Any]:
    result = load_yaml(CONTRACTS_DIR / "taxonomy" / "domains.yaml")
    result.update(load_yaml(CONTRACTS_DIR / "taxonomy" / "dimensions.yaml"))
    result.update(load_yaml(CONTRACTS_DIR / "taxonomy" / "observation_types.yaml"))
    indicators_by_subcategory: dict[str, list[dict[str, Any]]] = {}
    for spec in indicator_specs().values():
        indicators_by_subcategory.setdefault(spec["subcategory"], []).append(spec)
    for domain in result["domains"]:
        for subcategory in domain.get("subcategories", []):
            subcategory["indicators"] = indicators_by_subcategory.get(subcategory["slug"], [])
    return result


def indicator_specs() -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for path in sorted((CONTRACTS_DIR / "indicators").glob("*.yaml")):
        spec = load_yaml(path)
        indicator_id = spec.get("id")
        if not isinstance(indicator_id, str):
            raise ValueError(f"{path} has no valid indicator id")
        specs[indicator_id] = spec
    return specs


def dataset_specs() -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for path in sorted((CONTRACTS_DIR / "datasets").glob("*.yaml")):
        spec = load_yaml(path)
        slug = spec.get("slug")
        if not isinstance(slug, str):
            raise ValueError(f"{path} has no valid dataset slug")
        specs[slug] = spec
    return specs


def methodology() -> dict[str, Any]:
    return load_yaml(CONTRACTS_DIR / "methodology.yaml")


def find_domain_for_subcategory(subcategory: str) -> dict[str, Any] | None:
    for domain in taxonomy()["domains"]:
        if any(item["slug"] == subcategory for item in domain.get("subcategories", [])):
            return domain
    return None
