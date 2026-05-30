"""Rich terminal UI — shows pipeline progress, agent thinking, and results."""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.markdown import Markdown
from rich.rule import Rule
from rich.columns import Columns

from models import NeglectedTask, WorkerResult, RunReport

console = Console()


def show_banner():
    console.print()
    console.print(Panel(
        "[bold white]👻 GhostWriter[/bold white]\n"
        "[dim]Turn standups into shipped code[/dim]",
        border_style="bright_magenta",
        width=60,
    ))
    console.print()


def show_stage(number: int, name: str, description: str = ""):
    console.print()
    console.print(Rule(f"[bold cyan]Stage {number}[/bold cyan] · {name}", style="cyan"))
    if description:
        console.print(f"  [dim]{description}[/dim]")


def show_upload(filename: str, box_id: str):
    console.print(f"  [green]↑[/green] {filename} → [dim]Box:{box_id}[/dim]")


def show_extracted_tasks(count: int, filename: str):
    console.print(f"  [yellow]⚡[/yellow] {filename}: {count} tasks extracted")


def show_neglected_tasks(tasks: list[NeglectedTask]):
    console.print()
    table = Table(title="🔍 Neglected Tasks Found", border_style="yellow", show_lines=True)
    table.add_column("Task", style="bold")
    table.add_column("Reason", style="dim")
    table.add_column("Standups", justify="center")

    for t in tasks:
        # Extract standup count from reason
        count = t.reason.count("standup") or "?"
        table.add_row(t.title, t.reason[:60], str(count) if isinstance(count, int) else "3+")

    console.print(table)


def show_classification(task: NeglectedTask):
    if task.auto_doable:
        icon = "✅"
        style = "green"
    else:
        icon = "❌"
        style = "red"
    console.print(
        f"  {icon} [{style}]{task.id}[/{style}] → "
        f"{'[bold green]AUTO-DOABLE[/bold green]' if task.auto_doable else '[dim]skip[/dim]'}"
        f"{'  [dim](' + task.auto_doable_category + ')[/dim]' if task.auto_doable_category else ''}"
    )


def show_agent_thinking(task_id: str, message: str):
    console.print(Panel(
        f"[italic]{message}[/italic]",
        title=f"[bold blue]🤖 Agent Thinking[/bold blue] · {task_id}",
        border_style="blue",
        width=70,
    ))


def show_worker_start(task_id: str, description: str):
    console.print()
    console.print(Panel(
        f"[bold]{description}[/bold]",
        title=f"[yellow]⚙️  Worker[/yellow] · {task_id}",
        border_style="yellow",
        width=70,
    ))


def show_worker_tool_call(tool_name: str, detail: str = ""):
    icon = {"read_file": "📖", "write_file": "✏️", "grep": "🔍", "list_dir": "📂", "run_shell": "🐚"}.get(tool_name, "🔧")
    console.print(f"    {icon} [dim]{tool_name}[/dim] {detail}")


def show_worker_result(result: WorkerResult):
    if result.success:
        console.print(Panel(
            f"[bold green]✅ Success[/bold green]\n"
            f"[bold]{result.summary}[/bold]\n"
            f"Tests: {result.test_status or 'n/a'}",
            title=f"Worker Result · {result.task_id}",
            border_style="green",
            width=70,
        ))
        if result.diff:
            # Show a compact diff
            diff_lines = result.diff.strip().split("\n")
            compact = "\n".join(diff_lines[:20])
            if len(diff_lines) > 20:
                compact += f"\n... ({len(diff_lines) - 20} more lines)"
            console.print(Panel(compact, title="[dim]Git Diff[/dim]", border_style="dim", width=70))
    else:
        console.print(Panel(
            f"[bold red]❌ Failed[/bold red]\n{result.error or result.summary}",
            title=f"Worker Result · {result.task_id}",
            border_style="red",
            width=70,
        ))


def show_commit(task_id: str, branch: str):
    console.print(f"  [green]✓[/green] Committed [bold]{task_id}[/bold] → [cyan]{branch}[/cyan]")


def show_push(branch: str, success: bool):
    if success:
        console.print(Panel(
            f"[bold green]🚀 Pushed branch[/bold green] [cyan]{branch}[/cyan] to origin",
            border_style="green",
            width=70,
        ))
    else:
        console.print(f"  [yellow]⚠️  Push skipped (no remote configured)[/yellow]")


def show_report_summary(report: RunReport):
    console.print()
    console.print(Rule("[bold magenta]📋 Run Report", style="magenta"))
    console.print()

    # Stats cards
    total = len(report.neglected_tasks)
    auto = sum(1 for t in report.neglected_tasks if t.auto_doable)
    success = sum(1 for r in report.worker_results if r.success)
    failed = sum(1 for r in report.worker_results if not r.success)

    stats = Table.grid(padding=(0, 3))
    stats.add_row(
        Panel(f"[bold]{total}[/bold]\n[dim]neglected[/dim]", width=14, border_style="yellow"),
        Panel(f"[bold]{auto}[/bold]\n[dim]auto-doable[/dim]", width=14, border_style="cyan"),
        Panel(f"[bold green]{success}[/bold green]\n[dim]implemented[/dim]", width=14, border_style="green"),
        Panel(f"[bold red]{failed}[/bold red]\n[dim]failed[/dim]", width=14, border_style="red") if failed else Text(""),
    )
    console.print(stats)

    if report.report_box_file_id:
        console.print(f"\n  [dim]Report uploaded to Box:[/dim] [cyan]{report.report_box_file_id}[/cyan]")
