"""Voice recording and transcription via Deepgram live streaming."""
from __future__ import annotations

import os
import sys
import time
import threading
from pathlib import Path
from datetime import datetime

import numpy as np
import sounddevice as sd
from rich.console import Console
from rich.panel import Panel
from rich.live import Live
from rich.text import Text
from rich.spinner import Spinner
from rich.table import Table

console = Console()

SAMPLE_RATE = 16000
CHANNELS = 1


def record_meeting(output_dir: Path, deepgram_api_key: str | None = None) -> Path:
    """Record from microphone with live Deepgram transcription."""
    deepgram_api_key = deepgram_api_key or os.environ.get("DEEPGRAM_API_KEY")
    if not deepgram_api_key:
        console.print("[red]Error:[/] DEEPGRAM_API_KEY not set. Get one free at https://console.deepgram.com")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y_%m_%d_%H%M")
    transcript_path = output_dir / f"standup_{timestamp}.txt"

    transcript_lines: list[str] = []
    current_partial = ""
    is_recording = True
    lock = threading.Lock()

    from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents

    dg = DeepgramClient(deepgram_api_key)
    connection = dg.listen.live.v("1")

    def on_transcript(self, result, **kwargs):
        nonlocal current_partial
        try:
            sentence = result.channel.alternatives[0]
            if not sentence.transcript:
                return
            with lock:
                if result.is_final:
                    transcript_lines.append(sentence.transcript)
                    current_partial = ""
                else:
                    current_partial = sentence.transcript
        except Exception:
            pass

    def on_error(self, error, **kwargs):
        pass

    connection.on(LiveTranscriptionEvents.Transcript, on_transcript)
    connection.on(LiveTranscriptionEvents.Error, on_error)

    options = LiveOptions(
        model="nova-2",
        language="en",
        smart_format=True,
        punctuate=True,
        encoding="linear16",
        channels=CHANNELS,
        sample_rate=SAMPLE_RATE,
    )

    # Start Deepgram connection
    if not connection.start(options):
        console.print("[red]Error: Failed to connect to Deepgram[/red]")
        sys.exit(1)

    # Start audio capture immediately
    def audio_callback(indata, frames, time_info, status):
        if is_recording:
            connection.send(indata.copy().tobytes())

    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        callback=audio_callback,
        blocksize=4096,
    )
    stream.start()

    # Show UI
    console.print()
    console.print(Panel(
        "[bold green]🎙️  Recording standup meeting[/]\n"
        "[dim]Speak naturally. Press [bold]Enter[/bold] to stop recording.[/dim]",
        title="GhostWriter Voice",
        border_style="green",
    ))
    console.print()

    start_time = time.time()

    try:
        with Live(console=console, refresh_per_second=4) as live:
            while True:
                elapsed = int(time.time() - start_time)
                mins, secs = divmod(elapsed, 60)

                with lock:
                    partial = current_partial
                    lines_to_show = transcript_lines[-6:]

                transcript_display = "\n".join(lines_to_show)
                if partial:
                    transcript_display += f"\n[dim italic]{partial}[/dim italic]"

                panel = Panel(
                    transcript_display or "[dim]Listening...[/dim]",
                    title=f"[green]● REC[/green] Live Transcript ({mins:02d}:{secs:02d})",
                    border_style="blue",
                    width=80,
                )

                grid = Table.grid()
                grid.add_row(panel)
                grid.add_row(Text("  Press Enter to stop", style="dim"))
                live.update(grid)

                # Non-blocking check for Enter
                import select
                if select.select([sys.stdin], [], [], 0.25)[0]:
                    sys.stdin.readline()
                    break

    except KeyboardInterrupt:
        pass
    finally:
        is_recording = False
        stream.stop()
        stream.close()
        connection.finish()

    # Save transcript
    full_transcript = f"Standup Meeting — {datetime.now().strftime('%Y-%m-%d')}\n\n"
    full_transcript += "\n".join(transcript_lines)
    transcript_path.write_text(full_transcript)

    console.print()
    console.print(Panel(
        f"[bold]✅ Recording saved[/bold]\n"
        f"Duration: {int(time.time() - start_time)}s\n"
        f"Lines: {len(transcript_lines)}\n"
        f"File: [cyan]{transcript_path}[/cyan]",
        title="Done",
        border_style="green",
    ))

    return transcript_path
