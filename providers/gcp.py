"""Google Cloud Platform (Vertex AI) provider implementation."""

from __future__ import annotations

import os
from typing import Any, Optional

from strands import Agent
from strands.models import OpenAIModel

from .base import LLMProvider, ModelConfig


class GCPProvider(LLMProvider):
    """Google Cloud Platform (Vertex AI) provider implementation."""
    
    def __init__(self, project_id: str = None, location: str = None, 
                 service_account_path: str = None):
        """Initialize GCP provider.
        
        Args:
            project_id: GCP project ID
            location: GCP region/location for Vertex AI
            service_account_path: Path to service account JSON file
        """
        self.project_id = project_id or os.environ.get("GCP_PROJECT_ID")
        self.location = location or os.environ.get("GCP_LOCATION", "us-central1")
        self.service_account_path = service_account_path or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    
    def create_agent(self, model_config: ModelConfig, system_prompt: str, tools: list = None) -> Agent:
        """Create a Strands Agent with GCP Vertex AI model."""
        # Use OpenAI-compatible API for Vertex AI
        # Vertex AI provides OpenAI-compatible endpoints for some models
        
        # Construct the endpoint URL for Vertex AI
        if not self.project_id or not self.location:
            raise ValueError("GCP project_id and location are required")
            
        # For Vertex AI OpenAI-compatible API
        base_url = f"https://{self.location}-aiplatform.googleapis.com/v1/projects/{self.project_id}/locations/{self.location}/publishers/anthropic/models"
        
        # Get access token for authentication
        access_token = self._get_access_token()
        
        model = OpenAIModel(
            model_name=model_config.model_id,
            base_url=base_url,
            api_key=access_token,
            max_tokens=model_config.max_tokens or 8192,
            temperature=model_config.temperature,
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
        """Get default GCP model configuration."""
        return ModelConfig(
            model_id=os.environ.get("GCP_MODEL_ID", "claude-3-5-sonnet@20241022"),
            region=self.location,
            max_tokens=8192,
        )
    
    @property
    def provider_name(self) -> str:
        return "gcp"
    
    def validate_config(self) -> bool:
        """Validate GCP configuration."""
        if not self.project_id:
            return False
            
        # Check if we have authentication
        if self.service_account_path and os.path.exists(self.service_account_path):
            return True
            
        # Check if running on GCP with default service account
        return self._has_default_credentials()
    
    def _get_access_token(self) -> str:
        """Get GCP access token for authentication."""
        try:
            from google.auth import default
            from google.auth.transport.requests import Request
            
            credentials, _ = default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
            credentials.refresh(Request())
            return credentials.token
        except ImportError:
            raise ImportError(
                "Google Cloud SDK not installed. Install with: pip install google-cloud-aiplatform google-auth"
            )
        except Exception as e:
            raise ValueError(f"Failed to get GCP access token: {e}")
    
    def _has_default_credentials(self) -> bool:
        """Check if default GCP credentials are available."""
        try:
            from google.auth import default
            default()
            return True
        except Exception:
            return False