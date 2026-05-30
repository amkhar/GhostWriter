"""Pipeline orchestrator — coordinates all GhostWriter stages."""
from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from pathlib import Path

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

_CLASSIFY_PROMPT = """You are a code-change safety classifier with codebase context.

Given a neglected task AND relevant code from the repo, decide if it is safe to auto-implement.

Set auto_doable=true for changes that are:
- Small and localized (touches 1-3 files, <50 lines)
- Low risk: fix typo, update doc/README, add log line, add null check, bump dep,
  add unit test, rename, add config, fix lint, update error msg, refactor small function,
  change upload behavior, add a flag/option, update a prompt string
- Clear from the code context what needs to change

Set auto_doable=false ONLY for:
- Auth, payments, database migrations, security-critical code
- Requires architectural decisions or multi-service coordination
- Ambiguous with no clear path even after seeing the code

Be GENEROUS. If the code shows it is a straightforward change, approve it.

Respond with JSON only:
{{"auto_doable": true|false, "category": "<category>", "reasoning": "<1 sentence>", "files_to_change": ["<file1>"]}}

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
                        show_classification, show_worker_start, show_worker_result,
                        show_push, show_report_summary)
        has_ui = True
    except ImportError:
        has_ui = False

    box = BoxClient(
        dev_token=os.environ.get("BOX_TOKEN_A") or config.box_dev_token,
        client_id=os.environ.get("BOX_CLIENT_ID_A"),
        client_secret=os.environ.get("BOX_SECRET_A"),
    )

    # Stage 1: Ingest
    if has_ui: show_stage(1, "Ingest", "Uploading transcripts to Box")
    logger.info("[GhostWriter][pipeline] Stage 1: Ingest")
    ingested = ingest(config, box)
    if has_ui:
        for f in ingested:
            show_upload(f.filename, f.box_file_id)
    if not ingested:
        logger.warning("[GhostWriter][pipeline] No transcripts ingested")

    # Stage 2: Extract
    if has_ui: show_stage(2, "Extract", "Box AI extracting tasks from each transcript")
    logger.info("[GhostWriter][pipeline] Stage 2: Extract")
    tasks = extract(ingested, box)
    logger.info("[GhostWriter][pipeline] Extracted %d tasks", len(tasks))

    # Stage 3: Recurrence detection
    if has_ui: show_stage(3, "Recurrence", "Box AI identifying neglected recurring tasks")
    logger.info("[GhostWriter][pipeline] Stage 3: Recurrence detection")
    file_ids = [f.box_file_id for f in ingested]
    neglected = detect_recurrence(file_ids, box)
    logger.info("[GhostWriter][pipeline] Found %d neglected tasks", len(neglected))

    if not neglected:
        logger.info("[GhostWriter][pipeline] No neglected tasks — producing empty report")
        report = build_report([], [], config.dry_run, run_id)
        _upload_report(report, box, config)
        return report

    # Apify enrichment: public-evidence priority + dependency-compat checks (no-op without APIFY_TOKEN)
    from apify_enrich import enrich, scan_competitors
    neglected = enrich(neglected)

    if has_ui:
        show_neglected_tasks(neglected)

    # Stage 4: Classify
    if has_ui: show_stage(4, "Classify", "Bedrock LLM deciding which tasks are safe to auto-implement")
    logger.info("[GhostWriter][pipeline] Stage 4: Classify")
    neglected = classify(neglected, config.bedrock_model_id, config.repo)
    if has_ui:
        for t in neglected:
            show_classification(t)

    if config.dry_run:
        # Interactive override still available in dry-run for planning
        skipped = [t for t in neglected if not t.auto_doable]
        if skipped and sys.stdin.isatty():
            neglected = _prompt_user_overrides(neglected)
        logger.info("[GhostWriter][pipeline] Dry run — stopping after classify")
        report = build_report(neglected, [], True, run_id)
        report.recommendations = scan_competitors()
        _upload_report(report, box, config)
        return report

    # Stage 5-6: Implement — start auto-doable tasks immediately in parallel
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from agents.orchestrator import orchestrate

    auto_now = [t for t in neglected if t.auto_doable]
    skipped = [t for t in neglected if not t.auto_doable]

    # Kick off auto-doable tasks in background immediately
    bg_future = None
    if auto_now:
        if has_ui: show_stage(5, "Implement", f"Starting {len(auto_now)} task(s) in parallel — each on its own branch")
        logger.info("[GhostWriter][pipeline] Stage 5-6: Starting %d auto-doable tasks in parallel", len(auto_now))
        pool = ThreadPoolExecutor(max_workers=1)
        bg_future = pool.submit(orchestrate, neglected, config.repo, config.bedrock_model_id, run_id)

    # Meanwhile, prompt user for overrides on skipped tasks
    if skipped and sys.stdin.isatty():
        neglected = _prompt_user_overrides(neglected)
        # If user forced any new tasks, run those too
        newly_approved = [t for t in neglected if t.auto_doable and t.user_guidance and t not in auto_now]
        if newly_approved:
            logger.info("[GhostWriter][pipeline] Running %d user-overridden tasks", len(newly_approved))
            override_results, _ = orchestrate(neglected, config.repo, config.bedrock_model_id, run_id + "-ovr")
        else:
            override_results = []
    else:
        override_results = []

    # Collect background results
    if bg_future:
        results, _ = bg_future.result()
        pool.shutdown(wait=False)
    else:
        results = []

    all_results = results + override_results
    if has_ui:
        for r in all_results:
            show_worker_result(r)

    # Stage 7: Report
    if has_ui: show_stage(7, "Report", "Building and uploading run report")
    logger.info("[GhostWriter][pipeline] Stage 7: Build report")
    report = build_report(neglected, all_results, False, run_id)
    report.recommendations = scan_competitors()
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
        import tempfile, os
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
    tasks_folder = None
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


def classify(neglected: list[NeglectedTask], model_id: str, repo: Path = None) -> list[NeglectedTask]:
    """Use Bedrock LLM to classify each NeglectedTask with codebase research."""
    from agents.worker import AGENT_BACKEND

    # If using an external agent (kiro/claude-code), let IT do the research + classification
    if AGENT_BACKEND in ("kiro", "claude-code") and repo:
        return _classify_via_agent(neglected, repo)

    aws_region = os.environ.get("AWS_REGION", "us-east-1")
    model = BedrockModel(model_id=model_id, region_name=aws_region)
    classifier = Agent(model=model, system_prompt="You are a JSON-only responder.")

    for task in neglected:
        # Fast-path: unsafe keywords → false
        combined = (task.title + " " + task.description).lower()
        if any(kw in combined for kw in _UNSAFE_KEYWORDS):
            task.auto_doable = False
            task.classification_reasoning = "Contains unsafe keyword"
            logger.info("[GhostWriter][classify][%s] auto_doable=False (unsafe keyword)", task.id)
            continue

        code_context = _research_codebase(task, repo) if repo else "(no repo provided)"
        prompt = _CLASSIFY_PROMPT.format(title=task.title, description=task.description, code_context=code_context)
        try:
            response = classifier(prompt)
            text = str(response).strip()
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                data = json.loads(match.group())
                task.auto_doable = bool(data.get("auto_doable", False))
                task.auto_doable_category = data.get("category")
                task.classification_reasoning = data.get("reasoning")
            else:
                task.auto_doable = False
                task.classification_reasoning = "Could not parse classifier response"
        except Exception as e:
            logger.error("[GhostWriter][classify][%s] Bedrock error: %s", task.id, e)
            task.auto_doable = False
            task.classification_reasoning = f"Classification failed: {e}"

        logger.info(
            "[GhostWriter][classify][%s] auto_doable=%s category=%s reasoning=%s",
            task.id, task.auto_doable, task.auto_doable_category, task.classification_reasoning,
        )

    return neglected


def _classify_via_agent(neglected: list[NeglectedTask], repo: Path) -> list[NeglectedTask]:
    """Use kiro-cli or claude-code to research the codebase and classify tasks."""
    import subprocess
    from agents.worker import AGENT_BACKEND

    tasks_json = json.dumps([{"id": t.id, "title": t.title, "description": t.description} for t in neglected])

    prompt = (
        f"You are classifying tasks for an auto-implementation tool. "
        f"Research this codebase to determine which tasks are safe to auto-implement.\n\n"
        f"Tasks to classify:\n{tasks_json}\n\n"
        f"For EACH task, search the codebase to find the relevant files and understand the scope.\n"
        f"A task is auto_doable if it's a localized change (1-3 files, <50 lines, no auth/payment/migration).\n\n"
        f"Respond with ONLY a JSON array:\n"
        f'[{{"id": "...", "auto_doable": true/false, "category": "...", "reasoning": "...", "files_to_change": [...]}}]'
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
            for task in neglected:
                if task.id in results_map:
                    data = results_map[task.id]
                    task.auto_doable = bool(data.get("auto_doable", False))
                    task.auto_doable_category = data.get("category")
                    task.classification_reasoning = data.get("reasoning")
                logger.info("[GhostWriter][classify][%s] auto_doable=%s reasoning=%s",
                            task.id, task.auto_doable, task.classification_reasoning)
            return neglected
        except json.JSONDecodeError:
            pass

    # Fallback: if agent didn't return parseable JSON, mark all as auto_doable
    # (the agent researched it, trust its judgment even if format was off)
    logger.warning("[GhostWriter][classify] Could not parse agent output, defaulting all to auto_doable")
    for task in neglected:
        task.auto_doable = True
        task.auto_doable_category = "agent-researched"
        task.classification_reasoning = "Agent researched codebase but output wasn't parseable JSON; defaulting to approve"
    return neglected


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


def _prompt_user_overrides(neglected: list[NeglectedTask]) -> list[NeglectedTask]:
    """Interactively ask user if they want to force-approve skipped tasks."""
    from rich.console import Console
    from rich.panel import Panel
    from feedback import record_override

    console = Console()
    skipped = [t for t in neglected if not t.auto_doable]

    console.print()
    console.print(Panel(
        f"[yellow]{len(skipped)} task(s) were skipped by the classifier.[/yellow]\n"
        "[dim]You can provide implementation details to force any task through.[/dim]",
        title="[bold]💡 Override Skipped Tasks?[/bold]",
        border_style="yellow",
    ))

    for task in skipped:
        console.print(f"\n  [bold]{task.title}[/bold]")
        console.print(f"  [dim]Reason skipped: {task.classification_reasoning}[/dim]")
        console.print(f"  [dim]Description: {task.description[:100]}[/dim]")
        answer = console.input("  [yellow]Provide implementation details (or Enter to skip):[/yellow] ").strip()

        if answer:
            task.auto_doable = True
            task.auto_doable_category = "user-directed"
            task.user_guidance = answer
            task.classification_reasoning = f"User override: {answer[:80]}"
            record_override(
                task_id=task.id,
                title=task.title,
                description=task.description,
                user_guidance=answer,
                classification_reasoning=task.classification_reasoning,
            )
            console.print(f"  [green]✅ Forced auto-doable with your guidance[/green]")

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
    import time
    for attempt in range(3):
        try:
            folder_id = box.ensure_folder("reports", config.box_root_folder_id)
            fid = box.upload_report(report.to_markdown(), folder_id, f"ghostwriter_report_{report.run_id}.md")
            report.report_box_file_id = fid
            logger.info("[GhostWriter][report] Uploaded report to Box: %s", fid)
            return
        except Exception as e:
            if attempt < 2:
                logger.warning("[GhostWriter][report] Upload failed (attempt %d), retrying: %s", attempt + 1, e)
                time.sleep(2 ** attempt)
            else:
                logger.error("[GhostWriter][report] Box upload failed after 3 attempts: %s", e)
                raise
