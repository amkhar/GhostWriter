"""GhostWriter CLI entry point."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import typer
from dotenv import load_dotenv
import os

from models import PipelineConfig

app = typer.Typer(
    help="GhostWriter — Turn standups into shipped code",
    no_args_is_help=True,
)

_REQUIRED_VARS = ["AWS_REGION", "BEDROCK_MODEL_ID"]

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    stream=sys.stdout,
)


def _load_and_validate_env() -> dict[str, str]:
    load_dotenv()
    bedrock_api_key = os.environ.get("BEDROCK_API_KEY")
    if bedrock_api_key and not os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = bedrock_api_key
    missing = [v for v in _REQUIRED_VARS if not os.environ.get(v)]
    has_box = os.environ.get("BOX_TOKEN") or (os.environ.get("BOX_CLIENT_ID_A") and os.environ.get("BOX_SECRET_A"))
    if not has_box:
        missing.append("BOX_TOKEN or (BOX_CLIENT_ID_A + BOX_SECRET_A)")
    if missing:
        typer.echo(f"[GhostWriter] Missing required environment variables: {', '.join(missing)}", err=True)
        raise typer.Exit(code=1)
    return {v: os.environ.get(v, "") for v in _REQUIRED_VARS}


@app.command()
def run(
    transcripts: Optional[Path] = typer.Option(None, "--transcripts", help="Directory of .txt/.md transcript files"),
    repo: Optional[Path] = typer.Option(None, "--repo", help="Target repository directory"),
    paste: bool = typer.Option(False, "--paste", help="Read transcript from stdin"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run stages 1-4 only; no code changes"),
    box_folder: str = typer.Option("0", "--box-folder", help="Box root folder ID (default: root)"),
) -> None:
    """Run the full GhostWriter pipeline on existing transcripts."""
    env = _load_and_validate_env()

    if not paste and not transcripts:
        typer.echo("[GhostWriter] Error: provide --transcripts <dir> or --paste", err=True)
        raise typer.Exit(code=1)

    if transcripts and not transcripts.is_dir():
        typer.echo(f"[GhostWriter] Error: --transcripts path is not a directory: {transcripts}", err=True)
        raise typer.Exit(code=1)

    if not dry_run and not repo:
        typer.echo("[GhostWriter] Error: --repo is required unless --dry-run is set", err=True)
        raise typer.Exit(code=1)

    if repo and not repo.is_dir():
        typer.echo(f"[GhostWriter] Error: --repo path is not a directory: {repo}", err=True)
        raise typer.Exit(code=1)

    paste_content: Optional[str] = None
    if paste:
        typer.echo("[GhostWriter] Reading transcript from stdin...")
        paste_content = sys.stdin.read()

    config = PipelineConfig(
        transcripts_dir=transcripts,
        paste_content=paste_content,
        repo=repo,
        dry_run=dry_run,
        box_dev_token=os.environ.get("BOX_TOKEN"),
        aws_region=env["AWS_REGION"],
        bedrock_model_id=env["BEDROCK_MODEL_ID"],
        box_root_folder_id=box_folder,
    )

    from ui import show_banner, show_report_summary
    show_banner()

    from pipeline import run_pipeline
    try:
        report = run_pipeline(config)
    except Exception as e:
        typer.echo(f"[GhostWriter] Pipeline failed: {e}", err=True)
        raise typer.Exit(code=1)

    show_report_summary(report)
    typer.echo("\n" + report.to_markdown())

    if report.report_box_file_id:
        typer.echo(f"\n[GhostWriter] Report uploaded to Box: {report.report_box_file_id}")
    else:
        typer.echo("\n[GhostWriter] Warning: report was not uploaded to Box", err=True)
        raise typer.Exit(code=1)


@app.command()
def record(
    output: Path = typer.Option("./transcripts", "--output", "-o", help="Directory to save transcript"),
    repo: Optional[Path] = typer.Option(None, "--repo", help="Target repository (run pipeline after recording)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Classify only after recording, no code changes"),
) -> None:
    """Record a standup meeting from your microphone, transcribe it, then run the pipeline.

    Requires DEEPGRAM_API_KEY (free at https://console.deepgram.com).
    Records until you press Enter, then automatically runs the GhostWriter pipeline.
    """
    load_dotenv()
    bedrock_api_key = os.environ.get("BEDROCK_API_KEY")
    if bedrock_api_key and not os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = bedrock_api_key

    from ui import show_banner
    show_banner()

    from transcript_providers import registry
    provider = registry.get()
    transcript_path = provider.transcribe(output)

    # Ask if user wants to run the pipeline
    from rich.console import Console
    console = Console()
    console.print()

    if not repo and not dry_run:
        console.print("[dim]No --repo specified. Use --repo to auto-implement, or --dry-run to classify only.[/dim]")
        return

    # Run pipeline on the recorded transcript
    missing = [v for v in _REQUIRED_VARS if not os.environ.get(v)]
    if missing:
        console.print(f"[red]Missing env vars for pipeline: {', '.join(missing)}[/red]")
        raise typer.Exit(code=1)

    # Use only the just-recorded transcript (not the whole folder)
    transcript_content = transcript_path.read_text()

    config = PipelineConfig(
        paste_content=transcript_content,
        repo=repo,
        dry_run=dry_run,
        box_dev_token=os.environ.get("BOX_TOKEN"),
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),
        bedrock_model_id=os.environ["BEDROCK_MODEL_ID"],
    )

    from pipeline import run_pipeline
    from ui import show_report_summary
    try:
        report = run_pipeline(config)
    except Exception as e:
        console.print(f"[red]Pipeline failed: {e}[/red]")
        raise typer.Exit(code=1)

    show_report_summary(report)
    console.print("\n" + report.to_markdown())


@app.command()
def clean(
    all: bool = typer.Option(False, "--all", help="Delete all transcripts without prompting"),
) -> None:
    """Delete old transcripts from Box so they don't show up in future runs."""
    _load_and_validate_env()
    from rich.console import Console
    from rich.prompt import Confirm
    from box_client import BoxClient

    console = Console()
    box = BoxClient(
        dev_token=os.environ.get("BOX_TOKEN_A") or os.environ.get("BOX_TOKEN"),
        client_id=os.environ.get("BOX_CLIENT_ID_A"),
        client_secret=os.environ.get("BOX_SECRET_A"),
    )

    folder_id = box.ensure_folder("transcripts", os.environ.get("BOX_ROOT_FOLDER_ID", "0"))
    files = box.list_folder_files(folder_id)

    if not files:
        console.print("[dim]No transcripts to delete.[/dim]")
        return

    console.print(f"\n[yellow]Found {len(files)} transcript(s) in Box:[/yellow]")
    for i, f in enumerate(files, 1):
        console.print(f"  {i}. [cyan]{f['name']}[/cyan]  [dim]({f['id']})[/dim]")

    if not all:
        if not Confirm.ask(f"\n[red]Delete all {len(files)} transcript(s)?[/red]", default=False):
            console.print("[dim]Cancelled.[/dim]")
            return

    deleted = 0
    for f in files:
        if box.delete_file(f["id"]):
            console.print(f"  [green]✓[/green] Deleted {f['name']}")
            deleted += 1
        else:
            console.print(f"  [red]✗[/red] Failed to delete {f['name']}")

    console.print(f"\n[bold green]Deleted {deleted}/{len(files)} transcripts.[/bold green]")


if __name__ == "__main__":
    app()
