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

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    stream=sys.stdout,
)


def _load_and_validate_env() -> dict[str, str]:
    load_dotenv()
    
    # Handle legacy Bedrock API key mapping
    bedrock_api_key = os.environ.get("BEDROCK_API_KEY")
    if bedrock_api_key and not os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = bedrock_api_key

    # Validate provider configuration
    from providers import ProviderFactory
    provider_name = os.environ.get("LLM_PROVIDER", "bedrock")
    
    try:
        provider = ProviderFactory.create_provider(provider_name)
        if not provider.validate_config():
            raise ValueError(f"Provider {provider_name} is not properly configured")
    except Exception as e:
        typer.echo(f"[GhostWriter] Provider configuration error: {e}", err=True)
        _show_provider_help(provider_name)
        raise typer.Exit(code=1)
    
    # Check Box configuration
    has_box = (
        os.environ.get("BOX_TOKEN") or 
        (os.environ.get("BOX_CLIENT_ID_A") and os.environ.get("BOX_SECRET_A"))
    )
    if not has_box:
        typer.echo("[GhostWriter] Missing Box configuration: need BOX_TOKEN or (BOX_CLIENT_ID_A + BOX_SECRET_A)", err=True)
        raise typer.Exit(code=1)
    
    return {}


def _show_provider_help(provider_name: str) -> None:
    """Show configuration help for a specific provider."""
    help_text = {
        "bedrock": """
Required environment variables for Bedrock provider:
  AWS_REGION=us-east-1
  BEDROCK_MODEL_ID=us.anthropic.claude-3-5-sonnet-20241022-v2:0
  BEDROCK_API_KEY=your_api_key  # OR use AWS credentials

Optional AWS credentials (if not using IAM role):
  AWS_ACCESS_KEY_ID=your_access_key_id
  AWS_SECRET_ACCESS_KEY=your_secret_access_key
  AWS_SESSION_TOKEN=your_session_token  # for temporary credentials
""",
        "gcp": """
Required environment variables for GCP provider:
  GCP_PROJECT_ID=your-project-id
  GCP_LOCATION=us-central1  # optional, defaults to us-central1
  GCP_MODEL_ID=claude-3-5-sonnet@20241022  # optional

Authentication (one of):
  GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
  OR run on GCP with default service account
  OR run 'gcloud auth application-default login'

Install dependencies:
  pip install google-cloud-aiplatform google-auth
""",
        "azure": """
Required environment variables for Azure provider:
  AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
  AZURE_OPENAI_API_KEY=your_api_key
  AZURE_OPENAI_DEPLOYMENT_NAME=your-deployment-name

Optional:
  AZURE_OPENAI_API_VERSION=2024-02-15-preview  # defaults to this version
  AZURE_MODEL_ID=gpt-4o  # optional, defaults to gpt-4o
"""
    }
    
    if provider_name in help_text:
        typer.echo(help_text[provider_name], err=True)
    else:
        available = ", ".join(ProviderFactory.get_available_providers())
        typer.echo(f"Available providers: {available}", err=True)


@app.command()
def run(
    transcripts: Optional[Path] = typer.Option(None, "--transcripts", help="Directory of .txt/.md transcript files"),
    repo: Optional[Path] = typer.Option(None, "--repo", help="Target repository directory"),
    paste: bool = typer.Option(False, "--paste", help="Read transcript from stdin"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run stages 1-4 only; no code changes"),
    box_folder: str = typer.Option("0", "--box-folder", help="Box root folder ID (default: root)"),
    provider: Optional[str] = typer.Option(None, "--provider", help="LLM provider (bedrock, gcp, azure)"),
) -> None:
    """Run the full GhostWriter pipeline on existing transcripts."""
    if provider:
        os.environ["LLM_PROVIDER"] = provider
    
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
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),  # Keep for backward compatibility
        bedrock_model_id=os.environ.get("BEDROCK_MODEL_ID", ""),  # Keep for backward compatibility
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
    provider: Optional[str] = typer.Option(None, "--provider", help="LLM provider (bedrock, gcp, azure)"),
) -> None:
    """Record a standup meeting from your microphone, transcribe it, then run the pipeline.

    Requires DEEPGRAM_API_KEY (free at https://console.deepgram.com).
    Records until you press Enter, then automatically runs the GhostWriter pipeline.
    """
    load_dotenv()
    if provider:
        os.environ["LLM_PROVIDER"] = provider
    
    bedrock_api_key = os.environ.get("BEDROCK_API_KEY")
    if bedrock_api_key and not os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = bedrock_api_key

    from ui import show_banner
    show_banner()

    from voice import record_meeting
    transcript_path = record_meeting(output)

    # Ask if user wants to run the pipeline
    from rich.console import Console
    console = Console()
    console.print()

    if not repo and not dry_run:
        console.print("[dim]No --repo specified. Use --repo to auto-implement, or --dry-run to classify only.[/dim]")
        return

    # Validate configuration
    try:
        _load_and_validate_env()
    except typer.Exit:
        return

    config = PipelineConfig(
        transcripts_dir=transcript_path.parent,
        repo=repo,
        dry_run=dry_run,
        box_dev_token=os.environ.get("BOX_TOKEN"),
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),
        bedrock_model_id=os.environ.get("BEDROCK_MODEL_ID", ""),
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
def providers() -> None:
    """List available LLM providers and their configuration requirements."""
    from providers import ProviderFactory
    from rich.console import Console
    from rich.table import Table
    
    console = Console()
    
    # Auto-detect current provider
    detected = ProviderFactory.auto_detect_provider()
    current = os.environ.get("LLM_PROVIDER", "bedrock")
    
    console.print(f"\n[bold]Available LLM Providers[/bold]")
    console.print(f"Current: [green]{current}[/green]" + (f" (auto-detected: {detected})" if detected else ""))
    console.print()
    
    table = Table(show_header=True, header_style="bold blue")
    table.add_column("Provider", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Configuration Required")
    
    for provider_name in ProviderFactory.get_available_providers():
        try:
            provider = ProviderFactory.create_provider(provider_name)
            status = "✅ Ready" if provider.validate_config() else "❌ Not Configured"
        except Exception:
            status = "❌ Error"
        
        if provider_name == "bedrock":
            config = "AWS_REGION, BEDROCK_MODEL_ID, AWS credentials"
        elif provider_name == "gcp":
            config = "GCP_PROJECT_ID, GOOGLE_APPLICATION_CREDENTIALS"
        elif provider_name == "azure":
            config = "AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY"
        else:
            config = "See --help"
            
        table.add_row(provider_name, status, config)
    
    console.print(table)
    console.print()
    console.print("Set LLM_PROVIDER environment variable or use --provider flag")
    console.print("Run 'ghostwriter run --help' for detailed configuration instructions")


if __name__ == "__main__":
    app()