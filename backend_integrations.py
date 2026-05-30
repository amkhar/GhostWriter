"""Backend integration points for external task completion support."""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Dict, List, Callable

from flask import Flask, request, jsonify
import requests

from box_client import BoxClient
from models import TaskStatus

logger = logging.getLogger("ghostwriter.backend")


class TaskCompletionWebhook:
    """Webhook server to receive task completion notifications from external processes."""
    
    def __init__(self, box_client: BoxClient, root_folder_id: str = "0", port: int = 5555):
        self.box_client = box_client
        self.root_folder_id = root_folder_id
        self.app = Flask(__name__)
        self.port = port
        self._setup_routes()
        
    def _setup_routes(self):
        """Setup Flask routes for webhook endpoints."""
        
        @self.app.route('/health', methods=['GET'])
        def health():
            return jsonify({"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()})
        
        @self.app.route('/tasks/<task_id>/complete', methods=['POST'])
        def complete_task(task_id: str):
            """Mark a task as completed by external process."""
            try:
                data = request.get_json() or {}
                completed_by = data.get('completed_by', 'external')
                notes = data.get('notes', 'Completed by external process')
                error = data.get('error')  # If provided, marks as failed instead
                
                status = TaskStatus.FAILED if error else TaskStatus.COMPLETED
                
                self.box_client.update_task_status(
                    task_id=task_id,
                    status=status,
                    root_folder_id=self.root_folder_id,
                    error=error,
                    completed_by=completed_by,
                    notes=notes
                )
                
                logger.info("[webhook] Task %s marked as %s by %s", 
                           task_id, status.value, completed_by)
                
                return jsonify({
                    "success": True,
                    "task_id": task_id,
                    "status": status.value,
                    "completed_by": completed_by,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                
            except Exception as e:
                logger.error("[webhook] Failed to update task %s: %s", task_id, e)
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/tasks/<task_id>/status', methods=['POST'])
        def update_task_status(task_id: str):
            """Update task status with more granular control."""
            try:
                data = request.get_json()
                if not data:
                    return jsonify({"success": False, "error": "No JSON data provided"}), 400
                
                status_str = data.get('status')
                if not status_str:
                    return jsonify({"success": False, "error": "status field is required"}), 400
                
                try:
                    status = TaskStatus(status_str.lower())
                except ValueError:
                    return jsonify({
                        "success": False, 
                        "error": f"Invalid status. Valid values: {[s.value for s in TaskStatus]}"
                    }), 400
                
                self.box_client.update_task_status(
                    task_id=task_id,
                    status=status,
                    root_folder_id=self.root_folder_id,
                    error=data.get('error'),
                    completed_by=data.get('completed_by', 'external'),
                    notes=data.get('notes')
                )
                
                logger.info("[webhook] Task %s status updated to %s", task_id, status.value)
                
                return jsonify({
                    "success": True,
                    "task_id": task_id,
                    "status": status.value,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                
            except Exception as e:
                logger.error("[webhook] Failed to update task %s: %s", task_id, e)
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/tasks', methods=['GET'])
        def list_tasks():
            """List all tasks and their current status."""
            try:
                metadata_dict = self.box_client.load_task_metadata(self.root_folder_id)
                
                tasks = []
                for task_id, metadata in metadata_dict.items():
                    tasks.append({
                        "task_id": task_id,
                        "status": metadata.status.value,
                        "last_updated": metadata.last_updated.isoformat(),
                        "attempts": metadata.attempts,
                        "completed_by": metadata.completed_by,
                        "notes": metadata.notes,
                        "last_error": metadata.last_error
                    })
                
                return jsonify({
                    "success": True,
                    "tasks": tasks,
                    "total_count": len(tasks)
                })
                
            except Exception as e:
                logger.error("[webhook] Failed to list tasks: %s", e)
                return jsonify({"success": False, "error": str(e)}), 500
        
        @self.app.route('/tasks/<task_id>', methods=['GET'])
        def get_task_status(task_id: str):
            """Get status of a specific task."""
            try:
                metadata_dict = self.box_client.load_task_metadata(self.root_folder_id)
                
                if task_id not in metadata_dict:
                    return jsonify({"success": False, "error": "Task not found"}), 404
                
                metadata = metadata_dict[task_id]
                return jsonify({
                    "success": True,
                    "task_id": task_id,
                    "status": metadata.status.value,
                    "last_updated": metadata.last_updated.isoformat(),
                    "attempts": metadata.attempts,
                    "completed_by": metadata.completed_by,
                    "notes": metadata.notes,
                    "last_error": metadata.last_error
                })
                
            except Exception as e:
                logger.error("[webhook] Failed to get task %s: %s", task_id, e)
                return jsonify({"success": False, "error": str(e)}), 500
    
    def start_server(self, threaded: bool = True):
        """Start the webhook server."""
        if threaded:
            thread = threading.Thread(
                target=lambda: self.app.run(host='0.0.0.0', port=self.port, debug=False),
                daemon=True
            )
            thread.start()
            logger.info("[webhook] Started webhook server on port %d (threaded)", self.port)
            return thread
        else:
            logger.info("[webhook] Starting webhook server on port %d", self.port)
            self.app.run(host='0.0.0.0', port=self.port, debug=False)


class TaskSyncMonitor:
    """Background service to monitor and sync task completion status from various sources."""
    
    def __init__(self, box_client: BoxClient, root_folder_id: str = "0"):
        self.box_client = box_client
        self.root_folder_id = root_folder_id
        self.running = False
        self.thread = None
        self.completion_checkers: List[Callable[[str, Dict[str, Any]], Optional[Dict[str, Any]]]] = []
        
    def add_completion_checker(self, checker: Callable[[str, Dict[str, Any]], Optional[Dict[str, Any]]]):
        """Add a custom completion checker function.
        
        Args:
            checker: Function that takes (task_id, task_metadata_dict) and returns
                    completion info dict if task is completed, None otherwise.
                    Completion info should contain: {'completed_by': str, 'notes': str, 'error': str (optional)}
        """
        self.completion_checkers.append(checker)
        logger.info("[sync] Added completion checker: %s", checker.__name__)
    
    def start_monitoring(self, check_interval: int = 30):
        """Start background monitoring for task completions."""
        if self.running:
            logger.warning("[sync] Monitor already running")
            return
            
        self.running = True
        self.thread = threading.Thread(
            target=self._monitor_loop,
            args=(check_interval,),
            daemon=True
        )
        self.thread.start()
        logger.info("[sync] Started task sync monitor with %d second interval", check_interval)
    
    def stop_monitoring(self):
        """Stop the background monitoring."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("[sync] Stopped task sync monitor")
    
    def _monitor_loop(self, check_interval: int):
        """Main monitoring loop that runs in background thread."""
        while self.running:
            try:
                self._check_task_completions()
            except Exception as e:
                logger.error("[sync] Error during task completion check: %s", e)
            
            time.sleep(check_interval)
    
    def _check_task_completions(self):
        """Check all registered completion sources for task updates."""
        try:
            # Load current metadata
            metadata_dict = self.box_client.load_task_metadata(self.root_folder_id)
            
            # Only check tasks that are still pending or attempted
            pending_tasks = {
                task_id: metadata for task_id, metadata in metadata_dict.items()
                if metadata.status in [TaskStatus.PENDING, TaskStatus.ATTEMPTED]
            }
            
            if not pending_tasks:
                return
            
            logger.debug("[sync] Checking %d pending/attempted tasks for external completion", 
                        len(pending_tasks))
            
            # Run all completion checkers
            for task_id, metadata in pending_tasks.items():
                task_dict = {
                    "task_id": task_id,
                    "status": metadata.status.value,
                    "last_updated": metadata.last_updated.isoformat(),
                    "attempts": metadata.attempts,
                    "completed_by": metadata.completed_by,
                    "notes": metadata.notes,
                    "last_error": metadata.last_error
                }
                
                for checker in self.completion_checkers:
                    try:
                        completion_info = checker(task_id, task_dict)
                        if completion_info:
                            # Task was completed externally
                            status = TaskStatus.FAILED if completion_info.get('error') else TaskStatus.COMPLETED
                            
                            self.box_client.update_task_status(
                                task_id=task_id,
                                status=status,
                                root_folder_id=self.root_folder_id,
                                error=completion_info.get('error'),
                                completed_by=completion_info.get('completed_by', 'external'),
                                notes=completion_info.get('notes', 'Detected as completed by external process')
                            )
                            
                            logger.info("[sync] Task %s detected as %s by checker %s", 
                                       task_id, status.value, checker.__name__)
                            break  # Stop checking other checkers for this task
                            
                    except Exception as e:
                        logger.error("[sync] Error in completion checker %s for task %s: %s", 
                                   checker.__name__, task_id, e)
                        
        except Exception as e:
            logger.error("[sync] Failed to check task completions: %s", e)


class ExternalIntegrationClient:
    """Client for integrating with external systems that complete tasks."""
    
    def __init__(self, webhook_base_url: str):
        self.webhook_base_url = webhook_base_url.rstrip('/')
        self.session = requests.Session()
    
    def notify_task_completed(self, task_id: str, completed_by: str = "external", 
                            notes: str = None, error: str = None) -> bool:
        """Notify that a task has been completed by an external process."""
        try:
            payload = {
                "completed_by": completed_by,
                "notes": notes or f"Completed by {completed_by}",
            }
            if error:
                payload["error"] = error
            
            response = self.session.post(
                f"{self.webhook_base_url}/tasks/{task_id}/complete",
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            
            logger.info("[client] Successfully notified completion of task %s", task_id)
            return True
            
        except Exception as e:
            logger.error("[client] Failed to notify task completion for %s: %s", task_id, e)
            return False
    
    def update_task_status(self, task_id: str, status: str, completed_by: str = "external",
                          notes: str = None, error: str = None) -> bool:
        """Update task status via webhook."""
        try:
            payload = {
                "status": status,
                "completed_by": completed_by,
            }
            if notes:
                payload["notes"] = notes
            if error:
                payload["error"] = error
            
            response = self.session.post(
                f"{self.webhook_base_url}/tasks/{task_id}/status",
                json=payload,
                timeout=10
            )
            response.raise_for_status()
            
            logger.info("[client] Successfully updated task %s status to %s", task_id, status)
            return True
            
        except Exception as e:
            logger.error("[client] Failed to update task status for %s: %s", task_id, e)
            return False
    
    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a task."""
        try:
            response = self.session.get(
                f"{self.webhook_base_url}/tasks/{task_id}",
                timeout=10
            )
            response.raise_for_status()
            
            data = response.json()
            if data.get("success"):
                return data
            else:
                logger.error("[client] Failed to get task status: %s", data.get("error"))
                return None
                
        except Exception as e:
            logger.error("[client] Failed to get task status for %s: %s", task_id, e)
            return None
    
    def list_all_tasks(self) -> Optional[List[Dict[str, Any]]]:
        """Get status of all tasks."""
        try:
            response = self.session.get(
                f"{self.webhook_base_url}/tasks",
                timeout=10
            )
            response.raise_for_status()
            
            data = response.json()
            if data.get("success"):
                return data.get("tasks", [])
            else:
                logger.error("[client] Failed to list tasks: %s", data.get("error"))
                return None
                
        except Exception as e:
            logger.error("[client] Failed to list tasks: %s", e)
            return None


# ------------------------------------------------------------------ #
# Common completion checkers
# ------------------------------------------------------------------ #

def git_branch_completion_checker(task_id: str, task_metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Check if a task was completed by looking for merged git branches with task ID in name."""
    import subprocess
    
    try:
        # Look for merged branches containing the task ID
        result = subprocess.run(
            ["git", "branch", "-r", "--merged", "main"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            branches = result.stdout.strip().split('\n')
            for branch in branches:
                branch = branch.strip()
                if task_id in branch and 'origin/' in branch:
                    # Found a merged branch with task ID - assume task is completed
                    return {
                        "completed_by": "git",
                        "notes": f"Detected completion via merged git branch: {branch}",
                    }
    except Exception as e:
        logger.debug("[checker][git] Error checking git branches for task %s: %s", task_id, e)
    
    return None


def file_pattern_completion_checker(task_id: str, task_metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Check if a task was completed by looking for completion marker files."""
    # Look for files like .ghostwriter_completed_<task_id> or similar
    repo_root = Path.cwd()
    
    completion_patterns = [
        f".ghostwriter_completed_{task_id}",
        f"completed_{task_id}.txt",
        f".task_done_{task_id}",
    ]
    
    for pattern in completion_patterns:
        completion_file = repo_root / pattern
        if completion_file.exists():
            try:
                # Read completion info from file
                content = completion_file.read_text().strip()
                notes = content if content else f"Found completion marker file: {pattern}"
                
                return {
                    "completed_by": "file_marker",
                    "notes": notes,
                }
            except Exception as e:
                logger.debug("[checker][file] Error reading completion file %s: %s", completion_file, e)
                return {
                    "completed_by": "file_marker",
                    "notes": f"Found completion marker file: {pattern}",
                }
    
    return None


def github_issue_completion_checker(task_id: str, task_metadata: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Check if a task was completed by looking at GitHub issues (if GitHub token available)."""
    github_token = os.environ.get("GITHUB_TOKEN")
    github_repo = os.environ.get("GITHUB_REPO")  # Format: "owner/repo"
    
    if not github_token or not github_repo:
        return None
    
    try:
        # Look for closed issues mentioning the task ID
        headers = {
            "Authorization": f"token {github_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        # Search for issues mentioning the task ID
        response = requests.get(
            "https://api.github.com/search/issues",
            headers=headers,
            params={
                "q": f"repo:{github_repo} {task_id} is:closed",
                "sort": "updated",
                "order": "desc"
            },
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            if data.get("total_count", 0) > 0:
                issue = data["items"][0]  # Most recently updated
                return {
                    "completed_by": "github",
                    "notes": f"Task completed via GitHub issue #{issue['number']}: {issue['title']}"
                }
                
    except Exception as e:
        logger.debug("[checker][github] Error checking GitHub issues for task %s: %s", task_id, e)
    
    return None


# ------------------------------------------------------------------ #
# Convenience functions
# ------------------------------------------------------------------ #

def setup_backend_integrations(box_client: BoxClient, root_folder_id: str = "0", 
                              webhook_port: int = 5555, monitor_interval: int = 30) -> tuple[TaskCompletionWebhook, TaskSyncMonitor]:
    """Setup complete backend integration system."""
    
    # Create webhook server
    webhook_server = TaskCompletionWebhook(box_client, root_folder_id, webhook_port)
    
    # Create sync monitor
    sync_monitor = TaskSyncMonitor(box_client, root_folder_id)
    
    # Register common completion checkers
    sync_monitor.add_completion_checker(git_branch_completion_checker)
    sync_monitor.add_completion_checker(file_pattern_completion_checker)
    sync_monitor.add_completion_checker(github_issue_completion_checker)
    
    # Start services
    webhook_server.start_server(threaded=True)
    sync_monitor.start_monitoring(monitor_interval)
    
    logger.info("[backend] Backend integrations setup complete")
    logger.info("[backend] Webhook server: http://localhost:%d", webhook_port)
    logger.info("[backend] Sync monitor running with %d second intervals", monitor_interval)
    
    return webhook_server, sync_monitor


def notify_external_completion(task_id: str, completed_by: str = "external", 
                             notes: str = None, webhook_url: str = None) -> bool:
    """Convenience function to notify task completion from external processes."""
    webhook_url = webhook_url or os.environ.get("GHOSTWRITER_WEBHOOK_URL", "http://localhost:5555")
    
    client = ExternalIntegrationClient(webhook_url)
    return client.notify_task_completed(task_id, completed_by, notes)