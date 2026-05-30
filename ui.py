"""Rich terminal UI — shows pipeline progress, agent thinking, and results."""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.rule import Rule

from models import NeglectedTask, WorkerResult, RunReport

console = Console()


def show_banner():
    console.print()
    console.print(Panel(
        "[bold white]👻 GhostWriter[/bold white]\n"
        "[dim]AI-powered neglected-task auto-implementer[/dim]",
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
        status = "[bold green]AUTO-DOABLE[/bold green]"
    else:
        icon = "❌"
        style = "red"
        status = "[dim]skip[/dim]"
    
    # Basic classification line
    console.print(
        f"  {icon} [{style}]{task.id}[/{style}] → {status}"
        f"{'  [dim](' + task.auto_doable_category + ')[/dim]' if task.auto_doable_category else ''}"
    )
    
    # Enhanced details for non-auto-doable tasks
    if not task.auto_doable and task.classification:
        console.print(f"    [dim]Reason: {task.classification.reasoning}[/dim]")
        if task.classification.decision_factors:
            key_factors = ", ".join(task.classification.decision_factors[:2])  # Show first 2
            console.print(f"    [dim]Key factors: {key_factors}[/dim]")


def show_classification_details(task: NeglectedTask):
    """Show detailed classification information for a task."""
    if not task.classification:
        return
    
    title = f"🔍 Classification Details · {task.id}"
    content_lines = []
    
    content_lines.append(f"[bold]Decision:[/bold] {'✅ Auto-doable' if task.auto_doable else '❌ Not auto-doable'}")
    content_lines.append(f"[bold]Reasoning:[/bold] {task.classification.reasoning}")
    
    if task.classification.decision_factors:
        content_lines.append("\n[bold]Decision Factors:[/bold]")
        for factor in task.classification.decision_factors:
            content_lines.append(f"  • {factor}")
    
    if task.classification.code_analysis:
        content_lines.append(f"\n[bold]Code Analysis:[/bold] {task.classification.code_analysis}")
    
    if task.classification.risk_assessment:
        content_lines.append(f"\n[bold]Risk Assessment:[/bold] {task.classification.risk_assessment}")
    
    if task.classification.suggested_approach and not task.auto_doable:
        content_lines.append(f"\n[bold]Suggested Approach:[/bold] {task.classification.suggested_approach}")
    
    console.print(Panel(
        "\n".join(content_lines),
        title=title,
        border_style="cyan" if task.auto_doable else "yellow",
        width=80
    ))


def show_skipped_tasks_summary(tasks: list[NeglectedTask]):
    """Show a summary of why tasks were skipped."""
    skipped = [t for t in tasks if not t.auto_doable]
    if not skipped:
        return
    
    console.print()
    console.print(Panel(
        f"[yellow]{len(skipped)} task(s) were not classified as auto-doable.[/yellow]\n"
        "[dim]See detailed explanations in the report.[/dim]",
        title="[bold]📋 Skipped Tasks Summary[/bold]",
        border_style="yellow",
    ))
    
    # Group by common reasons
    reason_counts = {}
    for task in skipped:
        if task.classification and task.classification.reasoning:
            reason = task.classification.reasoning[:50] + "..." if len(task.classification.reasoning) > 50 else task.classification.reasoning
        else:
            reason = task.classification_reasoning or "Unknown reason"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    
    for reason, count in sorted(reason_counts.items(), key=lambda x: x[1], reverse=True):
        console.print(f"  • {reason} [dim]({count} task{'s' if count > 1 else ''})[/dim]")


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
        console.print("  [yellow]⚠️  Push skipped (no remote configured)[/yellow]")


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

    # Show summary of skipped tasks
    show_skipped_tasks_summary(report.neglected_tasks)

    if report.report_box_file_id:
        console.print(f"\n  [dim]Report uploaded to Box:[/dim] [cyan]{report.report_box_file_id}[/cyan]")