"""Tests for box_client.py — mocked Box API interactions.

Properties tested:
  P5: Task extraction schema completeness
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from hypothesis import given, settings
from hypothesis import strategies as st
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from box_client import BoxClient
from models import StatusMentioned


# ------------------------------------------------------------------ #
# Unit tests
# ------------------------------------------------------------------ #

@pytest.fixture
def client():
    return BoxClient("fake-token")


def test_parse_tasks_basic(client):
    raw = [
        {"title": "Fix typo", "description": "Fix it", "owner": "Alice",
         "status_mentioned": "todo", "is_action_item": True}
    ]
    tasks = BoxClient.parse_tasks(raw, "t.txt")
    assert len(tasks) == 1
    assert tasks[0].title == "Fix typo"
    assert tasks[0].status_mentioned == StatusMentioned.TODO
    assert tasks[0].is_action_item is True
    assert tasks[0].source_transcript == "t.txt"


def test_parse_tasks_missing_optional_fields(client):
    raw = [{"title": "Do something"}]
    tasks = BoxClient.parse_tasks(raw, "t.txt")
    assert len(tasks) == 1
    assert tasks[0].owner is None
    assert tasks[0].status_mentioned == StatusMentioned.UNCLEAR
    assert tasks[0].is_action_item is False


def test_parse_tasks_empty_list(client):
    assert BoxClient.parse_tasks([], "t.txt") == []


def test_parse_tasks_skips_no_title(client):
    raw = [{"description": "no title here"}]
    tasks = BoxClient.parse_tasks(raw, "t.txt")
    assert tasks == []


def test_parse_tasks_invalid_status_defaults_unclear(client):
    raw = [{"title": "T", "status_mentioned": "INVALID_STATUS"}]
    tasks = BoxClient.parse_tasks(raw, "t.txt")
    assert tasks[0].status_mentioned == StatusMentioned.UNCLEAR


def test_parse_tasks_bool_string_is_action_item(client):
    raw = [{"title": "T", "is_action_item": "true"}]
    tasks = BoxClient.parse_tasks(raw, "t.txt")
    assert tasks[0].is_action_item is True


def test_parse_neglected_valid_json(client):
    answer = 'Some text [{"title": "Fix README", "description": "Update it", "reason": "3 standups"}] more text'
    result = BoxClient.parse_neglected(answer)
    assert len(result) == 1
    assert result[0]["title"] == "Fix README"


def test_parse_neglected_no_json_returns_empty(client):
    result = BoxClient.parse_neglected("No JSON here at all")
    assert result == []


def test_upload_transcript_success(tmp_path, client):
    f = tmp_path / "test.txt"
    f.write_text("hello")
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"entries": [{"id": "file123"}]}
    with patch("requests.post", return_value=mock_resp):
        fid = client.upload_transcript(f, "folder1")
    assert fid == "file123"


def test_upload_transcript_conflict_deletes_and_reuploads(tmp_path, client):
    f = tmp_path / "test.txt"
    f.write_text("hello")
    conflict_resp = MagicMock()
    conflict_resp.status_code = 409
    conflict_resp.json.return_value = {"context_info": {"conflicts": {"id": "existing123"}}}
    success_resp = MagicMock()
    success_resp.status_code = 201
    success_resp.raise_for_status = MagicMock()
    success_resp.json.return_value = {"entries": [{"id": "new456"}]}
    delete_resp = MagicMock()
    delete_resp.raise_for_status = MagicMock()
    client._session.delete = MagicMock(return_value=delete_resp)
    with patch("requests.post", side_effect=[conflict_resp, success_resp]):
        fid = client.upload_transcript(f, "folder1")
    assert fid == "new456"
    client._session.delete.assert_called_once()


def test_ai_extract_returns_list(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = [
        {"title": "Task A", "description": "Do A", "status_mentioned": "todo"}
    ]
    client._session.post = MagicMock(return_value=mock_resp)
    result = client.ai_extract("file123")
    assert isinstance(result, list)
    assert result[0]["title"] == "Task A"


def test_ai_ask_multi_returns_string(client):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"answer": '[{"title": "T", "description": "D", "reason": "R"}]'}
    client._session.post = MagicMock(return_value=mock_resp)
    result = client.ai_ask_multi(["f1", "f2"], "prompt")
    assert isinstance(result, str)
    assert "title" in result


# ------------------------------------------------------------------ #
# Property-based tests
# ------------------------------------------------------------------ #

# Feature: ghostwriter, Property 5: Task extraction schema completeness
@given(st.dictionaries(
    keys=st.sampled_from(["title", "description", "owner", "status_mentioned", "is_action_item", "extra"]),
    values=st.one_of(st.text(max_size=50), st.booleans(), st.none()),
    min_size=0,
    max_size=6,
))
@settings(max_examples=200)
def test_parse_tasks_never_raises_on_partial_response(raw_dict):
    """parse_tasks should never raise on any partial Box AI response dict."""
    try:
        tasks = BoxClient.parse_tasks([raw_dict], "t.txt")
        # If title is present, we get a task; otherwise empty
        for t in tasks:
            assert t.source_transcript == "t.txt"
            assert t.status_mentioned in StatusMentioned.__members__.values()
    except Exception as e:
        pytest.fail(f"parse_tasks raised unexpectedly: {e}")
