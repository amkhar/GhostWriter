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
from ui_service import run_dry_run, DRY_RUN_STAGES

load_dotenv()
# Match the CLI: map a Bedrock API key to the boto3 bearer-token env var.
if os.environ.get("BEDROCK_API_KEY") and not os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = os.environ["BEDROCK_API_KEY"]

st.set_page_config(page_title="GhostWriter", page_icon="👻", layout="wide")
st.title("👻 GhostWriter")
st.caption("Find recurring neglected tasks in standup transcripts (Dry Run — no code is changed).")

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

st.subheader("Transcripts")
tab_upload, tab_paste = st.tabs(["Upload files", "Paste text"])
with tab_upload:
    uploaded = st.file_uploader(
        "Standup transcripts (.txt / .md)", type=["txt", "md"], accept_multiple_files=True
    )
with tab_paste:
    pasted = st.text_area("Paste a single transcript", height=200)

if st.button("Run dry run", type="primary"):
    if not (box_token and model_id):
        st.error("Box token and Bedrock model ID are required — set them in `.env`.")
        st.stop()
    if not uploaded and not pasted.strip():
        st.error("Provide at least one transcript (upload a file or paste text).")
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
        repo=None,
        dry_run=True,
        box_dev_token=box_token,
        aws_region=region,
        bedrock_model_id=model_id,
        box_root_folder_id=box_folder,
    )

    st.subheader("Pipeline")
    slots = {s: st.empty() for s in DRY_RUN_STAGES}
    for s in DRY_RUN_STAGES:
        slots[s].markdown(f"⏳ {s}")
    icons = {"running": "🔄", "done": "✅", "skipped": "⏭️"}

    def progress(stage: str, status: str) -> None:
        slots[stage].markdown(f"{icons.get(status, '•')} {stage}")

    try:
        report = run_dry_run(config, progress)
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

    st.subheader("Run report")
    md = report.to_markdown()
    st.markdown(md)
    st.download_button("Download report.md", md, file_name=f"ghostwriter_report_{report.run_id}.md")
    if report.report_box_file_id:
        st.success(f"Report uploaded to Box (file ID: {report.report_box_file_id})")
