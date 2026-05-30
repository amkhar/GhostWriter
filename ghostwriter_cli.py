#!/usr/bin/env python3
"""CLI tool for external processes to notify GhostWriter about task completions."""

import argparse
import json
import logging
import sys
from typing import Optional

from backend_integrations import ExternalIntegrationClient

logger = logging.getLogger("ghostwriter.cli")


def setup_logging(verbose: bool = False):
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def complete_task(client: ExternalIntegrationClient, task_id: str, 
                 completed_by: str, notes: Optional[str] = None, 
                 error: Optional[str] = None) -> bool:
    """Mark a task as completed."""
    print(f"Marking task '{task_id}' as {'failed' if error else 'completed'} by '{completed_by}'...")
    
    success = client.notify_task_completed(
        task_id=task_id,
        completed_by=completed_by,
        notes=notes,
        error=error
    )
    
    if success:
        print("✅ Task completion notification sent successfully")
        return True
    else:
        print("❌ Failed to send task completion notification")
        return False


def update_status(client: ExternalIntegrationClient, task_id: str, status: str,
                 completed_by: str, notes: Optional[str] = None, 
                 error: Optional[str] = None) -> bool:
    """Update task status."""
    print(f"Updating task '{task_id}' status to '{status}' by '{completed_by}'...")
    
    success = client.update_task_status(
        task_id=task_id,
        status=status,
        completed_by=completed_by,
        notes=notes,
        error=error
    )
    
    if success:
        print("✅ Task status update sent successfully")
        return True
    else:
        print("❌ Failed to send task status update")
        return False


def get_task(client: ExternalIntegrationClient, task_id: str) -> bool:
    """Get task status."""
    print(f"Getting status for task '{task_id}'...")
    
    result = client.get_task_status(task_id)
    if result:
        print("✅ Task found:")
        print(json.dumps(result, indent=2))
        return True
    else:
        print("❌ Task not found or request failed")
        return False


def list_tasks(client: ExternalIntegrationClient) -> bool:
    """List all tasks."""
    print("Listing all tasks...")
    
    tasks = client.list_all_tasks()
    if tasks is not None:
        print(f"✅ Found {len(tasks)} tasks:")
        
        if not tasks:
            print("  (no tasks)")
        else:
            for task in tasks:
                status_icon = {
                    "completed": "✅",
                    "failed": "❌", 
                    "skipped": "⏭️",
                    "attempted": "🔄",
                    "pending": "⏸️"
                }.get(task.get("status"), "❓")
                
                print(f"  {status_icon} {task['task_id']:<30} {task['status']:<12} {task.get('completed_by', 'N/A'):<15}")
        
        return True
    else:
        print("❌ Failed to list tasks")
        return False


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="GhostWriter external task completion CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Mark task as completed by agent
  %(prog)s complete fix-typo-readme --by agent --notes "Fixed spelling error in README.md"
  
  # Mark task as failed
  %(prog)s complete deploy-feature --by ci --error "Deployment failed: timeout"
  
  # Update task status
  %(prog)s status fix-auth-bug --status attempted --by developer --notes "Started working on auth fix"
  
  # Get task status
  %(prog)s get fix-typo-readme
  
  # List all tasks
  %(prog)s list
        """
    )
    
    parser.add_argument(
        "--webhook-url",
        default="http://localhost:5555",
        help="GhostWriter webhook URL (default: %(default)s)"
    )
    
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Complete command
    complete_parser = subparsers.add_parser("complete", help="Mark a task as completed")
    complete_parser.add_argument("task_id", help="Task ID to mark as completed")
    complete_parser.add_argument("--by", dest="completed_by", required=True, 
                               help="Who/what completed the task (e.g., 'agent', 'ci', 'developer')")
    complete_parser.add_argument("--notes", help="Additional notes about completion")
    complete_parser.add_argument("--error", help="Error message (marks task as failed)")
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Update task status")
    status_parser.add_argument("task_id", help="Task ID to update")
    status_parser.add_argument("--status", required=True,
                              choices=["pending", "attempted", "completed", "skipped", "failed"],
                              help="New status for the task")
    status_parser.add_argument("--by", dest="completed_by", required=True,
                             help="Who/what is updating the status")
    status_parser.add_argument("--notes", help="Additional notes")
    status_parser.add_argument("--error", help="Error message (for failed status)")
    
    # Get command
    get_parser = subparsers.add_parser("get", help="Get task status")
    get_parser.add_argument("task_id", help="Task ID to get status for")
    
    # List command - parser variable not used but needed for side effects
    subparsers.add_parser("list", help="List all tasks")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    setup_logging(args.verbose)
    
    # Create client
    client = ExternalIntegrationClient(args.webhook_url)
    
    # Dispatch to appropriate handler
    try:
        if args.command == "complete":
            success = complete_task(
                client, args.task_id, args.completed_by, args.notes, args.error
            )
        elif args.command == "status":
            success = update_status(
                client, args.task_id, args.status, args.completed_by, args.notes, args.error
            )
        elif args.command == "get":
            success = get_task(client, args.task_id)
        elif args.command == "list":
            success = list_tasks(client)
        else:
            parser.print_help()
            return 1
        
        return 0 if success else 1
        
    except KeyboardInterrupt:
        print("\n❌ Operation cancelled by user")
        return 1
    except Exception as e:
        logger.error("Unexpected error: %s", e)
        print(f"❌ Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())