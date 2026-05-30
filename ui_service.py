"""Service layer that runs the GhostWriter pipeline for the UI with stage progress callbacks."""
from __future__ import annotations

import uuid
from typing import Callable

from box_client import BoxClient
from models import PipelineConfig, RunReport
import pipeline as P

# progress(stage_name, status) — status is one of: "running", "done", "skipped"
ProgressFn = Callable[[str, str], None]

DRY_RUN_STAGES = ["Ingest", "Extract", "Recurrence", "Classify", "Report"]
FULL_RUN_STAGES = ["Ingest", "Extract", "Recurrence", "Classify", "Orchestrate", "Report"]


def _noop(_stage: str, _status: str) -> None:
    pass


def _ingest_to_classify(config: PipelineConfig, box: BoxClient, progress: ProgressFn) -> list:
    """Run stages 1-4 (ingest, extract, recurrence, classify); return neglected tasks."""
    progress("Ingest", "running")
    ingested = P.ingest(config, box)
    progress("Ingest", "done")

    progress("Extract", "running")
    P.extract(ingested, box)
    progress("Extract", "done")

    progress("Recurrence", "running")
    neglected = P.detect_recurrence([f.box_file_id for f in ingested], box)
    progress("Recurrence", "done")

    if neglected:
        progress("Classify", "running")
        neglected = P.classify(neglected, config.bedrock_model_id)
        progress("Classify", "done")
    else:
        progress("Classify", "skipped")
    return neglected


def _finish(box, config, neglected, results, dry_run, run_id, progress) -> RunReport:
    progress("Report", "running")
    report = P.build_report(neglected, results, dry_run, run_id)
    P._upload_report(report, box, config)
    progress("Report", "done")
    return report


def run_dry_run(config: PipelineConfig, progress: ProgressFn = _noop) -> RunReport:
    """Run pipeline stages 1-4 + report (no code changes). Returns the RunReport."""
    run_id = str(uuid.uuid4())[:8]
    box = BoxClient(config.box_dev_token)
    neglected = _ingest_to_classify(config, box, progress)
    return _finish(box, config, neglected, [], True, run_id, progress)


def run_full(config: PipelineConfig, progress: ProgressFn = _noop) -> RunReport:
    """Run the full pipeline: stages 1-4, orchestrate auto-doable tasks, then report."""
    run_id = str(uuid.uuid4())[:8]
    box = BoxClient(config.box_dev_token)
    neglected = _ingest_to_classify(config, box, progress)

    results = []
    if any(t.auto_doable for t in neglected):
        progress("Orchestrate", "running")
        from agents.orchestrator import orchestrate
        results, _ = orchestrate(neglected, config.repo, config.bedrock_model_id, run_id)
        progress("Orchestrate", "done")
    else:
        progress("Orchestrate", "skipped")

    return _finish(box, config, neglected, results, False, run_id, progress)
