from __future__ import annotations

import json
from pathlib import Path

import typer
import uvicorn

from nyc_civic.api import create_app
from nyc_civic.config import PROJECT_ROOT, get_settings
from nyc_civic.db import Database
from nyc_civic.gemini import GeminiService
from nyc_civic.insights import generate_district_insight
from nyc_civic.policy import extract_document, ingest_document
from nyc_civic.real_data import sync_parks_data


app = typer.Typer(help="Local-first NYC Civic Priorities platform commands.", no_args_is_help=True)
contract_app = typer.Typer(help="OpenAPI contract commands.", no_args_is_help=True)
data_app = typer.Typer(help="Official-data synchronization commands.", no_args_is_help=True)
docs_app = typer.Typer(help="Policy document commands.", no_args_is_help=True)
fixtures_app = typer.Typer(help="UI fixture commands.", no_args_is_help=True)
insights_app = typer.Typer(help="Gemini district interpretation commands.", no_args_is_help=True)
app.add_typer(contract_app, name="contract")
app.add_typer(data_app, name="data")
app.add_typer(docs_app, name="docs")
app.add_typer(fixtures_app, name="fixtures")
app.add_typer(insights_app, name="insights")


def database() -> Database:
    return Database(get_settings())


@app.command()
def init() -> None:
    """Create local directories and the SQLite schema without inventing records."""
    store = database()
    store.initialize()
    typer.echo("Initialized empty local store. Run `nycp data sync` to load official NYC data.")


@app.command()
def serve(port: int = typer.Option(8000, min=1, max=65535)) -> None:
    """Run the API on loopback only; it is never bound to the local network."""
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="info")


@contract_app.command("export")
def export_contract(output: Path = typer.Option(PROJECT_ROOT / "contracts" / "openapi.json")) -> None:
    """Write the generated OpenAPI contract for the UI owner."""
    output.parent.mkdir(parents=True, exist_ok=True)
    schema = create_app().openapi()
    output.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    typer.echo(f"Wrote {output}")


@contract_app.command("check")
def check_contract(contract: Path = typer.Option(PROJECT_ROOT / "contracts" / "openapi.json")) -> None:
    """Fail when the committed contract differs from the Python API models."""
    expected = json.dumps(create_app().openapi(), indent=2) + "\n"
    actual = contract.read_text(encoding="utf-8") if contract.exists() else ""
    if actual != expected:
        typer.echo("OpenAPI is stale; run `nycp contract export`.", err=True)
        raise typer.Exit(code=1)
    typer.echo("OpenAPI contract is current.")


@data_app.command("sync")
def data_sync() -> None:
    """Fetch the official NYC Parks, DCP population, and CD-boundary sources locally."""
    typer.echo("Downloading official NYC Open Data records…")
    version = sync_parks_data(database(), get_settings())
    typer.echo(f"Loaded 59 community districts and current Parks acreage data ({version}).")


@docs_app.command("ingest")
def docs_ingest(source: Path) -> None:
    """Copy and parse a PDF, Markdown, or text policy source into local SQLite chunks."""
    document_id, chunks = ingest_document(database(), get_settings(), source)
    typer.echo(f"Ingested {chunks} chunks as document {document_id}")


@docs_app.command("extract")
def docs_extract(document_id: str) -> None:
    """Run Gemini structured extraction; all saved commitments require later human approval."""
    settings = get_settings()
    gemini = GeminiService(settings.gemini_api_key, settings.gemini_model_fast)
    saved, rejected = extract_document(database(), gemini, document_id)
    typer.echo(f"Saved {saved} review-pending commitments; rejected {rejected} unverifiable items.")


@docs_app.command("approve")
def docs_approve(commitment_id: str) -> None:
    """Approve a reviewed commitment so it can appear in the public API."""
    if not database().set_commitment_review_status(commitment_id, "approved"):
        raise typer.BadParameter("Unknown commitment id")
    typer.echo(f"Approved commitment {commitment_id}")


@docs_app.command("list")
def docs_list(approved_only: bool = typer.Option(False)) -> None:
    """Print commitment IDs and review states for the local human-review step."""
    rows = database().commitments(approved_only=approved_only)
    if not rows:
        typer.echo("No matching commitments.")
        return
    for row in rows:
        typer.echo(f"{row['id']}  [{row['review_status']}]  {row['summary']}")


@docs_app.command("show")
def docs_show(commitment_id: str) -> None:
    """Print a proposed commitment and its source excerpt for human review."""
    row = database().commitment(commitment_id, approved_only=False)
    if row is None:
        raise typer.BadParameter("Unknown commitment id")
    typer.echo(f"Document: {row['document_title']}")
    typer.echo(f"Page: {row['page'] or 'n/a'}")
    typer.echo(f"Status: {row['review_status']}")
    typer.echo(f"Summary: {row['summary']}")
    typer.echo(f"Excerpt: {row['excerpt']}")
    typer.echo(f"Tags: {row['tags_json']}")


@docs_app.command("reject")
def docs_reject(commitment_id: str) -> None:
    """Reject a reviewed commitment so it remains out of the public API."""
    if not database().set_commitment_review_status(commitment_id, "rejected"):
        raise typer.BadParameter("Unknown commitment id")
    typer.echo(f"Rejected commitment {commitment_id}")


@insights_app.command("generate")
def insights_generate(
    node_type: str = typer.Option("indicator"),
    node_id: str = typer.Option("public_parks.acreage_per_1000"),
    level: str = typer.Option("cd"),
) -> None:
    """Generate and cache one data-constrained Gemini interpretation per configured geography."""
    store = database()
    geographies = store.list_geographies(level)
    if not geographies:
        raise typer.BadParameter(f"No geographies are loaded at level '{level}'")
    for geography in geographies:
        insight = generate_district_insight(
            store, get_settings(), geography["geo_id"], node_type, node_id
        )
        typer.echo(f"{insight.geo_id}: {insight.headline}")


@fixtures_app.command("export")
def export_fixtures(output_dir: Path = typer.Option(PROJECT_ROOT / "contracts" / "fixtures")) -> None:
    """Export compact current API fixtures after an official-data synchronization."""
    from fastapi.testclient import TestClient

    output_dir.mkdir(parents=True, exist_ok=True)
    client = TestClient(create_app())
    paths = {
        "taxonomy.json": "/api/v1/taxonomy",
        "geographies-cd.json": "/api/v1/geographies?level=cd",
        "scores-public-parks.json": "/api/v1/scores?level=cd&node_type=subcategory&node_id=public_parks",
        "citywide-public-parks.json": "/api/v1/citywide?node_type=subcategory&node_id=public_parks",
        "methodology.json": "/api/v1/methodology",
    }
    for filename, path in paths.items():
        response = client.get(path)
        response.raise_for_status()
        (output_dir / filename).write_text(json.dumps(response.json(), indent=2) + "\n", encoding="utf-8")
    typer.echo(f"Wrote {len(paths)} fixtures to {output_dir}")


if __name__ == "__main__":
    app()
