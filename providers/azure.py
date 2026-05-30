"""Microsoft Azure OpenAI provider implementation."""

from __future__ import annotations

import os
from typing import Any, Optional

from strands import Agent
from strands.models import OpenAIModel

from .base import LLMProvider, ModelConfig


class AzureProvider(LLMProvider):
    """Microsoft Azure OpenAI provider implementation."""
    
    def __init__(self, azure_endpoint: str = None, api_key: str = None, 
                 api_version: str = None, deployment_name: str = None):
        """Initialize Azure provider.
        
        Args:
            azure_endpoint: Azure OpenAI endpoint URL
            api_key: Azure OpenAI API key
            api_version: API version to use
            deployment_name: Azure deployment name
        """
        self.azure_endpoint = azure_endpoint or os.environ.get("AZURE_OPENAI_ENDPOINT")
        self.api_key = api_key or os.environ.get("AZURE_OPENAI_API_KEY")
        self.api_version = api_version or os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
        self.deployment_name = deployment_name or os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME")
    
    def create_agent(self, model_config: ModelConfig, system_prompt: str, tools: list = None) -> Agent:
        """Create a Strands Agent with Azure OpenAI model."""
        if not self.azure_endpoint or not self.api_key:
            raise ValueError("Azure endpoint and API key are required")
            
        # Use the deployment name if provided, otherwise use the model_id
        deployment = self.deployment_name or model_config.model_id
        
        # Construct the base URL for Azure OpenAI
        base_url = f"{self.azure_endpoint.rstrip('/')}/openai/deployments/{deployment}"
        
        model = OpenAIModel(
            model_name=deployment,  # For Azure, this should be the deployment name
            base_url=base_url,
            api_key=self.api_key,
            max_tokens=model_config.max_tokens or 8192,
            temperature=model_config.temperature,
            extra_headers={
                "api-version": self.api_version
            },
            **model_config.provider_config
        )
        
        agent_kwargs = {
            "model": model,
            "system_prompt": system_prompt,
        }
        
        if tools:
            agent_kwargs["tools"] = tools
            
        return Agent(**agent_kwargs)
    
    def get_default_model_config(self) -> ModelConfig:
        """Get default Azure model configuration."""
        return ModelConfig(
            model_id=os.environ.get("AZURE_MODEL_ID", "gpt-4o"),
            max_tokens=8192,
            provider_config={
                "deployment_name": self.deployment_name
            }
        )
    
    @property
    def provider_name(self) -> str:
        return "azure"
    
    def validate_config(self) -> bool:
        """Validate Azure configuration."""
        return bool(
            self.azure_endpoint and 
            self.api_key and 
            self.api_version
        )