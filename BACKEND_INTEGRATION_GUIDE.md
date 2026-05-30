# GhostWriter Backend Integration Guide

This guide explains how to use GhostWriter's backend integration features to automatically update task metadata when tasks are completed by external processes, agents, or background systems.

## Overview

GhostWriter now provides multiple ways for external systems to notify when tasks are completed:

1. **Webhook API** - REST endpoints for programmatic notifications
2. **CLI Tool** - Command-line tool for manual/scripted notifications  
3. **Background Monitoring** - Automatic detection of completions via various sources
4. **Integration Libraries** - Python APIs for custom integrations

This ensures task metadata stays synchronized across all completion mechanisms, so completed tasks are no longer presented to users.

## Quick Start

### 1. Start Backend Services

```bash
# Start the webhook server and background monitoring
python start_backend_services.py

# Or using the installed script:
ghostwriter-backend
```

This starts:
- Webhook API server (default port 5555)
- Background monitoring service
- Automatic completion detection

### 2. Notify Task Completion

**Using CLI:**
```bash
# Mark task as completed
python ghostwriter_cli.py complete fix-typo-readme --by agent --notes "Fixed spelling errors"

# Mark task as failed
python ghostwriter_cli.py complete deploy-feature --by ci --error "Deployment timeout"

# Update task status
python ghostwriter_cli.py status auth-fix --status attempted --by developer
```

**Using HTTP API:**
```bash
# Mark task completed
curl -X POST http://localhost:5555/tasks/fix-typo-readme/complete \
  -H "Content-Type: application/json" \
  -d '{"completed_by": "agent", "notes": "Fixed spelling errors"}'

# Update task status  
curl -X POST http://localhost:5555/tasks/auth-fix/status \
  -H "Content-Type: application/json" \
  -d '{"status": "attempted", "completed_by": "developer"}'
```

**Using Python API:**
```python
from backend_integrations import notify_external_completion

# Simple notification
notify_external_completion("fix-typo-readme", "agent", "Fixed spelling errors")

# Advanced usage
from backend_integrations import ExternalIntegrationClient

client = ExternalIntegrationClient("http://localhost:5555")
client.notify_task_completed("task-id", "system", "completion notes")
```

## Architecture

### Components

1. **TaskCompletionWebhook** - Flask-based webhook server providing REST API
2. **TaskSyncMonitor** - Background service that monitors various completion sources
3. **ExternalIntegrationClient** - Python client for programmatic access
4. **Completion Checkers** - Pluggable functions to detect completions from different sources

### Integration Points

The system integrates with Box storage to:
- Load existing task metadata
- Update task status and completion information  
- Maintain synchronization across all completion mechanisms
- Preserve audit trail of who/what completed tasks

## API Reference

### Webhook Endpoints

#### Health Check
```
GET /health
```
Returns service health status.

#### List All Tasks
```
GET /tasks
```
Returns all tasks with their current metadata.

#### Get Task Status
```
GET /tasks/{task_id}
```
Returns specific task metadata.

#### Mark Task Complete
```
POST /tasks/{task_id}/complete
```
Marks task as completed or failed.

**Request Body:**
```json
{
  "completed_by": "system_name",
  "notes": "completion details",
  "error": "error message (optional, marks as failed)"
}
```

#### Update Task Status
```
POST /tasks/{task_id}/status  
```
Updates task status with granular control.

**Request Body:**
```json
{
  "status": "pending|attempted|completed|skipped|failed",
  "completed_by": "system_name", 
  "notes": "status details",
  "error": "error message (optional)"
}
```

### CLI Commands

#### Complete Task
```bash
ghostwriter-cli complete <task_id> --by <system> [--notes <text>] [--error <text>]
```

#### Update Status
```bash
ghostwriter-cli status <task_id> --status <status> --by <system> [--notes <text>]
```

#### Get Task
```bash
ghostwriter-cli get <task_id>
```

#### List Tasks
```bash
ghostwriter-cli list
```

## Background Monitoring

The background monitoring system automatically detects task completions from various sources:

### Built-in Completion Checkers

1. **Git Branch Checker** - Detects merged branches containing task IDs
2. **File Marker Checker** - Looks for completion marker files
3. **GitHub Issue Checker** - Monitors GitHub issues (if `GITHUB_TOKEN` set)

### Custom Completion Checkers

You can add custom completion detection logic:

```python
from backend_integrations import TaskSyncMonitor

def my_completion_checker(task_id: str, task_metadata: dict) -> dict | None:
    """Custom checker that returns completion info if task is done."""
    # Your detection logic here
    if task_completed_somehow(task_id):
        return {
            "completed_by": "my_system",
            "notes": "Detected completion via custom logic"
        }
    return None

# Add to monitor
monitor = TaskSyncMonitor(box_client)
monitor.add_completion_checker(my_completion_checker)
```

### Completion Detection Methods

1. **Git Integration**: Automatically detects when branches with task IDs are merged
2. **File Markers**: Looks for files like `.ghostwriter_completed_<task_id>`  
3. **GitHub Issues**: Monitors closed issues mentioning task IDs
4. **Custom Logic**: Add your own detection mechanisms

## Integration Examples

### CI/CD Pipeline Integration

Add to your deployment pipeline:

```bash
# After successful deployment
if [ $? -eq 0 ]; then
  ghostwriter-cli complete $TASK_ID --by "ci/cd" --notes "Deployed successfully to production"
else
  ghostwriter-cli complete $TASK_ID --by "ci/cd" --error "Deployment failed: $ERROR_MSG"  
fi
```

### AI Agent Integration

```python
# After agent completes a task
from backend_integrations import notify_external_completion

def agent_completed_task(task_id, success, details):
    if success:
        notify_external_completion(task_id, "ai_agent", f"Completed: {details}")
    else:
        notify_external_completion(task_id, "ai_agent", error=f"Failed: {details}")
```

### GitHub Webhook Integration

```python
from flask import Flask, request
from backend_integrations import ExternalIntegrationClient

app = Flask(__name__)
client = ExternalIntegrationClient("http://localhost:5555")

@app.route("/github-webhook", methods=["POST"])  
def github_webhook():
    payload = request.json
    
    if payload.get("action") == "closed" and "issue" in payload:
        issue = payload["issue"]
        # Extract task ID from issue title
        task_id = extract_task_id(issue["title"])
        if task_id:
            client.notify_task_completed(
                task_id=task_id,
                completed_by="github",
                notes=f"Completed via issue #{issue['number']}"
            )
    
    return "OK"
```

### Manual Developer Workflow

```bash
# Developer starts working on a task
ghostwriter-cli status implement-feature --status attempted --by alice --notes "Started implementation"

# Developer completes the task  
ghostwriter-cli complete implement-feature --by alice --notes "Feature implemented and tested"
```

## Configuration

### Environment Variables

- `BOX_TOKEN_A` or `BOX_CLIENT_ID_A`/`BOX_SECRET_A` - Box API credentials
- `BOX_ROOT_FOLDER_ID` - Box folder for metadata storage (default: "0")
- `GHOSTWRITER_WEBHOOK_PORT` - Webhook server port (default: 5555)
- `GHOSTWRITER_MONITOR_INTERVAL` - Background monitoring interval in seconds (default: 30)
- `GHOSTWRITER_WEBHOOK_URL` - URL for external systems to call (default: http://localhost:5555)
- `GITHUB_TOKEN` - GitHub API token for issue monitoring (optional)
- `GITHUB_REPO` - GitHub repository in "owner/repo" format (optional)

### Setup Example

```bash
export BOX_CLIENT_ID_A="your_box_client_id"
export BOX_SECRET_A="your_box_client_secret"  
export GHOSTWRITER_WEBHOOK_PORT=8080
export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"
export GITHUB_REPO="myorg/myrepo"

# Start services
ghostwriter-backend
```

## Best Practices

### Task ID Management
- Use consistent, URL-safe task IDs (lowercase, hyphens)
- Include task IDs in branch names, commit messages, issue titles
- Use descriptive task IDs that indicate the work being done

### Error Handling
- Always include meaningful completion notes
- Use error fields for failed tasks to provide debugging information
- Implement retry logic for webhook calls in unreliable networks

### Security
- Run webhook server behind reverse proxy in production
- Use authentication if exposing publicly
- Validate task IDs to prevent unauthorized updates

### Monitoring
- Check webhook server health regularly
- Monitor background sync for errors
- Set up alerts for failed task notifications

## Troubleshooting

### Common Issues

**Webhook server won't start**
- Check if port is already in use
- Verify Box credentials are configured
- Check firewall settings

**Task updates not working**  
- Verify webhook URL is accessible
- Check Box API credentials and permissions
- Ensure task IDs match exactly

**Background monitoring not working**
- Check if monitoring service is running
- Verify completion checkers are configured
- Check file permissions for git/file operations

### Debug Commands

```bash
# Test webhook connectivity
curl http://localhost:5555/health

# List current tasks
ghostwriter-cli list

# Check specific task status
ghostwriter-cli get <task_id>

# Test completion notification
ghostwriter-cli complete test-task --by debug --notes "Testing integration"
```

### Logs

The backend services provide detailed logging:

```bash
# Start with verbose logging
LOGLEVEL=DEBUG ghostwriter-backend

# Check logs for integration issues
tail -f ghostwriter.log | grep -E "(webhook|sync|backend)"
```

## Migration Guide

If upgrading from a previous version:

1. **Backup existing metadata**: Export task data before upgrading
2. **Update configuration**: Add new environment variables as needed
3. **Test integrations**: Verify external systems can connect to new webhook API
4. **Update scripts**: Replace any custom notification scripts with new CLI tool

## Examples Repository

See `example_integrations.py` for complete working examples of:
- CI/CD pipeline integration
- AI agent integration  
- Manual developer workflows
- GitHub webhook integration
- Batch status synchronization
- Custom completion checkers

Run examples:
```bash
python example_integrations.py
```

This provides backend support to automatically update Box storage metadata when tasks are completed by any external process, ensuring the metadata stays synchronized across all completion mechanisms.