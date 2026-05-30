"""Example integration script showing how external processes can notify GhostWriter of task completions.

This demonstrates various ways external systems (CI/CD, agents, manual processes) can
integrate with GhostWriter's backend to keep task metadata synchronized.
"""
import time
import logging
from backend_integrations import (
    ExternalIntegrationClient,
    notify_external_completion,
    git_branch_completion_checker,
    file_pattern_completion_checker
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ghostwriter.example")


def example_ci_cd_integration():
    """Example: CI/CD pipeline notifying task completion."""
    logger.info("=== CI/CD Integration Example ===")
    
    # This would typically be called from a CI/CD script after successful deployment
    webhook_url = "http://localhost:5555"
    
    # Example: deployment pipeline completed a task
    task_id = "fix-auth-bug"
    success = notify_external_completion(
        task_id=task_id,
        completed_by="ci/cd",
        notes="Deployed auth fix to production successfully. All tests passing.",
        webhook_url=webhook_url
    )
    
    if success:
        logger.info("✅ CI/CD successfully notified task completion")
    else:
        logger.error("❌ CI/CD failed to notify task completion")


def example_agent_integration():
    """Example: AI agent or automated tool notifying task completion."""
    logger.info("=== AI Agent Integration Example ===")
    
    client = ExternalIntegrationClient("http://localhost:5555")
    
    # Example: AI agent completed a documentation update
    success = client.notify_task_completed(
        task_id="update-readme-typos",
        completed_by="ai_agent",
        notes="Fixed 3 typos in README.md and updated installation instructions"
    )
    
    if success:
        logger.info("✅ AI agent successfully notified task completion")
    else:
        logger.error("❌ AI agent failed to notify task completion")
    
    # Example: Agent attempted a task but failed
    success = client.notify_task_completed(
        task_id="complex-refactor",
        completed_by="ai_agent", 
        error="Task too complex: requires breaking changes across 15+ files"
    )
    
    if success:
        logger.info("✅ AI agent successfully reported task failure")
    else:
        logger.error("❌ AI agent failed to report task failure")


def example_manual_integration():
    """Example: Manual developer workflow integration."""
    logger.info("=== Manual Developer Integration Example ===")
    
    client = ExternalIntegrationClient("http://localhost:5555")
    
    # Developer started working on a task
    client.update_task_status(
        task_id="implement-new-feature",
        status="attempted",
        completed_by="developer_alice",
        notes="Started implementation, created feature branch"
    )
    
    # Simulate some work time
    time.sleep(1)
    
    # Developer completed the task
    client.update_task_status(
        task_id="implement-new-feature", 
        status="completed",
        completed_by="developer_alice",
        notes="Feature implemented and tested. Ready for review."
    )
    
    logger.info("✅ Manual developer workflow integration completed")


def example_github_webhook_integration():
    """Example: GitHub webhook integration (pseudo-code)."""
    logger.info("=== GitHub Webhook Integration Example ===")
    
    # This would be implemented as a webhook endpoint that GitHub calls
    # when issues are closed or PRs are merged
    
    def handle_github_webhook(payload):
        """Handle GitHub webhook payload."""
        client = ExternalIntegrationClient("http://localhost:5555")
        
        if payload.get("action") == "closed":
            issue = payload.get("issue", {})
            # Extract task ID from issue title or body
            issue_title = issue.get("title", "")
            
            # Look for task ID patterns in the title
            import re
            task_match = re.search(r'\[([a-z0-9-]+)\]', issue_title)
            if task_match:
                task_id = task_match.group(1)
                
                client.notify_task_completed(
                    task_id=task_id,
                    completed_by="github",
                    notes=f"Task completed via GitHub issue #{issue.get('number')}: {issue_title}"
                )
                logger.info("✅ GitHub webhook integration processed task completion")
    
    # Simulate webhook call
    mock_payload = {
        "action": "closed",
        "issue": {
            "number": 123,
            "title": "[fix-login-validation] Fix email validation in login form",
            "state": "closed"
        }
    }
    
    handle_github_webhook(mock_payload)


def example_completion_checker_usage():
    """Example: Using built-in completion checkers."""
    logger.info("=== Completion Checker Example ===")
    
    # Example task metadata
    task_metadata = {
        "task_id": "update-dependencies", 
        "status": "attempted",
        "last_updated": "2024-01-15T10:30:00Z",
        "attempts": 1,
        "completed_by": None,
        "notes": "Attempted to update package.json dependencies",
        "last_error": None
    }
    
    # Check if task was completed via git branch
    git_result = git_branch_completion_checker("update-dependencies", task_metadata)
    if git_result:
        logger.info("✅ Git checker detected completion: %s", git_result["notes"])
    else:
        logger.info("ℹ️  Git checker: no completion detected")
    
    # Check if task was completed via file marker
    file_result = file_pattern_completion_checker("update-dependencies", task_metadata)
    if file_result:
        logger.info("✅ File checker detected completion: %s", file_result["notes"])
    else:
        logger.info("ℹ️  File checker: no completion detected")


def example_batch_status_sync():
    """Example: Syncing multiple task statuses in batch."""
    logger.info("=== Batch Status Sync Example ===")
    
    client = ExternalIntegrationClient("http://localhost:5555")
    
    # Get all current tasks
    tasks = client.list_all_tasks()
    if tasks:
        logger.info("Found %d tasks in system", len(tasks))
        
        # Example: mark all "attempted" tasks older than 1 hour as "failed" 
        # (timeout scenario)
        from datetime import datetime, timezone, timedelta
        
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)
        
        for task in tasks:
            if task["status"] == "attempted":
                last_updated = datetime.fromisoformat(task["last_updated"].replace("Z", "+00:00"))
                
                if last_updated < cutoff_time:
                    client.update_task_status(
                        task_id=task["task_id"],
                        status="failed", 
                        completed_by="timeout_monitor",
                        notes="Task timed out after 1 hour of no activity"
                    )
                    logger.info("⏰ Marked task %s as failed due to timeout", task["task_id"])
    
    logger.info("✅ Batch status sync completed")


def main():
    """Run all integration examples."""
    logger.info("GhostWriter Backend Integration Examples")
    logger.info("=" * 50)
    
    print("\nThese examples demonstrate how external systems can integrate with GhostWriter")
    print("to automatically update task completion status.\n")
    
    print("NOTE: Make sure the backend services are running first:")
    print("  python start_backend_services.py")
    print("  (or: ghostwriter-backend)")
    print()
    
    try:
        # Run examples
        example_ci_cd_integration()
        print()
        
        example_agent_integration()
        print()
        
        example_manual_integration()
        print()
        
        example_github_webhook_integration()
        print()
        
        example_completion_checker_usage()
        print()
        
        example_batch_status_sync()
        print()
        
        logger.info("✅ All integration examples completed")
        
    except Exception as e:
        logger.error("❌ Integration example failed: %s", e)
        print("\nTroubleshooting:")
        print("1. Is the backend service running? (python start_backend_services.py)")
        print("2. Are Box credentials configured?")
        print("3. Is the webhook URL accessible?")


if __name__ == "__main__":
    main()