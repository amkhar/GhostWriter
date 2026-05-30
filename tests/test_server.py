"""Unit tests for web API server database schema and task retrieval."""
import os
import sys
import tempfile
import sqlite3
import json
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import web.api.server as server


def test_db_init_and_columns():
    """Verify that init_db dynamically adds priority and evidence columns to tasks table."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "ghostwriter_test.db"
        with patch("web.api.server.DB_PATH", test_db):
            server.init_db()
            
            # Inspect tasks table columns
            conn = sqlite3.connect(str(test_db))
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(tasks)")
            columns = [row[1] for row in cursor.fetchall()]
            conn.close()
            
            assert "priority" in columns
            assert "evidence" in columns


def test_db_tasks_serialize_deserialize():
    """Verify that tasks can be saved and deserialized with JSON evidence lists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db = Path(tmpdir) / "ghostwriter_test.db"
        with patch("web.api.server.DB_PATH", test_db):
            server.init_db()
            
            conn = server.get_db()
            # 1. Insert a run
            conn.execute("INSERT INTO runs (id, started_at, status) VALUES ('run1', '2026-05-30T12:00:00', 'complete')")
            # 2. Insert a task with priority and json evidence list
            conn.execute(
                "INSERT INTO tasks (id, run_id, title, description, reason, auto_doable, category, reasoning, priority, evidence) "
                "VALUES ('task1', 'run1', 'Test Title', 'Test Desc', 'Test Reason', 1, 'category', 'reasoning', 'high', ?)",
                (json.dumps(["evidence 1", "evidence 2"]),)
            )
            conn.commit()
            conn.close()
            
            # Retrieve run detail
            run_data = conn = None
            
            # Since server methods use get_db(), mock the module DB_PATH globally
            # so get_db inside server.py connects to the test database
            import fastapi
            from fastapi.testclient import TestClient
            
            client = TestClient(server.app)
            response = client.get("/api/pipeline/runs/run1")
            assert response.status_code == 200
            
            data = response.json()
            assert len(data["tasks"]) == 1
            t = data["tasks"][0]
            assert t["id"] == "task1"
            assert t["priority"] == "high"
            assert t["evidence"] == ["evidence 1", "evidence 2"]
