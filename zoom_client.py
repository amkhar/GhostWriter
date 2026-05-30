"""Zoom integration — fetch cloud recording transcripts via Server-to-Server OAuth."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class ZoomClient:
    """Fetches meeting transcripts from Zoom Cloud Recordings."""

    TOKEN_URL = "https://zoom.us/oauth/token"
    API_BASE = "https://api.zoom.us/v2"

    def __init__(self, account_id: str, client_id: str, client_secret: str):
        self.account_id = account_id
        self.client_id = client_id
        self.client_secret = client_secret
        self._access_token: Optional[str] = None

    def _get_token(self) -> str:
        if self._access_token:
            return self._access_token
        resp = requests.post(
            self.TOKEN_URL,
            params={"grant_type": "account_credentials", "account_id": self.account_id},
            auth=(self.client_id, self.client_secret),
            timeout=30,
        )
        resp.raise_for_status()
        self._access_token = resp.json()["access_token"]
        return self._access_token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._get_token()}"}

    def list_recordings(self, user_id: str = "me", from_date: Optional[str] = None) -> list[dict]:
        """List cloud recordings for a user. Returns meetings with transcript files."""
        params: dict = {"page_size": "50"}
        if from_date:
            params["from"] = from_date
        resp = requests.get(
            f"{self.API_BASE}/users/{user_id}/recordings",
            headers=self._headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("meetings", [])

    def download_transcript(self, download_url: str) -> str:
        """Download a transcript VTT file and return its text content."""
        resp = requests.get(
            download_url,
            headers=self._headers(),
            timeout=60,
        )
        resp.raise_for_status()
        return resp.text

    def fetch_transcripts(self, user_id: str = "me", from_date: Optional[str] = None) -> list[tuple[str, str]]:
        """Fetch all available transcripts. Returns list of (filename, content) tuples."""
        meetings = self.list_recordings(user_id=user_id, from_date=from_date)
        results: list[tuple[str, str]] = []
        for meeting in meetings:
            topic = meeting.get("topic", "meeting")
            start = meeting.get("start_time", "")[:10]
            for rec_file in meeting.get("recording_files", []):
                if rec_file.get("file_type") == "TRANSCRIPT" and rec_file.get("download_url"):
                    filename = f"zoom_{start}_{topic.replace(' ', '_')[:40]}.txt"
                    try:
                        content = self.download_transcript(rec_file["download_url"])
                        results.append((filename, content))
                        logger.info("[Zoom] Fetched transcript: %s", filename)
                    except Exception as e:
                        logger.error("[Zoom] Failed to download transcript for %s: %s", topic, e)
        return results

    def save_transcripts(self, output_dir: Path, user_id: str = "me", from_date: Optional[str] = None) -> list[Path]:
        """Fetch transcripts and save to output_dir. Returns list of saved file paths."""
        output_dir.mkdir(parents=True, exist_ok=True)
        transcripts = self.fetch_transcripts(user_id=user_id, from_date=from_date)
        paths: list[Path] = []
        for filename, content in transcripts:
            path = output_dir / filename
            path.write_text(content)
            paths.append(path)
        return paths
