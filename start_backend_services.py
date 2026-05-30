"""Startup script for GhostWriter backend integration services."""
import logging
import os
import signal
import sys
import time

from box_client import BoxClient
from backend_integrations import setup_backend_integrations

logger = logging.getLogger("ghostwriter.backend_server")


def setup_logging():
    """Setup logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    logger.info("Received signal %d, shutting down backend services...", signum)
    sys.exit(0)


def main():
    """Start GhostWriter backend integration services."""
    setup_logging()
    
    # Handle shutdown signals
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("Starting GhostWriter Backend Integration Services")
    
    # Setup Box client
    try:
        box_client = BoxClient(
            dev_token=os.environ.get("BOX_TOKEN_A"),
            client_id=os.environ.get("BOX_CLIENT_ID_A"),
            client_secret=os.environ.get("BOX_SECRET_A"),
        )
    except Exception as e:
        logger.error("Failed to initialize Box client: %s", e)
        logger.error("Make sure BOX_TOKEN_A or (BOX_CLIENT_ID_A + BOX_SECRET_A) are set")
        return 1
    
    # Configuration
    root_folder_id = os.environ.get("BOX_ROOT_FOLDER_ID", "0")
    webhook_port = int(os.environ.get("GHOSTWRITER_WEBHOOK_PORT", "5555"))
    monitor_interval = int(os.environ.get("GHOSTWRITER_MONITOR_INTERVAL", "30"))
    
    logger.info("Configuration:")
    logger.info("  Box root folder ID: %s", root_folder_id)
    logger.info("  Webhook port: %d", webhook_port)
    logger.info("  Monitor interval: %d seconds", monitor_interval)
    
    try:
        # Setup backend integrations
        webhook_server, sync_monitor = setup_backend_integrations(
            box_client=box_client,
            root_folder_id=root_folder_id,
            webhook_port=webhook_port,
            monitor_interval=monitor_interval
        )
        
        logger.info("✅ Backend services started successfully")
        logger.info("Webhook API endpoints:")
        logger.info("  GET  /health                    - Health check")
        logger.info("  GET  /tasks                     - List all tasks")
        logger.info("  GET  /tasks/<task_id>           - Get task status")
        logger.info("  POST /tasks/<task_id>/complete  - Mark task as completed")
        logger.info("  POST /tasks/<task_id>/status    - Update task status")
        logger.info("")
        logger.info("Monitoring features enabled:")
        logger.info("  - Git branch completion detection")
        logger.info("  - File marker completion detection") 
        logger.info("  - GitHub issue completion detection (if GITHUB_TOKEN set)")
        logger.info("")
        logger.info("External processes can notify completions via:")
        logger.info("  python ghostwriter_cli.py complete <task_id> --by <system>")
        logger.info("  curl -X POST http://localhost:%d/tasks/<task_id>/complete \\", webhook_port)
        logger.info("       -H 'Content-Type: application/json' \\")
        logger.info("       -d '{\"completed_by\": \"<system>\", \"notes\": \"<details>\"}'")
        
        # Keep running until interrupted
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        
    except Exception as e:
        logger.error("Failed to start backend services: %s", e)
        return 1
    
    finally:
        logger.info("Stopping backend services...")
        try:
            if 'sync_monitor' in locals():
                sync_monitor.stop_monitoring()
        except Exception as e:
            logger.error("Error stopping sync monitor: %s", e)
    
    logger.info("GhostWriter backend services stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())