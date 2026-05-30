"""GhostWriter Web API — FastAPI server exposing the pipeline via SSE."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

# Add project root to path so we can import pipeline modules
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

DB_PATH = Path(__file__).resolve().parent.parent / "ghostwriter.db"

# ---------- Database ---------- #

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL DEFAULT 'running',
            dry_run INTEGER NOT NULL DEFAULT 0,
            transcript TEXT,
            report_md TEXT,
            tasks_json TEXT,
            results_json TEXT,
            stats_json TEXT
        );
    """)
    conn.close()


# ---------- App ---------- #

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(title="GhostWriter API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------- Recording state ---------- #

_recording_state: dict = {"active": False, "transcript_lines": [], "partial": "", "start_time": 0}
_recording_lock = threading.Lock()
_recording_connection = None
_recording_stream = None


class RecordingStartResponse(BaseModel):
    status: str


class RecordingStopResponse(BaseModel):
    transcript: str
    duration: int
    lines: int


class PipelineRunRequest(BaseModel):
    transcript: Optional[str] = None
    transcripts_dir: Optional[str] = None
    repo: Optional[str] = None
    dry_run: bool = False


# ---------- Recording endpoints ---------- #

@app.post("/api/recording/start", response_model=RecordingStartResponse)
async def recording_start():
    global _recording_connection, _recording_stream
    deepgram_api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not deepgram_api_key:
        raise HTTPException(400, "DEEPGRAM_API_KEY not configured")

    with _recording_lock:
        if _recording_state["active"]:
            raise HTTPException(409, "Already recording")
        _recording_state["active"] = True
        _recording_state["transcript_lines"] = []
        _recording_state["partial"] = ""
        _recording_state["start_time"] = time.time()

    try:
        from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents
        import sounddevice as sd

        dg = DeepgramClient(deepgram_api_key)
        connection = dg.listen.live.v("1")

        def on_transcript(self, result, **kwargs):
            try:
                sentence = result.channel.alternatives[0]
                if not sentence.transcript:
                    return
                with _recording_lock:
                    if result.is_final:
                        _recording_state["transcript_lines"].append(sentence.transcript)
                        _recording_state["partial"] = ""
                    else:
                        _recording_state["partial"] = sentence.transcript
            except Exception:
                pass

        connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
        connection.on(LiveTranscriptionEvents.Error, lambda *a, **k: None)

        options = LiveOptions(model="nova-2", language="en", smart_format=True, punctuate=True,
                              encoding="linear16", channels=1, sample_rate=16000)
        if not connection.start(options):
            raise HTTPException(500, "Failed to connect to Deepgram")

        def audio_callback(indata, frames, time_info, status):
            if _recording_state["active"]:
                connection.send(indata.copy().tobytes())

        stream = sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                                callback=audio_callback, blocksize=4096)
        stream.start()
        _recording_connection = connection
        _recording_stream = stream
    except ImportError as e:
        with _recording_lock:
            _recording_state["active"] = False
        raise HTTPException(500, f"Missing dependency: {e}")
    except Exception as e:
        with _recording_lock:
            _recording_state["active"] = False
        raise HTTPException(500, str(e))

    return RecordingStartResponse(status="recording")


@app.post("/api/recording/stop", response_model=RecordingStopResponse)
async def recording_stop():
    global _recording_connection, _recording_stream
    with _recording_lock:
        if not _recording_state["active"]:
            raise HTTPException(409, "Not recording")
        _recording_state["active"] = False
        lines = list(_recording_state["transcript_lines"])
        duration = int(time.time() - _recording_state["start_time"])

    if _recording_stream:
        _recording_stream.stop()
        _recording_stream.close()
        _recording_stream = None
    if _recording_connection:
        _recording_connection.finish()
        _recording_connection = None

    transcript = "\n".join(lines)
    return RecordingStopResponse(transcript=transcript, duration=duration, lines=len(lines))


@app.get("/api/recording/status")
async def recording_status():
    with _recording_lock:
        return {
            "active": _recording_state["active"],
            "lines": list(_recording_state["transcript_lines"]),
            "partial": _recording_state["partial"],
            "elapsed": int(time.time() - _recording_state["start_time"]) if _recording_state["active"] else 0,
        }


# ---------- Pipeline endpoints ---------- #

@app.post("/api/pipeline/run")
async def pipeline_run(req: PipelineRunRequest):
    """Run the pipeline, streaming SSE events for each stage."""
    run_id = str(uuid.uuid4())[:8]

    # Save run to DB
    conn = get_db()
    conn.execute("INSERT INTO runs (id, started_at, status, dry_run, transcript) VALUES (?, ?, ?, ?, ?)",
                 (run_id, datetime.utcnow().isoformat(), "running", int(req.dry_run), req.transcript or ""))
    conn.commit()
    conn.close()

    async def event_generator():
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def run_in_thread():
            """Run the pipeline in a background thread, posting events to the queue."""
            import logging
            from models import PipelineConfig, NeglectedTask

            stats = {"files_analyzed": 0, "api_calls": 0, "lines_changed": 0}

            def emit(event_type: str, data: dict):
                data["timestamp"] = datetime.utcnow().isoformat()
                loop.call_soon_threadsafe(queue.put_nowait, (event_type, data))

            try:
                emit("stage", {"stage": 0, "name": "Setup", "status": "complete", "message": "Pipeline initialized"})

                # Build config
                config_kwargs = {
                    "dry_run": req.dry_run,
                    "box_dev_token": os.environ.get("BOX_TOKEN"),
                    "aws_region": os.environ.get("AWS_REGION", "us-east-1"),
                    "bedrock_model_id": os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-3-5-sonnet-20241022-v2:0"),
                    "box_root_folder_id": os.environ.get("BOX_ROOT_FOLDER_ID", "0"),
                }

                # Handle transcript input
                if req.transcript:
                    config_kwargs["paste_content"] = req.transcript
                elif req.transcripts_dir:
                    config_kwargs["transcripts_dir"] = Path(req.transcripts_dir)

                if req.repo:
                    config_kwargs["repo"] = Path(req.repo)

                config = PipelineConfig(**config_kwargs)

                from box_client import BoxClient, _RECURRENCE_PROMPT
                from pipeline import ingest, extract, detect_recurrence, classify, build_report

                box = BoxClient(
                    dev_token=os.environ.get("BOX_TOKEN_A") or config.box_dev_token,
                    client_id=os.environ.get("BOX_CLIENT_ID_A"),
                    client_secret=os.environ.get("BOX_SECRET_A"),
                )

                # Stage 1: Ingest
                emit("stage", {"stage": 1, "name": "Ingest", "status": "running", "message": "Uploading transcripts to Box"})
                ingested = ingest(config, box)
                stats["api_calls"] += len(ingested)
                stats["files_analyzed"] = len(ingested)
                emit("stage", {"stage": 1, "name": "Ingest", "status": "complete",
                               "message": f"Uploaded {len(ingested)} file(s)", "stats": stats.copy()})

                # Stage 2: Extract
                emit("stage", {"stage": 2, "name": "Extract", "status": "running", "message": "Box AI extracting tasks"})
                tasks = extract(ingested, box)
                stats["api_calls"] += len(ingested)
                emit("stage", {"stage": 2, "name": "Extract", "status": "complete",
                               "message": f"Extracted {len(tasks)} tasks", "stats": stats.copy()})

                # Stage 3: Recurrence
                emit("stage", {"stage": 3, "name": "Recurrence", "status": "running",
                               "message": "Identifying neglected recurring tasks"})
                file_ids = [f.box_file_id for f in ingested]
                neglected = detect_recurrence(file_ids, box)
                stats["api_calls"] += 1
                emit("stage", {"stage": 3, "name": "Recurrence", "status": "complete",
                               "message": f"Found {len(neglected)} neglected tasks",
                               "tasks": [t.model_dump() for t in neglected], "stats": stats.copy()})

                if not neglected:
                    emit("complete", {"run_id": run_id, "message": "No neglected tasks found", "stats": stats})
                    loop.call_soon_threadsafe(queue.put_nowait, None)
                    return

                # Stage 4: Classify
                emit("stage", {"stage": 4, "name": "Classify", "status": "running",
                               "message": "LLM classifying task safety"})
                neglected = classify(neglected, config.bedrock_model_id, config.repo)
                stats["api_calls"] += len(neglected)
                emit("stage", {"stage": 4, "name": "Classify", "status": "complete",
                               "message": f"Classified {len(neglected)} tasks",
                               "tasks": [t.model_dump() for t in neglected], "stats": stats.copy()})

                if config.dry_run:
                    report = build_report(neglected, [], True, run_id)
                    emit("complete", {"run_id": run_id, "dry_run": True, "report": report.to_markdown(),
                                      "tasks": [t.model_dump() for t in neglected], "stats": stats})
                    # Save to DB
                    conn2 = get_db()
                    conn2.execute("UPDATE runs SET finished_at=?, status=?, report_md=?, tasks_json=?, stats_json=? WHERE id=?",
                                  (datetime.utcnow().isoformat(), "complete", report.to_markdown(),
                                   json.dumps([t.model_dump() for t in neglected]), json.dumps(stats), run_id))
                    conn2.commit()
                    conn2.close()
                    loop.call_soon_threadsafe(queue.put_nowait, None)
                    return

                # Stage 5-6: Implement
                auto_tasks = [t for t in neglected if t.auto_doable]
                if auto_tasks:
                    emit("stage", {"stage": 5, "name": "Implement", "status": "running",
                                   "message": f"Implementing {len(auto_tasks)} task(s)"})

                    from agents.orchestrator import orchestrate
                    for t in auto_tasks:
                        emit("agent", {"task_id": t.id, "title": t.title, "status": "working",
                                       "message": f"Agent working on: {t.title}"})

                    results, _ = orchestrate(neglected, config.repo, config.bedrock_model_id, run_id)

                    for r in results:
                        stats["lines_changed"] += len((r.diff or "").split("\n"))
                        emit("agent", {"task_id": r.task_id, "status": "done" if r.success else "failed",
                                       "summary": r.summary, "diff": r.diff, "test_status": r.test_status})

                    emit("stage", {"stage": 5, "name": "Implement", "status": "complete",
                                   "message": f"Completed {len(results)} task(s)", "stats": stats.copy()})
                else:
                    results = []

                # Stage 7: Report
                emit("stage", {"stage": 7, "name": "Report", "status": "running", "message": "Building report"})
                report = build_report(neglected, results, False, run_id)
                emit("stage", {"stage": 7, "name": "Report", "status": "complete",
                               "message": "Report generated"})

                emit("complete", {"run_id": run_id, "report": report.to_markdown(),
                                  "tasks": [t.model_dump() for t in neglected],
                                  "results": [r.model_dump() for r in results], "stats": stats})

                # Save to DB
                conn2 = get_db()
                conn2.execute("UPDATE runs SET finished_at=?, status=?, report_md=?, tasks_json=?, results_json=?, stats_json=? WHERE id=?",
                              (datetime.utcnow().isoformat(), "complete", report.to_markdown(),
                               json.dumps([t.model_dump() for t in neglected]),
                               json.dumps([r.model_dump() for r in results]), json.dumps(stats), run_id))
                conn2.commit()
                conn2.close()

            except Exception as e:
                emit("error", {"message": str(e), "run_id": run_id})
                conn2 = get_db()
                conn2.execute("UPDATE runs SET finished_at=?, status=? WHERE id=?",
                              (datetime.utcnow().isoformat(), "failed", run_id))
                conn2.commit()
                conn2.close()

            loop.call_soon_threadsafe(queue.put_nowait, None)

        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()

        while True:
            item = await queue.get()
            if item is None:
                break
            event_type, data = item
            yield {"event": event_type, "data": json.dumps(data)}

    return EventSourceResponse(event_generator())


@app.get("/api/pipeline/runs")
async def list_runs():
    conn = get_db()
    rows = conn.execute("SELECT id, started_at, finished_at, status, dry_run, stats_json FROM runs ORDER BY started_at DESC LIMIT 50").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/pipeline/runs/{run_id}")
async def get_run(run_id: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Run not found")
    return dict(row)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
