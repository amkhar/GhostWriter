"""Granola transcript provider — fetches meeting transcripts from the Granola API."""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

import requests

logger = logging.getLogger("ghostwriter.granola")

GRANOLA_API_BASE = "https://api.granola.ai/v1"


class GranolaClient:
    """Minimal client for fetching transcripts from Granola."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("GRANOLA_API_KEY", "")
        if not self.api_key:
            raise ValueError("GRANOLA_API_KEY is required")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        })

    def list_documents(self, limit: int = 20) -> list[dict]:
        """List recent meeting documents from Granola."""
        resp = self.session.get(f"{GRANOLA_API_BASE}/documents", params={"limit": limit})
        resp.raise_for_status()
        return resp.json().get("documents", [])

    def get_transcript(self, document_id: str) -> str:
        """Fetch the transcript text for a given document."""
        resp = self.session.get(f"{GRANOLA_API_BASE}/documents/{document_id}/transcript")
        resp.raise_for_status()
        data = resp.json()
        return data.get("transcript", "")


def fetch_granola_transcripts(output_dir: Path, limit: int = 20) -> Path:
    """Fetch recent Granola transcripts and write them to output_dir.

    Returns the output directory path (for use as --transcripts).
    """
    client = GranolaClient()
    output_dir.mkdir(parents=True, exist_ok=True)

    documents = client.list_documents(limit=limit)
    if not documents:
        logger.warning("[GhostWriter][granola] No documents found in Granola")
        return output_dir

    for doc in documents:
        doc_id = doc.get("id", "unknown")
        title = doc.get("title", "meeting").replace(" ", "_").replace("/", "_")
        created = doc.get("created_at", datetime.now().isoformat())[:10].replace("-", "_")
        transcript = client.get_transcript(doc_id)
        if not transcript:
            logger.warning("[GhostWriter][granola] Empty transcript for %s, skipping", doc_id)
            continue

        filename = f"granola_{created}_{title[:40]}.txt"
        path = output_dir / filename
        path.write_text(transcript)
        logger.info("[GhostWriter][granola] Saved %s", filename)

    return output_dir
