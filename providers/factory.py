"""Provider factory for creating and managing LLM providers."""

from __future__ import annotations

import os
from typing import Optional

from .base import LLMProvider
from .bedrock import BedrockProvider
from .gcp import GCPProvider
from .azure import AzureProvider


class ProviderFactory:
    """Factory for creating LLM providers."""
    
    _providers = {
        "bedrock": BedrockProvider,
        "gcp": GCPProvider,
        "azure": AzureProvider,
    }
    
    @classmethod
    def create_provider(cls, provider_name: str = None, **kwargs) -> LLMProvider:
        """Create a provider instance.
        
        Args:
            provider_name: Name of the provider ("bedrock", "gcp", "azure")
            **kwargs: Provider-specific configuration
            
        Returns:
            Configured provider instance
        """
        # Default to bedrock for backward compatibility
        provider_name = provider_name or os.environ.get("LLM_PROVIDER", "bedrock")
        
        if provider_name not in cls._providers:
            available = ", ".join(cls._providers.keys())
            raise ValueError(f"Unknown provider: {provider_name}. Available: {available}")
        
        provider_class = cls._providers[provider_name]
        return provider_class(**kwargs)
    
    @classmethod
    def get_available_providers(cls) -> list[str]:
        """Get list of available provider names."""
        return list(cls._providers.keys())
    
    @classmethod
    def auto_detect_provider(cls) -> Optional[str]:
        """Auto-detect the best available provider based on environment."""
        # Check in order of preference
        
        # Check for Bedrock
        if (os.environ.get("AWS_REGION") and 
            os.environ.get("BEDROCK_MODEL_ID") and 
            (os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_BEARER_TOKEN_BEDROCK"))):
            return "bedrock"
        
        # Check for Azure
        if (os.environ.get("AZURE_OPENAI_ENDPOINT") and 
            os.environ.get("AZURE_OPENAI_API_KEY")):
            return "azure"
        
        # Check for GCP
        if (os.environ.get("GCP_PROJECT_ID") and 
            (os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or 
             cls._has_gcp_default_credentials())):
            return "gcp"
        
        return None
    
    @classmethod
    def _has_gcp_default_credentials(cls) -> bool:
        """Check if GCP default credentials are available."""
        try:
            from google.auth import default
            default()
            return True
        except Exception:
            return False