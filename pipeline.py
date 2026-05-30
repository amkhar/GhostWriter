"""Pipeline orchestrator — coordinates all GhostWriter stages."""
from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone

from strands import Agent
from strands.models import BedrockModel
import os

from box_client import BoxClient, _RECURRENCE_PROMPT
from models import (
    IngestedFile,
    NeglectedTask,
    PipelineConfig,
    RunReport,
    Task,
    TaskClassification,
    TaskMetadata,
    TaskStatus,
    WorkerResult,
)

logger = logging.getLogger("ghostwriter.pipeline")

_AUTO_DOABLE_CATEGORIES = [
    "fix typo",
    "update doc",
    "update readme",
    "add missing log line",
    "add null check",
    "add empty check",
    "bump dependency",
    "add unit test",
    "rename for consistency",
]

_UNSAFE_KEYWORDS = [
    "auth", "authentication", "payment", "billing", "database migration",
    "infrastructure", "delete", "drop table", "remove file", "rm -rf",
]

_ENHANCED_CLASSIFY_PROMPT = """You are a code-change safety classifier with codebase context.

Given a neglected task AND relevant code from the repo, provide a detailed classification decision.

Respond with JSON only in this exact format:
{{
  "auto_doable": true|false,
  "category": "<category if auto_doable>",
  "reasoning": "<clear 1-2 sentence explanation>",
  "decision_factors": ["<factor1>", "<factor2>", ...],
  "code_analysis": "<what you found in the codebase>",
  "risk_assessment": "<risks identified if not auto_doable>",
  "suggested_approach": "<how user could make it auto_doable if not auto_doable>"
}}

Classification guidelines:
- Set auto_doable=true for changes that are small, localized (1-3 files, <50 lines), and low risk
- Safe categories: fix typo, update doc/README, add log line, add null check, bump dep, add unit test, rename, add config, fix lint, update error msg, refactor small function, change upload behavior, add a flag/option, update a prompt string
- Set auto_doable=false for: auth/payments/security, database migrations, architectural changes, ambiguous requirements

Be GENEROUS. If the code shows it is a straightforward change, approve it.

Task title: {title}
Task description: {description}

Relevant code from the repository:
{code_context}
"""


def run_pipeline(config: PipelineConfig) -> RunReport:
    run_id = str(uuid.uuid4())[:8]
    logger.info("[GhostWriter][pipeline] Starting run %s", run_id)

    # Import UI (safe to call even if not in a TTY — functions are no-ops on non-TTY)
    try:
        from ui import (show_stage, show_upload, show_neglected_tasks,
                        show_classification, show_worker_result)
        has_ui = True
    except ImportError:
        has_ui = False

    box = BoxClient(
        dev_token=os.environ.get("BOX_TOKEN_A") or config.box_dev_token,
        client_id=os.environ.get("BOX_CLIENT_ID_A"),
        client_secret=os.environ.get("BOX_SECRET_A"),
    )

    # Stage 1: Ingest
    if has_ui:
        show_stage(1, "Ingest", "Uploading transcripts to Box")
    logger.info("[GhostWriter][pipeline] Stage 1: Ingest")
    ingested = ingest(config, box)
    if has_ui:
        for f in ingested:
            show_upload(f.filename, f.box_file_id)
    if not ingested:
        logger.warning("[GhostWriter][pipeline] No transcripts ingested")

    # Stage 2: Extract
    if has_ui:
        show_stage(2, "Extract", "Box AI extracting tasks from each transcript")
    logger.info("[GhostWriter][pipeline] Stage 2: Extract")
    tasks = extract(ingested, box)
    logger.info("[GhostWriter][pipeline] Extracted %d tasks", len(tasks))

    # Stage 3: Recurrence detection
    if has_ui:
        show_stage(3, "Recurrence", "Box AI identifying neglected recurring tasks")
    logger.info("[GhostWriter][pipeline] Stage 3: Recurrence detection")
    file_ids = [f.box_file_id for f in ingested]
    neglected = detect_recurrence(file_ids, box)
    logger.info("[GhostWriter][pipeline] Found %d neglected tasks", len(neglected))

    # Stage 3.5: Load metadata and filter out already handled tasks
    if has_ui:
        show_stage(3.5, "Metadata", "Loading task history and filtering completed tasks")
    logger.info("[GhostWriter][pipeline] Stage 3.5: Load metadata")
    neglected = load_and_filter_metadata(neglected, box, config)
    pending_tasks = [t for t in neglected if not t.metadata or t.metadata.status == TaskStatus.PENDING]
    logger.info("[GhostWriter][pipeline] %d tasks pending after metadata filtering", len(pending_tasks))

    if has_ui and neglected:
        show_neglected_tasks(neglected)

    if not pending_tasks and not config.dry_run:
        logger.info("[GhostWriter][pipeline] No pending tasks — producing report with metadata")
        report = build_report(neglected, [], config.dry_run, run_id)
        _upload_report(report, box, config)
        return report

    if not neglected:
        logger.info("[GhostWriter][pipeline] No neglected tasks — producing empty report")
        report = build_report([], [], config.dry_run, run_id)
        _upload_report(report, box, config)
        return report

    # Stage 4: Classify (only for pending tasks)
    if has_ui:
        show_stage(4, "Classify", "Bedrock LLM deciding which tasks are safe to auto-implement")
    logger.info("[GhostWriter][pipeline] Stage 4: Classify")
    neglected = classify(neglected, config.bedrock_model_id, config.repo)
    if has_ui:
        for t in neglected:
            show_classification(t)

    # Interactive override: let user force-approve skipped tasks with guidance
    skipped = [t for t in neglected if not t.auto_doable and 
               (not t.metadata or t.metadata.status == TaskStatus.PENDING)]
    if skipped and not config.dry_run and sys.stdin.isatty():
        neglected = _prompt_user_overrides(neglected, box, config)

    if config.dry_run:
        logger.info("[GhostWriter][pipeline] Dry run — stopping after classify")
        report = build_report(neglected, [], True, run_id)
        _upload_report(report, box, config)
        return report

    # Filter to only auto-doable pending tasks for implementation
    implementable = [t for t in neglected if t.auto_doable and 
                    (not t.metadata or t.metadata.status == TaskStatus.PENDING)]
    
    if not implementable:
        logger.info("[GhostWriter][pipeline] No implementable tasks — producing report")
        report = build_report(neglected, [], False, run_id)
        _upload_report(report, box, config)
        return report

    # Stage 5-6: Orchestrate
    if has_ui:
        show_stage(5, "Implement", "Strands agents making code changes")
    logger.info("[GhostWriter][pipeline] Stage 5-6: Orchestrate")
    from agents.orchestrator import orchestrate
    results, _ = orchestrate(implementable, config.repo, config.bedrock_model_id, run_id)
    if has_ui:
        for r in results:
            show_worker_result(r)

    # Update metadata with results
    update_metadata_with_results(results, box, config)

    # Stage 7: Report
    if has_ui:
        show_stage(7, "Report", "Building and uploading run report")
    logger.info("[GhostWriter][pipeline] Stage 7: Build report")
    report = build_report(neglected, results, False, run_id)
    _upload_report(report, box, config)
    return report


# ------------------------------------------------------------------ #
# Stage functions
# ------------------------------------------------------------------ #

def ingest(config: PipelineConfig, box: BoxClient) -> list[IngestedFile]:
    """Upload transcripts to Box; return list of IngestedFile."""
    folder_id = box.ensure_folder("transcripts", config.box_root_folder_id)
    ingested: list[IngestedFile] = []

    if config.paste_content:
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, prefix="paste_") as f:
            f.write(config.paste_content)
            tmp_path = Path(f.name)
        try:
            fid = box.upload_transcript(tmp_path, folder_id)
            ingested.append(IngestedFile(filename=tmp_path.name, box_file_id=fid))
        except Exception as e:
            logger.error("[GhostWriter][ingest] Failed to upload paste content: %s", e)
        finally:
            os.unlink(tmp_path)
        return ingested

    if config.transcripts_dir:
        for path in sorted(config.transcripts_dir.iterdir()):
            if path.suffix in (".txt", ".md"):
                try:
                    fid = box.upload_transcript(path, folder_id)
                    ingested.append(IngestedFile(filename=path.name, box_file_id=fid))
                    logger.info("[GhostWriter][ingest] Ingested %s → %s", path.name, fid)
                except Exception as e:
                    logger.error("[GhostWriter][ingest] Failed %s: %s", path.name, e)

    return ingested


def extract(ingested: list[IngestedFile], box: BoxClient) -> list[Task]:
    """Call Box AI Extract per file; return all Task objects."""
    all_tasks: list[Task] = []

    for f in ingested:
        try:
            raw = box.ai_extract(f.box_file_id)
            tasks = BoxClient.parse_tasks(raw, f.filename)
            all_tasks.extend(tasks)
            logger.info("[GhostWriter][extract] %s → %d tasks", f.filename, len(tasks))
        except Exception as e:
            logger.error("[GhostWriter][extract] Failed for %s: %s", f.filename, e)

    return all_tasks


def detect_recurrence(file_ids: list[str], box: BoxClient) -> list[NeglectedTask]:
    """Call Box AI Ask multi-file; return NeglectedTask list."""
    if not file_ids:
        return []
    try:
        answer = box.ai_ask_multi(file_ids, _RECURRENCE_PROMPT)
        logger.info("[GhostWriter][recurrence] Box AI answer: %s", answer[:200])
        raw_list = BoxClient.parse_neglected(answer)
    except Exception as e:
        logger.error("[GhostWriter][recurrence] Box AI Ask failed: %s", e)
        raise

    neglected: list[NeglectedTask] = []
    for item in raw_list:
        title = item.get("title", "unknown")
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
        neglected.append(
            NeglectedTask(
                id=slug,
                title=title,
                description=item.get("description", title),
                reason=item.get("reason", "recurring across meetings"),
            )
        )
    return neglected


def load_and_filter_metadata(neglected: list[NeglectedTask], box: BoxClient, 
                            config: PipelineConfig) -> list[NeglectedTask]:
    """Load task metadata and attach it to neglected tasks."""
    try:
        metadata_dict = box.load_task_metadata(config.box_root_folder_id)
        
        for task in neglected:
            if task.id in metadata_dict:
                task.metadata = metadata_dict[task.id]
                logger.info("[GhostWriter][metadata] Task %s has status: %s", 
                           task.id, task.metadata.status.value)
            else:
                # Create new metadata entry for tracking
                task.metadata = TaskMetadata(
                    task_id=task.id,
                    status=TaskStatus.PENDING,
                    last_updated=datetime.now(timezone.utc),
                )
                
        return neglected
        
    except Exception as e:
        logger.warning("[GhostWriter][metadata] Failed to load metadata: %s", e)
        # Continue without metadata
        for task in neglected:
            task.metadata = TaskMetadata(
                task_id=task.id,
                status=TaskStatus.PENDING,
                last_updated=datetime.now(timezone.utc),
            )
        return neglected


def classify(neglected: list[NeglectedTask], model_id: str, repo: Path = None) -> list[NeglectedTask]:
    """Use Bedrock LLM to classify each NeglectedTask with enhanced codebase research."""
    from agents.worker import AGENT_BACKEND

    # Only classify tasks that are pending
    pending_tasks = [t for t in neglected if not t.metadata or t.metadata.status == TaskStatus.PENDING]
    
    if not pending_tasks:
        logger.info("[GhostWriter][classify] No pending tasks to classify")
        return neglected

    # If using an external agent (kiro/claude-code), let IT do the research + classification
    if AGENT_BACKEND in ("kiro", "claude-code") and repo:
        return _classify_via_agent(neglected, repo)

    aws_region = os.environ.get("AWS_REGION", "us-east-1")
    model = BedrockModel(model_id=model_id, region_name=aws_region)
    classifier = Agent(model=model, system_prompt="You are a JSON-only responder.")

    for task in neglected:
        # Skip tasks that are not pending
        if task.metadata and task.metadata.status != TaskStatus.PENDING:
            logger.info("[GhostWriter][classify][%s] Skipping non-pending task (status: %s)", 
                       task.id, task.metadata.status.value)
            continue
            
        # Fast-path: unsafe keywords → false
        combined = (task.title + " " + task.description).lower()
        unsafe_found = [kw for kw in _UNSAFE_KEYWORDS if kw in combined]
        if unsafe_found:
            task.auto_doable = False
            task.classification_reasoning = f"Contains unsafe keyword: {unsafe_found[0]}"
            task.classification = TaskClassification(
                auto_doable=False,
                reasoning=f"Contains security/risk keyword: {unsafe_found[0]}",
                decision_factors=[f"Unsafe keyword detected: '{unsafe_found[0]}'", "High-risk operation"],
                risk_assessment="Security-sensitive or destructive operation",
                suggested_approach="Manual review required for security/infrastructure changes"
            )
            logger.info("[GhostWriter][classify][%s] auto_doable=False (unsafe keyword: %s)", task.id, unsafe_found[0])
            continue

        code_context = _research_codebase(task, repo) if repo else "(no repo provided)"
        prompt = _ENHANCED_CLASSIFY_PROMPT.format(title=task.title, description=task.description, code_context=code_context)
        
        try:
            response = classifier(prompt)
            text = str(response).strip()
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                data = json.loads(match.group())
                
                # Create enhanced classification
                task.classification = TaskClassification(
                    auto_doable=bool(data.get("auto_doable", False)),
                    category=data.get("category"),
                    reasoning=data.get("reasoning", "No reasoning provided"),
                    decision_factors=data.get("decision_factors", []),
                    code_analysis=data.get("code_analysis"),
                    risk_assessment=data.get("risk_assessment"),
                    suggested_approach=data.get("suggested_approach")
                )
                
                # Set legacy fields for backward compatibility
                task.auto_doable = task.classification.auto_doable
                task.auto_doable_category = task.classification.category
                task.classification_reasoning = task.classification.reasoning
            else:
                task.auto_doable = False
                task.classification_reasoning = "Could not parse classifier response"
                task.classification = TaskClassification(
                    auto_doable=False,
                    reasoning="Could not parse classifier response",
                    decision_factors=["Malformed classifier output"],
                    risk_assessment="Unknown due to classification failure",
                    suggested_approach="Re-run classification or provide manual guidance"
                )
        except Exception as e:
            logger.error("[GhostWriter][classify][%s] Bedrock error: %s", task.id, e)
            task.auto_doable = False
            task.classification_reasoning = f"Classification failed: {e}"
            task.classification = TaskClassification(
                auto_doable=False,
                reasoning=f"Classification system error: {str(e)}",
                decision_factors=["System error during classification"],
                risk_assessment="Cannot assess risk due to system failure",
                suggested_approach="Check system configuration and retry, or provide manual guidance"
            )

        logger.info(
            "[GhostWriter][classify][%s] auto_doable=%s category=%s reasoning=%s",
            task.id, task.auto_doable, task.auto_doable_category, task.classification_reasoning,
        )

    return neglected


def _classify_via_agent(neglected: list[NeglectedTask], repo: Path) -> list[NeglectedTask]:
    """Use kiro-cli or claude-code to research the codebase and classify tasks."""
    import subprocess
    from agents.worker import AGENT_BACKEND

    # Only classify pending tasks
    pending_tasks = [t for t in neglected if not t.metadata or t.metadata.status == TaskStatus.PENDING]
    
    if not pending_tasks:
        return neglected
    
    tasks_json = json.dumps([{"id": t.id, "title": t.title, "description": t.description} for t in pending_tasks])

    prompt = (
        f"You are classifying tasks for an auto-implementation tool. "
        f"Research this codebase to determine which tasks are safe to auto-implement.\n\n"
        f"Tasks to classify:\n{tasks_json}\n\n"
        f"For EACH task, search the codebase to find the relevant files and understand the scope.\n"
        f"A task is auto_doable if it's a localized change (1-3 files, <50 lines, no auth/payment/migration).\n\n"
        f"Respond with ONLY a JSON array in this format:\n"
        f'[{{"id": "...", "auto_doable": true/false, "category": "...", "reasoning": "...", '
        f'"decision_factors": [...], "code_analysis": "...", "risk_assessment": "...", "suggested_approach": "..."}}]'
    )

    if AGENT_BACKEND == "kiro":
        cmd = ["kiro-cli", "chat", "--trust-all-tools", "--no-interactive", prompt]
    else:
        cmd = ["claude", "-p", prompt, "--allowedTools", "Edit,Write,Read,Bash"]

    logger.info("[GhostWriter][classify] Using %s agent for research + classification", AGENT_BACKEND)
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(repo), timeout=300)

    # Parse JSON from output
    output = r.stdout
    match = re.search(r"\[.*\]", output, re.DOTALL)
    if match:
        try:
            results = json.loads(match.group())
            results_map = {item["id"]: item for item in results}
            for task in pending_tasks:
                if task.id in results_map:
                    data = results_map[task.id]
                    
                    # Create enhanced classification
                    task.classification = TaskClassification(
                        auto_doable=bool(data.get("auto_doable", False)),
                        category=data.get("category"),
                        reasoning=data.get("reasoning", "Agent classification"),
                        decision_factors=data.get("decision_factors", []),
                        code_analysis=data.get("code_analysis"),
                        risk_assessment=data.get("risk_assessment"),
                        suggested_approach=data.get("suggested_approach")
                    )
                    
                    # Set legacy fields
                    task.auto_doable = task.classification.auto_doable
                    task.auto_doable_category = task.classification.category
                    task.classification_reasoning = task.classification.reasoning
                    
                logger.info("[GhostWriter][classify][%s] auto_doable=%s reasoning=%s",
                            task.id, task.auto_doable, task.classification_reasoning)
            return neglected
        except json.JSONDecodeError:
            pass

    # Fallback: if agent didn't return parseable JSON, mark pending tasks as auto_doable
    logger.warning("[GhostWriter][classify] Could not parse agent output, defaulting pending tasks to auto_doable")
    for task in pending_tasks:
        task.auto_doable = True
        task.auto_doable_category = "agent-researched"
        task.classification_reasoning = "Agent researched codebase but output wasn't parseable JSON; defaulting to approve"
        task.classification = TaskClassification(
            auto_doable=True,
            category="agent-researched",
            reasoning="Agent researched codebase but output format was invalid; defaulting to approve",
            decision_factors=["Agent research completed", "Output format invalid but defaulting to safe"],
            code_analysis="Agent performed codebase research but results not parseable",
            suggested_approach="Agent already performed research and deemed safe"
        )
    return neglected


def update_metadata_with_results(results: list[WorkerResult], box: BoxClient, config: PipelineConfig) -> None:
    """Update task metadata based on worker results."""
    try:
        for result in results:
            status = TaskStatus.COMPLETED if result.success else TaskStatus.FAILED
            box.update_task_status(
                task_id=result.task_id,
                status=status,
                root_folder_id=config.box_root_folder_id,
                error=result.error if not result.success else None,
                completed_by="auto",
                notes=f"Auto-implementation: {result.summary}",
            )
            logger.info("[GhostWriter][metadata] Updated task %s to status %s", 
                       result.task_id, status.value)
    except Exception as e:
        logger.error("[GhostWriter][metadata] Failed to update metadata with results: %s", e)


def _research_codebase(task: NeglectedTask, repo: Path) -> str:
    """Grep the repo for code relevant to the task. Returns compact context for the classifier."""
    import subprocess

    keywords = _extract_keywords(task.title + " " + task.description)
    snippets: list[str] = []

    for kw in keywords[:5]:
        r = subprocess.run(
            ["grep", "-rn", "--include=*.py", "--include=*.ts", "--include=*.js",
             "--include=*.md", "--include=*.yaml", "--include=*.toml",
             "-i", "-l", kw, str(repo)],
            capture_output=True, text=True, timeout=10,
        )
        if r.stdout.strip():
            for f in r.stdout.strip().split("\n")[:3]:
                r2 = subprocess.run(
                    ["grep", "-n", "-i", "-B1", "-A3", kw, f],
                    capture_output=True, text=True, timeout=5,
                )
                if r2.stdout.strip():
                    rel_path = f.replace(str(repo) + "/", "")
                    snippets.append(f"--- {rel_path} ---\n{r2.stdout.strip()[:500]}")

    if not snippets:
        return "(no relevant code found in repo)"

    seen = set()
    unique = [s for s in snippets if s not in seen and not seen.add(s)]
    return "\n\n".join(unique[:8])[:3000]


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful search keywords from task text."""
    stop = {"the", "a", "an", "is", "are", "was", "were", "be", "been", "to", "of", "in",
            "for", "on", "with", "at", "by", "from", "it", "this", "that", "not", "but",
            "and", "or", "if", "we", "should", "can", "will", "do", "has", "have", "had",
            "just", "also", "still", "instead", "when", "then", "so", "as", "all", "any"}
    words = re.findall(r'[a-zA-Z_][a-zA-Z0-9_]*', text)
    seen = set()
    return [w for w in words if w.lower() not in stop and len(w) > 2
            and w.lower() not in seen and not seen.add(w.lower())]


def _prompt_user_overrides(neglected: list[NeglectedTask], box: BoxClient, config: PipelineConfig) -> list[NeglectedTask]:
    """Interactively ask user if they want to force-approve skipped tasks."""
    from rich.console import Console
    from rich.panel import Panel
    from feedback import record_override

    console = Console()
    skipped = [t for t in neglected if not t.auto_doable and 
               (not t.metadata or t.metadata.status == TaskStatus.PENDING)]

    console.print()
    console.print(Panel(
        f"[yellow]{len(skipped)} task(s) were skipped by the classifier.[/yellow]\n"
        "[dim]You can provide implementation details to force any task through.[/dim]",
        title="[bold]💡 Override Skipped Tasks?[/bold]",
        border_style="yellow",
    ))

    for task in skipped:
        console.print(f"\n  [bold]{task.title}[/bold]")
        if task.classification:
            console.print(f"  [dim]Reason skipped: {task.classification.reasoning}[/dim]")
            if task.classification.suggested_approach:
                console.print(f"  [dim]Suggestion: {task.classification.suggested_approach}[/dim]")
        else:
            console.print(f"  [dim]Reason skipped: {task.classification_reasoning}[/dim]")
        console.print(f"  [dim]Description: {task.description[:100]}[/dim]")
        
        answer = console.input("  [yellow]Provide implementation details (or Enter to skip):[/yellow] ").strip()

        if answer:
            task.auto_doable = True
            task.auto_doable_category = "user-directed"
            task.user_guidance = answer
            task.classification_reasoning = f"User override: {answer[:80]}"
            
            # Update classification if it exists
            if task.classification:
                task.classification.auto_doable = True
                task.classification.category = "user-directed"
                task.classification.reasoning = f"User override: {answer}"
                task.classification.decision_factors = ["User provided implementation guidance", "Manual override"]
            
            record_override(
                task_id=task.id,
                title=task.title,
                description=task.description,
                user_guidance=answer,
                classification_reasoning=task.classification_reasoning,
            )
            console.print("  [green]✅ Forced auto-doable with your guidance[/green]")
        else:
            # Mark as manually skipped in metadata
            try:
                box.update_task_status(
                    task_id=task.id,
                    status=TaskStatus.SKIPPED,
                    root_folder_id=config.box_root_folder_id,
                    completed_by="manual",
                    notes="User chose to skip during interactive prompt",
                )
                if task.metadata:
                    task.metadata.status = TaskStatus.SKIPPED
                console.print("  [dim]⏭️  Marked as skipped[/dim]")
            except Exception as e:
                logger.warning("[GhostWriter][metadata] Failed to update skipped status: %s", e)

    return neglected


def build_report(
    neglected: list[NeglectedTask],
    results: list[WorkerResult],
    dry_run: bool,
    run_id: str,
) -> RunReport:
    return RunReport(
        run_id=run_id,
        dry_run=dry_run,
        neglected_tasks=neglected,
        worker_results=results,
    )


def _upload_report(report: RunReport, box: BoxClient, config: PipelineConfig) -> None:
    try:
        folder_id = box.ensure_folder("reports", config.box_root_folder_id)
        fid = box.upload_report(report.to_markdown(), folder_id, f"ghostwriter_report_{report.run_id}.md")
        report.report_box_file_id = fid
        logger.info("[GhostWriter][report] Uploaded report to Box: %s", fid)
    except Exception as e:
        logger.error("[GhostWriter][report] Box upload failed: %s", e)
        raise