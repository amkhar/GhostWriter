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


def _noop(_stage: str, _status: str) -> None:
    pass


def run_dry_run(config: PipelineConfig, progress: ProgressFn = _noop) -> RunReport:
    """Run pipeline stages 1-4 + report (no code changes). Returns the RunReport."""
    run_id = str(uuid.uuid4())[:8]
    box = BoxClient(config.box_dev_token)

    progress("Ingest", "running")
    ingested = P.ingest(config, box)
    progress("Ingest", "done")

    progress("Extract", "running")
    P.extract(ingested, box)
    progress("Extract", "done")

    progress("Recurrence", "running")
    file_ids = [f.box_file_id for f in ingested]
    neglected = P.detect_recurrence(file_ids, box)
    progress("Recurrence", "done")

    if neglected:
        progress("Classify", "running")
        neglected = P.classify(neglected, config.bedrock_model_id)
        progress("Classify", "done")
    else:
        progress("Classify", "skipped")

    progress("Report", "running")
    report = P.build_report(neglected, [], True, run_id)
    P._upload_report(report, box, config)
    progress("Report", "done")
    return report
