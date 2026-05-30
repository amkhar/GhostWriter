"""Tests for metadata tracking functionality."""
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from box_client import BoxClient
from models import TaskMetadata, TaskStatus, NeglectedTask
from pipeline import load_and_filter_metadata


@pytest.fixture
def box_client():
    return BoxClient("fake-token")


def test_task_metadata_creation():
    """Test TaskMetadata model creation and serialization."""
    metadata = TaskMetadata(
        task_id="test-task",
        status=TaskStatus.COMPLETED,
        last_updated=datetime.now(timezone.utc),
        attempts=2,
        completed_by="auto",
        notes="Successfully implemented"
    )
    
    assert metadata.task_id == "test-task"
    assert metadata.status == TaskStatus.COMPLETED
    assert metadata.attempts == 2
    assert metadata.completed_by == "auto"


def test_load_task_metadata_empty(box_client):
    """Test loading metadata when no file exists."""
    with patch.object(box_client, 'ensure_folder', return_value="meta123"):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"entries": []}
        
        with patch.object(box_client._session, 'get', return_value=mock_resp):
            result = box_client.load_task_metadata("0")
            
        assert result == {}


def test_load_task_metadata_with_data(box_client):
    """Test loading metadata with existing data."""
    test_data = {
        "task-1": {
            "task_id": "task-1",
            "status": "completed",
            "last_updated": "2024-01-01T12:00:00+00:00",
            "attempts": 1,
            "completed_by": "auto",
            "notes": "Test task"
        }
    }
    
    with patch.object(box_client, 'ensure_folder', return_value="meta123"):
        # Mock folder listing response
        list_resp = MagicMock()
        list_resp.raise_for_status.return_value = None
        list_resp.json.return_value = {
            "entries": [{"type": "file", "name": "task_metadata.json", "id": "file123"}]
        }
        
        # Mock file download response
        file_resp = MagicMock()
        file_resp.raise_for_status.return_value = None
        file_resp.text = json.dumps(test_data)
        
        with patch.object(box_client._session, 'get') as mock_get:
            mock_get.side_effect = [list_resp, file_resp]
            result = box_client.load_task_metadata("0")
            
        assert len(result) == 1
        assert "task-1" in result
        metadata = result["task-1"]
        assert metadata.status == TaskStatus.COMPLETED
        assert metadata.completed_by == "auto"


def test_save_task_metadata(box_client):
    """Test saving metadata to Box."""
    metadata_dict = {
        "task-1": TaskMetadata(
            task_id="task-1",
            status=TaskStatus.COMPLETED,
            last_updated=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            attempts=1,
            completed_by="auto",
            notes="Test task"
        )
    }
    
    with patch.object(box_client, 'ensure_folder', return_value="meta123"):
        with patch('requests.post') as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.raise_for_status.return_value = None
            mock_post.return_value = mock_resp
            
            box_client.save_task_metadata(metadata_dict, "0")
            
            # Verify the request was made
            assert mock_post.called
            call_args = mock_post.call_args
            
            # Check that JSON data was properly formatted
            files_data = call_args[1]['files']['file'][1].read().decode()
            parsed_data = json.loads(files_data)
            
            assert "task-1" in parsed_data
            assert parsed_data["task-1"]["status"] == "completed"
            assert parsed_data["task-1"]["completed_by"] == "auto"


def test_update_task_status_new_task(box_client):
    """Test updating status for a new task."""
    with patch.object(box_client, 'load_task_metadata', return_value={}):
        with patch.object(box_client, 'save_task_metadata') as mock_save:
            box_client.update_task_status("new-task", TaskStatus.COMPLETED, "0", completed_by="manual")
            
            # Verify save was called with new metadata
            mock_save.assert_called_once()
            metadata_dict = mock_save.call_args[0][0]
            
            assert "new-task" in metadata_dict
            metadata = metadata_dict["new-task"]
            assert metadata.status == TaskStatus.COMPLETED
            assert metadata.completed_by == "manual"


def test_update_task_status_existing_task(box_client):
    """Test updating status for an existing task."""
    existing_metadata = {
        "existing-task": TaskMetadata(
            task_id="existing-task",
            status=TaskStatus.PENDING,
            last_updated=datetime(2024, 1, 1, tzinfo=timezone.utc),
            attempts=0
        )
    }
    
    with patch.object(box_client, 'load_task_metadata', return_value=existing_metadata):
        with patch.object(box_client, 'save_task_metadata') as mock_save:
            box_client.update_task_status(
                "existing-task", 
                TaskStatus.ATTEMPTED, 
                "0", 
                error="Test error"
            )
            
            # Verify save was called with updated metadata
            mock_save.assert_called_once()
            metadata_dict = mock_save.call_args[0][0]
            
            assert "existing-task" in metadata_dict
            metadata = metadata_dict["existing-task"]
            assert metadata.status == TaskStatus.ATTEMPTED
            assert metadata.attempts == 1
            assert metadata.last_error == "Test error"


def test_load_and_filter_metadata_pipeline():
    """Test the pipeline function that loads and filters metadata."""
    # Create test tasks
    neglected_tasks = [
        NeglectedTask(
            id="task-1",
            title="Fix bug",
            description="Fix the bug",
            reason="Mentioned in 3 standups"
        ),
        NeglectedTask(
            id="task-2", 
            title="Update docs",
            description="Update documentation",
            reason="Overdue for 2 weeks"
        )
    ]
    
    # Mock metadata - task-1 is completed, task-2 is pending
    mock_metadata = {
        "task-1": TaskMetadata(
            task_id="task-1",
            status=TaskStatus.COMPLETED,
            last_updated=datetime.now(timezone.utc),
            completed_by="auto"
        )
    }
    
    mock_box = MagicMock()
    mock_box.load_task_metadata.return_value = mock_metadata
    
    from models import PipelineConfig
    config = PipelineConfig(
        aws_region="us-east-1",
        bedrock_model_id="test-model",
        box_root_folder_id="0"
    )
    
    result = load_and_filter_metadata(neglected_tasks, mock_box, config)
    
    assert len(result) == 2
    
    # Check that task-1 has completed metadata
    task1 = next(t for t in result if t.id == "task-1")
    assert task1.metadata is not None
    assert task1.metadata.status == TaskStatus.COMPLETED
    
    # Check that task-2 has pending metadata
    task2 = next(t for t in result if t.id == "task-2") 
    assert task2.metadata is not None
    assert task2.metadata.status == TaskStatus.PENDING


def test_load_and_filter_metadata_error_handling():
    """Test error handling in metadata loading."""
    neglected_tasks = [
        NeglectedTask(
            id="test-task",
            title="Test",
            description="Test task",
            reason="Test reason"
        )
    ]
    
    mock_box = MagicMock()
    mock_box.load_task_metadata.side_effect = Exception("Box error")
    
    from models import PipelineConfig
    config = PipelineConfig(
        aws_region="us-east-1",
        bedrock_model_id="test-model",
        box_root_folder_id="0"
    )
    
    # Should not raise, but continue with default metadata
    result = load_and_filter_metadata(neglected_tasks, mock_box, config)
    
    assert len(result) == 1
    assert result[0].metadata is not None
    assert result[0].metadata.status == TaskStatus.PENDING


def test_report_generation_with_metadata():
    """Test that reports include metadata information."""
    from models import RunReport, NeglectedTask, TaskMetadata, TaskStatus
    
    # Create a task with metadata
    task = NeglectedTask(
        id="test-task",
        title="Fix issue",
        description="Fix the issue",
        reason="Recurring in meetings",
        metadata=TaskMetadata(
            task_id="test-task",
            status=TaskStatus.COMPLETED,
            last_updated=datetime.now(timezone.utc),
            completed_by="auto",
            notes="Auto-implemented successfully"
        )
    )
    
    report = RunReport(
        run_id="test123",
        dry_run=True,
        neglected_tasks=[task]
    )
    
    markdown = report.to_markdown()
    
    # Check that metadata is included in the report
    assert "✅ completed" in markdown.lower()
    assert "**completed by:** auto" in markdown.lower()
    assert "auto-implemented successfully" in markdown.lower()


if __name__ == "__main__":
    pytest.main([__file__])