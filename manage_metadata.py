#!/usr/bin/env python3
"""Utility script for managing GhostWriter task metadata."""

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from box_client import BoxClient
from models import TaskStatus
import os


def list_tasks(box: BoxClient, root_folder_id: str = "0") -> None:
    """List all tasks and their current status."""
    metadata_dict = box.load_task_metadata(root_folder_id)
    
    if not metadata_dict:
        print("No task metadata found.")
        return
    
    print(f"Found {len(metadata_dict)} tasks:")
    print("-" * 80)
    
    for task_id, metadata in sorted(metadata_dict.items()):
        status_icon = {
            TaskStatus.COMPLETED: "✅",
            TaskStatus.SKIPPED: "⏭️", 
            TaskStatus.FAILED: "❌",
            TaskStatus.ATTEMPTED: "🔄",
            TaskStatus.PENDING: "⏸️"
        }.get(metadata.status, "❓")
        
        print(f"{status_icon} {task_id}")
        print(f"   Status: {metadata.status.value}")
        print(f"   Last Updated: {metadata.last_updated.strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"   Attempts: {metadata.attempts}")
        
        if metadata.completed_by:
            print(f"   Completed By: {metadata.completed_by}")
        if metadata.last_error:
            print(f"   Last Error: {metadata.last_error}")
        if metadata.notes:
            print(f"   Notes: {metadata.notes}")
        print()


def mark_task_completed(box: BoxClient, task_id: str, root_folder_id: str = "0") -> None:
    """Mark a task as completed."""
    try:
        box.update_task_status(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            root_folder_id=root_folder_id,
            completed_by="manual",
            notes="Manually marked as completed via metadata utility",
        )
        print(f"✅ Marked task '{task_id}' as completed.")
    except Exception as e:
        print(f"❌ Error updating task: {e}")
        sys.exit(1)


def mark_task_skipped(box: BoxClient, task_id: str, root_folder_id: str = "0") -> None:
    """Mark a task as skipped."""
    try:
        box.update_task_status(
            task_id=task_id,
            status=TaskStatus.SKIPPED,
            root_folder_id=root_folder_id,
            completed_by="manual",
            notes="Manually marked as skipped via metadata utility",
        )
        print(f"⏭️  Marked task '{task_id}' as skipped.")
    except Exception as e:
        print(f"❌ Error updating task: {e}")
        sys.exit(1)


def reset_task(box: BoxClient, task_id: str, root_folder_id: str = "0") -> None:
    """Reset a task to pending status."""
    try:
        box.update_task_status(
            task_id=task_id,
            status=TaskStatus.PENDING,
            root_folder_id=root_folder_id,
            notes="Reset to pending via metadata utility",
        )
        print(f"🔄 Reset task '{task_id}' to pending.")
    except Exception as e:
        print(f"❌ Error updating task: {e}")
        sys.exit(1)


def clear_metadata(box: BoxClient, root_folder_id: str = "0") -> None:
    """Clear all task metadata (with confirmation)."""
    metadata_dict = box.load_task_metadata(root_folder_id)
    
    if not metadata_dict:
        print("No task metadata found to clear.")
        return
    
    print(f"This will clear metadata for {len(metadata_dict)} tasks:")
    for task_id in sorted(metadata_dict.keys()):
        print(f"  - {task_id}")
    
    confirm = input("\nAre you sure? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("Cancelled.")
        return
    
    try:
        # Save empty metadata dict
        box.save_task_metadata({}, root_folder_id)
        print("✅ All task metadata cleared.")
    except Exception as e:
        print(f"❌ Error clearing metadata: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Manage GhostWriter task metadata")
    parser.add_argument("--box-token", help="Box developer token (or set BOX_TOKEN_A env var)")
    parser.add_argument("--box-client-id", help="Box client ID (or set BOX_CLIENT_ID_A env var)")  
    parser.add_argument("--box-client-secret", help="Box client secret (or set BOX_SECRET_A env var)")
    parser.add_argument("--root-folder", default="0", help="Box root folder ID (default: 0)")
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # List tasks
    subparsers.add_parser("list", help="List all tasks and their status")
    
    # Mark completed
    complete_parser = subparsers.add_parser("complete", help="Mark a task as completed")
    complete_parser.add_argument("task_id", help="Task ID to mark as completed")
    
    # Mark skipped
    skip_parser = subparsers.add_parser("skip", help="Mark a task as skipped")
    skip_parser.add_argument("task_id", help="Task ID to mark as skipped")
    
    # Reset task
    reset_parser = subparsers.add_parser("reset", help="Reset a task to pending")
    reset_parser.add_argument("task_id", help="Task ID to reset")
    
    # Clear all metadata
    subparsers.add_parser("clear", help="Clear all task metadata")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Initialize Box client
    box_token = args.box_token or os.environ.get("BOX_TOKEN_A")
    box_client_id = args.box_client_id or os.environ.get("BOX_CLIENT_ID_A")
    box_client_secret = args.box_client_secret or os.environ.get("BOX_SECRET_A")
    
    try:
        box = BoxClient(
            dev_token=box_token,
            client_id=box_client_id,
            client_secret=box_client_secret,
        )
    except Exception as e:
        print(f"❌ Failed to initialize Box client: {e}")
        print("Make sure to provide Box credentials via arguments or environment variables.")
        sys.exit(1)
    
    # Execute command
    try:
        if args.command == "list":
            list_tasks(box, args.root_folder)
        elif args.command == "complete":
            mark_task_completed(box, args.task_id, args.root_folder)
        elif args.command == "skip":
            mark_task_skipped(box, args.task_id, args.root_folder)
        elif args.command == "reset":
            reset_task(box, args.task_id, args.root_folder)
        elif args.command == "clear":
            clear_metadata(box, args.root_folder)
    except KeyboardInterrupt:
        print("\n❌ Cancelled by user")
        sys.exit(1)


if __name__ == "__main__":
    main()