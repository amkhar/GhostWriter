"""Base provider interface for L and M providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional
from pydantic import BaseModel
from strands import Agent


class ModelConfig(BaseModel):
    """Configuration for a specific model."""
    model_id: str
    region: Optional[str] = None
    max_tokens: Optional[int] = 8192
    temperature: Optional[float] = None
    provider_config: dict[str, Any] = {}


class LLMProvider(ABC):
    """Abstract base class for L and M providers."""
    
    @abstractmethod
    def create_agent(self, model_config: ModelConfig, system_prompt: str, tools: list = None) -> Agent:
        """Create a Strands Agent instance for this provider."""
        pass
    
    @abstractmethod
    def get_default_model_config(self) -> ModelConfig:
        """Get default model configuration for this provider."""
        pass
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name."""
        pass
    
    @abstractmethod
    def validate_config(self) -> bool:
        """Validate that the provider is properly configured."""
        pass