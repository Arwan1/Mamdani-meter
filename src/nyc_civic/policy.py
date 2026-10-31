from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

import pymupdf
from rapidfuzz import fuzz

from nyc_civic.config import Settings
from nyc_civic.db import Database
from nyc_civic.gemini import GeminiService


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def split_chunks(text: str, page: int | None, max_chars: int = 8500) -> list[dict[str, str | int | None]]:
    """Use parser-owned page references and preserve source text for later verification."""
    cleaned = normalized_text(text)
    if not cleaned:
        return []
    chunks: list[dict[str, str | int | None]] = []
    for start in range(0, len(cleaned), max_chars):
        end = min(len(cleaned), start + max_chars)
        if end < len(cleaned):
            boundary = cleaned.rfind(". ", start, end)
            if boundary > start + max_chars // 2:
                end = boundary + 1
        chunks.append({"text": cleaned[start:end], "page": page, "section_ref": f"page {page}" if page else None})
        if end == len(cleaned):
            break
        start = end
    return chunks


def parse_document(path: Path) -> list[dict[str, str | int | None]]:
    if path.suffix.lower() == ".pdf":
        document = pymupdf.open(path)
        try:
            return [
                chunk
                for page_number, page in enumerate(document, start=1)
                for chunk in split_chunks(page.get_text("text"), page_number)
            ]
        finally:
            document.close()
    return split_chunks(path.read_text(encoding="utf-8"), None)


def ingest_document(database: Database, settings: Settings, source: Path) -> tuple[str, int]:
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(source)
    file_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    target = settings.policy_dir / f"{file_hash[:12]}-{source.name}"
    if not target.exists():
        settings.policy_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    document_id = database.create_policy_document(source.stem, str(target), file_hash)
    chunks = parse_document(target)
    database.replace_document_chunks(document_id, chunks)
    return document_id, len(chunks)


def extract_document(database: Database, gemini: GeminiService, document_id: str) -> tuple[int, int]:
    """Save only excerpts that can be verified directly against their source chunk."""
    chunks = database.document_chunks(document_id)
    if not chunks:
        raise ValueError(f"No chunks were found for document {document_id}")
    saved = 0
    rejected = 0
    for chunk in chunks:
        extracted = gemini.extract_commitments(chunk["text"])
        for item in extracted.commitments:
            match = fuzz.partial_ratio(normalized_text(item.excerpt), normalized_text(chunk["text"])) / 100
            if match < 0.97:
                rejected += 1
                continue
            target_as_text = format(item.target_value, ".15g") if item.target_value is not None else None
            if target_as_text is not None and target_as_text not in item.excerpt:
                rejected += 1
                continue
            identifier = database.add_commitment(
                {
                    "document_id": document_id,
                    "chunk_id": chunk["id"],
                    "statement_type": item.statement_type,
                    "summary": item.summary,
                    "excerpt": item.excerpt,
                    "section_ref": chunk["section_ref"],
                    "page": chunk["page"],
                    "agencies": item.agencies,
                    "target_value": item.target_value,
                    "target_unit": item.target_unit,
                    "deadline": item.deadline,
                    "tags": [value for value in [item.domain, item.subcategory, *item.dimensions] if value],
                }
            )
            saved += identifier is not None
    return saved, rejected
