"""Pluggable transcript provider abstraction.

Register custom providers to broaden transcript ingestion beyond Deepgram.

Usage:
    from transcript_providers import registry, TranscriptProvider

    class MyProvider(TranscriptProvider):
        name = "my_provider"

        def transcribe(self, output_dir: Path, **kwargs) -> Path:
            # ... produce a .txt transcript file in output_dir ...
            return path_to_transcript

    registry.register(MyProvider)

    # Or use the decorator:
    @registry.register
    class AnotherProvider(TranscriptProvider):
        name = "another"
        def transcribe(self, output_dir, **kwargs):
            ...

Select provider via GHOSTWRITER_TRANSCRIPT_PROVIDER env var (default: "deepgram").
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Type


class TranscriptProvider(ABC):
    """Base class for transcript providers."""

    name: str  # unique identifier, e.g. "deepgram", "assemblyai"

    @abstractmethod
    def transcribe(self, output_dir: Path, **kwargs) -> Path:
        """Produce a transcript file in output_dir and return its path."""
        ...


class _ProviderRegistry:
    """Registry of available transcript providers."""

    def __init__(self):
        self._providers: dict[str, Type[TranscriptProvider]] = {}

    def register(self, cls: Type[TranscriptProvider]) -> Type[TranscriptProvider]:
        """Register a provider class. Can be used as a decorator."""
        self._providers[cls.name] = cls
        return cls

    def get(self, name: str | None = None) -> TranscriptProvider:
        """Instantiate and return a provider by name (defaults to env var or 'deepgram')."""
        name = name or os.environ.get("GHOSTWRITER_TRANSCRIPT_PROVIDER", "deepgram")
        if name not in self._providers:
            available = ", ".join(sorted(self._providers.keys())) or "(none)"
            raise ValueError(
                f"Unknown transcript provider '{name}'. Available: {available}"
            )
        return self._providers[name]()

    @property
    def available(self) -> list[str]:
        return sorted(self._providers.keys())


registry = _ProviderRegistry()


# --- Built-in: Deepgram provider ---

class DeepgramProvider(TranscriptProvider):
    """Live microphone transcription via Deepgram Nova."""

    name = "deepgram"

    def transcribe(self, output_dir: Path, **kwargs) -> Path:
        from voice import record_meeting
        api_key = kwargs.get("api_key") or os.environ.get("DEEPGRAM_API_KEY")
        return record_meeting(output_dir, deepgram_api_key=api_key)


registry.register(DeepgramProvider)
