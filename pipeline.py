"""Pipeline orchestrator — coordinates all GhostWriter stages."""
from __future__ import annotations

import json
import logging
import re
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

_CLASSIFY_PROMPT = """You are a code-change safety classifier.

Given a neglected task, decide if it is safe to auto-implement.
Set auto_doable=true ONLY for: fix typo, update doc/README, add missing log line,
add null/empty check, bump dependency version, add simple unit test, rename for consistency.
Set auto_doable=false for: auth, payments, database migrations, infrastructure, code deletion,
or anything that doesn't clearly fit the above categories.

Respond with JSON only:
{{"auto_doable": true|false, "category": "<category or null>", "reasoning": "<1 sentence>"}}

Task title: {title}
Task description: {description}
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
    if has_ui and neglected: show_neglected_tasks(neglected)

    if not neglected:
        logger.info("[GhostWriter][pipeline] No neglected tasks — producing empty report")
        report = build_report([], [], config.dry_run, run_id)
        _upload_report(report, box, config)
        return report

    # Stage 4: Classify
    if has_ui: show_stage(4, "Classify", "Bedrock LLM deciding which tasks are safe to auto-implement")
    logger.info("[GhostWriter][pipeline] Stage 4: Classify")
    neglected = classify(neglected, config.bedrock_model_id)
    if has_ui:
        for t in neglected:
            show_classification(t)

    if config.dry_run:
        logger.info("[GhostWriter][pipeline] Dry run — stopping after classify")
        report = build_report(neglected, [], True, run_id)
        _upload_report(report, box, config)
        return report

    # Stage 5-6: Orchestrate
    if has_ui: show_stage(5, "Implement", "Strands agents making code changes")
    logger.info("[GhostWriter][pipeline] Stage 5-6: Orchestrate")
    from agents.orchestrator import orchestrate
    results, _ = orchestrate(neglected, config.repo, config.bedrock_model_id, run_id)
    if has_ui:
        for r in results:
            show_worker_result(r)

    # Stage 7: Report
    if has_ui: show_stage(7, "Report", "Building and uploading run report")
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


def classify(neglected: list[NeglectedTask], model_id: str) -> list[NeglectedTask]:
    """Use Bedrock LLM to classify each NeglectedTask; set auto_doable flag."""
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

        prompt = _CLASSIFY_PROMPT.format(title=task.title, description=task.description)
        try:
            response = classifier(prompt)
            text = str(response).strip()
            # Extract JSON
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
