"""GhostWriter Streamlit UI — dry-run mode.

Local-only tool. Run with:  streamlit run app.py
(Binds to localhost; no auth — do not expose to a network.)
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from models import PipelineConfig
from ui_service import run_dry_run, run_full, DRY_RUN_STAGES, FULL_RUN_STAGES

load_dotenv()
# Match the CLI: map a Bedrock API key to the boto3 bearer-token env var.
if os.environ.get("BEDROCK_API_KEY") and not os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = os.environ["BEDROCK_API_KEY"]

st.set_page_config(page_title="GhostWriter", page_icon="👻", layout="wide")
st.title("👻 GhostWriter")
st.caption("Find recurring neglected tasks in standup transcripts, and optionally auto-implement the safe ones.")

box_token = os.environ.get("BOX_TOKEN", "")
region = os.environ.get("AWS_REGION", "us-east-1")
model_id = os.environ.get("BEDROCK_MODEL_ID", "")

with st.sidebar:
    st.header("Configuration")
    st.write("Box token:", "✅ set" if box_token else "❌ missing")
    st.write("AWS region:", region or "❌ missing")
    st.write("Bedrock model:", model_id or "❌ missing")
    box_folder = st.text_input("Box root folder ID", value="0")
    st.caption("Values are read from `.env`; secrets are never displayed.")
    st.divider()
    mode = st.radio("Mode", ["Dry Run", "Full Run"], help="Full Run lets agents implement safe tasks on a copy of the repo.")
    repo_path = ""
    if mode == "Full Run":
        repo_path = st.text_input("Target repo path", help="A git repo. Changes go to a new ghostwriter/auto-* branch.")
        st.info("Full Run copies the repo, works on a `ghostwriter/auto-*` branch, and never touches `main`.")

st.subheader("Transcripts")
tab_upload, tab_paste = st.tabs(["Upload files", "Paste text"])
with tab_upload:
    uploaded = st.file_uploader(
        "Standup transcripts (.txt / .md)", type=["txt", "md"], accept_multiple_files=True
    )
with tab_paste:
    pasted = st.text_area("Paste a single transcript", height=200)

full = mode == "Full Run"
if st.button("Run full" if full else "Run dry run", type="primary"):
    if not (box_token and model_id):
        st.error("Box token and Bedrock model ID are required — set them in `.env`.")
        st.stop()
    if not uploaded and not pasted.strip():
        st.error("Provide at least one transcript (upload a file or paste text).")
        st.stop()
    if full and not (repo_path and Path(repo_path).is_dir()):
        st.error("Full Run requires a valid target repo path.")
        st.stop()

    transcripts_dir = None
    paste_content = None
    if uploaded:
        tmp = Path(tempfile.mkdtemp(prefix="gw-ui-"))
        for f in uploaded:
            (tmp / f.name).write_bytes(f.getvalue())
        transcripts_dir = tmp
    else:
        paste_content = pasted

    config = PipelineConfig(
        transcripts_dir=transcripts_dir,
        paste_content=paste_content,
        repo=Path(repo_path) if full else None,
        dry_run=not full,
        box_dev_token=box_token,
        aws_region=region,
        bedrock_model_id=model_id,
        box_root_folder_id=box_folder,
    )

    st.subheader("Pipeline")
    stages = FULL_RUN_STAGES if full else DRY_RUN_STAGES
    slots = {s: st.empty() for s in stages}
    for s in stages:
        slots[s].markdown(f"⏳ {s}")
    icons = {"running": "🔄", "done": "✅", "skipped": "⏭️"}

    def progress(stage: str, status: str) -> None:
        slots[stage].markdown(f"{icons.get(status, '•')} {stage}")

    try:
        report = (run_full if full else run_dry_run)(config, progress)
    except Exception as e:
        st.error(f"Run failed: {e}")
        st.stop()

    st.subheader("Neglected tasks")
    if report.neglected_tasks:
        st.dataframe(
            [
                {
                    "Task": t.title,
                    "Auto-doable": "✅" if t.auto_doable else "❌",
                    "Category": t.auto_doable_category or "-",
                    "Why": t.classification_reasoning or t.reason,
                }
                for t in report.neglected_tasks
            ],
            use_container_width=True,
        )
    else:
        st.info("No recurring neglected tasks detected.")

    if report.worker_results:
        st.subheader("Auto-implemented changes")
        for r in report.worker_results:
            header = f"{'✅' if r.success else '❌'} {r.task_id} · tests: {r.test_status or 'n/a'}"
            with st.expander(header, expanded=r.success):
                st.write(r.summary)
                if r.diff:
                    st.code(r.diff, language="diff")
                if r.error:
                    st.error(r.error)

    st.subheader("Run report")
    md = report.to_markdown()
    st.markdown(md)
    st.download_button("Download report.md", md, file_name=f"ghostwriter_report_{report.run_id}.md")
    if report.report_box_file_id:
        st.success(f"Report uploaded to Box (file ID: {report.report_box_file_id})")
