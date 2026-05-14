"""Load page records from extract_pdf_for_rag JSONL (no OpenAI dependency)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_page_records(jsonl_path: str | Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))
    if records and "document_metadata" in records[0]:
        records = records[1:]
    return records
