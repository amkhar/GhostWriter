"""Box API layer — all Box interactions are isolated here."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

import requests

from models import Task, StatusMentioned, TaskMetadata, TaskStatus

logger = logging.getLogger("ghostwriter.box")

_BOX_API = "https://api.box.com/2.0"
_BOX_AI = "https://api.box.com/2.0/ai"

_EXTRACT_PROMPT = (
    "Extract all tasks, action items, and to-dos from this standup or scrum transcript. "
    "For each task return: title, description, owner (person responsible, or null), "
    "status_mentioned (one of: todo, in_progress, blocked, done, unclear), "
    "is_action_item (true if explicitly called out as an action item)."
)

_RECURRENCE_PROMPT = (
    "From these standup transcripts, identify ALL tasks, blockers, or issues that are "
    "NOT marked as done or resolved. Include tasks mentioned even once if they appear "
    "neglected, skipped, unassigned, blocked, or overdue. "
    "For each such task, provide: title, description, and a short reason string explaining "
    "why it seems neglected (e.g. 'mentioned as blocker but unassigned', 'raised in 3 standups, "
    "still not done'). Return a JSON array of objects with keys: "
    "title, description, reason."
)


class BoxClient:
    def __init__(self, dev_token: str = None, *, client_id: str = None, client_secret: str = None) -> None:
        """Initialize with either a developer token or CCG credentials.

        CCG (Client Credentials Grant) is preferred — tokens auto-refresh.
        Falls back to dev_token if CCG creds aren't provided.
        """
        self._session = requests.Session()
        self._client_id = client_id
        self._client_secret = client_secret

        if client_id and client_secret:
            # CCG auth — try to get a fresh token
            try:
                self._token = self._ccg_token()
                logger.info("[box] Using CCG authentication (auto-refresh)")
            except Exception as e:
                if dev_token:
                    self._token = dev_token
                    logger.warning("[box] CCG auth failed (%s), falling back to developer token", e)
                else:
                    raise
        elif dev_token:
            self._token = dev_token
            logger.info("[box] Using developer token")
        else:
            raise ValueError("Provide either dev_token or client_id+client_secret")

        self._session.headers.update({"Authorization": f"Bearer {self._token}"})

    def _ccg_token(self) -> str:
        """Obtain an access token via Client Credentials Grant."""
        import os
        resp = requests.post(
            "https://api.box.com/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "box_subject_type": "enterprise",
                "box_subject_id": os.environ.get("BOX_ENTERPRISE_ID", "0"),
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def _refresh_if_needed(self, resp: requests.Response) -> bool:
        """If 401 and we have CCG creds, refresh token and return True."""
        if resp.status_code == 401 and self._client_id:
            logger.info("[box] Token expired, refreshing via CCG...")
            self._token = self._ccg_token()
            self._session.headers.update({"Authorization": f"Bearer {self._token}"})
            return True
        return False

    # ------------------------------------------------------------------ #
    # Folder helpers
    # ------------------------------------------------------------------ #

    def ensure_folder(self, name: str, parent_id: str = "0") -> str:
        """Return folder ID, creating it if it doesn't exist."""
        # List children of parent
        resp = self._session.get(
            f"{_BOX_API}/folders/{parent_id}/items",
            params={"fields": "id,name,type", "limit": 1000},
        )
        resp.raise_for_status()
        for item in resp.json().get("entries", []):
            if item["type"] == "folder" and item["name"] == name:
                return item["id"]
        # Create
        resp = self._session.post(
            f"{_BOX_API}/folders",
            json={"name": name, "parent": {"id": parent_id}},
        )
        resp.raise_for_status()
        return resp.json()["id"]

    # ------------------------------------------------------------------ #
    # File operations
    # ------------------------------------------------------------------ #

    def upload_transcript(self, file_path: Path, folder_id: str) -> str:
        """Upload a transcript file to Box; return Box file ID."""
        logger.info("[ingest] Uploading %s to folder %s", file_path.name, folder_id)
        with open(file_path, "rb") as fh:
            resp = requests.post(
                "https://upload.box.com/api/2.0/files/content",
                headers={"Authorization": f"Bearer {self._token}"},
                data={"attributes": json.dumps({"name": file_path.name, "parent": {"id": folder_id}})},
                files={"file": (file_path.name, fh, "text/plain")},
            )
        if resp.status_code == 409:
            # File already exists — return existing ID
            existing_id = resp.json()["context_info"]["conflicts"]["id"]
            logger.info("[ingest] File already exists, reusing ID %s", existing_id)
            return existing_id
        resp.raise_for_status()
        return resp.json()["entries"][0]["id"]

    def upload_report(self, content: str, folder_id: str, filename: str = "ghostwriter_report.md") -> str:
        """Upload Markdown report to Box; return file ID."""
        import io
        logger.info("[report] Uploading report to folder %s", folder_id)
        resp = requests.post(
            "https://upload.box.com/api/2.0/files/content",
            headers={"Authorization": f"Bearer {self._token}"},
            data={"attributes": json.dumps({"name": filename, "parent": {"id": folder_id}})},
            files={"file": (filename, io.BytesIO(content.encode()), "text/markdown")},
        )
        if resp.status_code == 409:
            existing_id = resp.json()["context_info"]["conflicts"]["id"]
            # Overwrite with new version
            resp2 = requests.post(
                f"https://upload.box.com/api/2.0/files/{existing_id}/content",
                headers={"Authorization": f"Bearer {self._token}"},
                data={"attributes": json.dumps({"name": filename})},
                files={"file": (filename, io.BytesIO(content.encode()), "text/markdown")},
            )
            resp2.raise_for_status()
            return resp2.json()["entries"][0]["id"]
        resp.raise_for_status()
        return resp.json()["entries"][0]["id"]

    # ------------------------------------------------------------------ #
    # Metadata storage and retrieval
    # ------------------------------------------------------------------ #

    def load_task_metadata(self, root_folder_id: str = "0") -> dict[str, TaskMetadata]:
        """Load task metadata from Box storage. Returns dict of task_id -> TaskMetadata."""
        try:
            metadata_folder = self.ensure_folder("metadata", root_folder_id)
            
            # List files in metadata folder
            resp = self._session.get(
                f"{_BOX_API}/folders/{metadata_folder}/items",
                params={"fields": "id,name,type", "limit": 1000},
            )
            resp.raise_for_status()
            
            metadata_dict = {}
            for item in resp.json().get("entries", []):
                if item["type"] == "file" and item["name"] == "task_metadata.json":
                    # Download and parse metadata file
                    file_resp = self._session.get(
                        f"{_BOX_API}/files/{item['id']}/content",
                    )
                    file_resp.raise_for_status()
                    metadata_data = json.loads(file_resp.text)
                    
                    for task_id, meta_dict in metadata_data.items():
                        # Convert datetime string back to datetime object
                        meta_dict["last_updated"] = datetime.fromisoformat(meta_dict["last_updated"])
                        metadata_dict[task_id] = TaskMetadata(**meta_dict)
                    
                    logger.info("[metadata] Loaded metadata for %d tasks", len(metadata_dict))
                    return metadata_dict
                    
            logger.info("[metadata] No existing metadata file found")
            return {}
            
        except Exception as e:
            logger.warning("[metadata] Failed to load task metadata: %s", e)
            return {}

    def save_task_metadata(self, metadata_dict: dict[str, TaskMetadata], root_folder_id: str = "0") -> None:
        """Save task metadata to Box storage."""
        try:
            metadata_folder = self.ensure_folder("metadata", root_folder_id)
            
            # Convert metadata to JSON-serializable format
            json_data = {}
            for task_id, metadata in metadata_dict.items():
                json_data[task_id] = {
                    "task_id": metadata.task_id,
                    "status": metadata.status.value,
                    "last_updated": metadata.last_updated.isoformat(),
                    "attempts": metadata.attempts,
                    "last_error": metadata.last_error,
                    "completed_by": metadata.completed_by,
                    "notes": metadata.notes,
                }
            
            content = json.dumps(json_data, indent=2)
            
            # Upload to Box
            import io
            resp = requests.post(
                "https://upload.box.com/api/2.0/files/content",
                headers={"Authorization": f"Bearer {self._token}"},
                data={"attributes": json.dumps({"name": "task_metadata.json", "parent": {"id": metadata_folder}})},
                files={"file": ("task_metadata.json", io.BytesIO(content.encode()), "application/json")},
            )
            
            if resp.status_code == 409:
                # File exists, update it
                existing_id = resp.json()["context_info"]["conflicts"]["id"]
                resp2 = requests.post(
                    f"https://upload.box.com/api/2.0/files/{existing_id}/content",
                    headers={"Authorization": f"Bearer {self._token}"},
                    data={"attributes": json.dumps({"name": "task_metadata.json"})},
                    files={"file": ("task_metadata.json", io.BytesIO(content.encode()), "application/json")},
                )
                resp2.raise_for_status()
                logger.info("[metadata] Updated task metadata for %d tasks", len(metadata_dict))
            else:
                resp.raise_for_status()
                logger.info("[metadata] Saved task metadata for %d tasks", len(metadata_dict))
                
        except Exception as e:
            logger.error("[metadata] Failed to save task metadata: %s", e)
            raise

    def update_task_status(self, task_id: str, status: TaskStatus, 
                          root_folder_id: str = "0", error: str = None, 
                          completed_by: str = None, notes: str = None) -> None:
        """Update a single task's status in metadata."""
        metadata_dict = self.load_task_metadata(root_folder_id)
        
        if task_id in metadata_dict:
            metadata = metadata_dict[task_id]
            metadata.status = status
            metadata.last_updated = datetime.now(timezone.utc)
            if status == TaskStatus.ATTEMPTED:
                metadata.attempts += 1
            if error:
                metadata.last_error = error
            if completed_by:
                metadata.completed_by = completed_by
            if notes:
                metadata.notes = notes
        else:
            metadata_dict[task_id] = TaskMetadata(
                task_id=task_id,
                status=status,
                last_updated=datetime.now(timezone.utc),
                attempts=1 if status == TaskStatus.ATTEMPTED else 0,
                last_error=error,
                completed_by=completed_by,
                notes=notes,
            )
        
        self.save_task_metadata(metadata_dict, root_folder_id)

    # ------------------------------------------------------------------ #
    # Box AI
    # ------------------------------------------------------------------ #

    def ai_extract(self, file_id: str) -> list[dict[str, Any]]:
        """Call Box AI Extract (freeform) for a single file; return list of raw task dicts."""
        logger.info("[extract] Box AI Extract for file %s", file_id)
        payload = {
            "items": [{"type": "file", "id": file_id}],
            "prompt": _EXTRACT_PROMPT,
            "fields": [
                {"key": "title"},
                {"key": "description"},
                {"key": "owner"},
                {
                    "key": "status_mentioned",
                    "options": [
                        {"key": "todo"},
                        {"key": "in_progress"},
                        {"key": "blocked"},
                        {"key": "done"},
                        {"key": "unclear"},
                    ],
                },
                {"key": "is_action_item", "type": "boolean"},
            ],
        }
        resp = self._session.post(f"{_BOX_AI}/extract", json=payload)
        resp.raise_for_status()
        data = resp.json()
        # Box AI Extract returns a dict of field→value; wrap in list
        if isinstance(data, dict):
            # May be a single task or a nested structure
            if "tasks" in data:
                return data["tasks"]
            # Try to parse as a list embedded in the answer
            return [data]
        if isinstance(data, list):
            return data
        return []

    def ai_ask_multi(self, file_ids: list[str], prompt: str) -> str:
        """Call Box AI Ask in multi-file mode; return raw answer string."""
        logger.info("[recurrence] Box AI Ask over %d files", len(file_ids))
        payload = {
            "mode": "multiple_item_qa",
            "prompt": prompt,
            "items": [{"type": "file", "id": fid} for fid in file_ids],
        }
        resp = self._session.post(f"{_BOX_AI}/ask", json=payload)
        resp.raise_for_status()
        return resp.json().get("answer", "")

    # ------------------------------------------------------------------ #
    # Parsing helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def parse_tasks(raw: list[dict[str, Any]], source_transcript: str) -> list[Task]:
        """Convert raw Box AI Extract dicts into Task objects."""
        tasks: list[Task] = []
        for item in raw:
            title = item.get("title")
            if not title or not isinstance(title, str):
                continue
            status_raw = item.get("status_mentioned") or "unclear"
            if not isinstance(status_raw, str):
                status_raw = "unclear"
            status_raw = status_raw.lower().replace(" ", "_")
            try:
                status = StatusMentioned(status_raw)
            except ValueError:
                status = StatusMentioned.UNCLEAR
            is_action = item.get("is_action_item")
            if isinstance(is_action, str):
                is_action = is_action.lower() in ("true", "yes", "1")
            desc = item.get("description") or title
            if not isinstance(desc, str):
                desc = title
            owner = item.get("owner") or None
            if owner is not None and not isinstance(owner, str):
                owner = str(owner)
            tasks.append(
                Task(
                    title=title,
                    description=desc,
                    owner=owner,
                    status_mentioned=status,
                    is_action_item=bool(is_action),
                    source_transcript=source_transcript,
                )
            )
        return tasks

    @staticmethod
    def parse_neglected(answer: str) -> list[dict[str, str]]:
        """Parse the Box AI Ask answer into a list of {title, description, reason} dicts."""
        import re
        # Try to extract JSON array from the answer
        match = re.search(r"\[.*\]", answer, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        # Fallback: return empty
        logger.warning("[recurrence] Could not parse neglected tasks from Box AI answer")
        return []