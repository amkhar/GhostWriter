"""AWS Bedrock provider implementation."""

from __future__ import annotations

import os
from typing import Any, Optional

from strands import Agent
from strands.models import BedrockModel

from .base import LLMProvider, ModelConfig


class BedrockProvider(LLMProvider):
    """AWS Bedrock provider implementation."""
    
    def __init__(self, aws_region: str = None, aws_access_key_id: str = None, 
                 aws_secret_access_key: str = None, aws_session_token: str = None):
        """Initialize Bedrock provider.
        
        Args:
            aws_region: AWS region for Bedrock
            aws_access_key_id: AWS access key ID
            aws_secret_access_key: AWS secret access key  
            aws_session_token: AWS session token (for temporary credentials)
        """
        self.aws_region = aws_region or os.environ.get("AWS_REGION", "us-east-1")
        self.aws_access_key_id = aws_access_key_id or os.environ.get("AWS_ACCESS_KEY_ID")
        self.aws_secret_access_key = aws_secret_access_key or os.environ.get("AWS_SECRET_ACCESS_KEY")
        self.aws_session_token = aws_session_token or os.environ.get("AWS_SESSION_TOKEN")
    
    def create_agent(self, model_config: ModelConfig, system_prompt: str, tools: list = None) -> Agent:
        """Create a Strands Agent with Bedrock model."""
        bedrock_kwargs = {
            "model_id": model_config.model_id,
            "region_name": self.aws_region,
            "max_tokens": model_config.max_tokens or 8192,
        }
        
        # Add temperature if specified
        if model_config.temperature is not None:
            bedrock_kwargs["temperature"] = model_config.temperature
        
        # Add AWS credentials if provided
        if self.aws_access_key_id and self.aws_secret_access_key:
            bedrock_kwargs["aws_access_key_id"] = self.aws_access_key_id
            bedrock_kwargs["aws_secret_access_key"] = self.aws_secret_access_key
            if self.aws_session_token:
                bedrock_kwargs["aws_session_token"] = self.aws_session_token
        
        # Add provider-specific config
        bedrock_kwargs.update(model_config.provider_config)
        
        model = BedrockModel(**bedrock_kwargs)
        
        agent_kwargs = {
            "model": model,
            "system_prompt": system_prompt,
        }
        
        if tools:
            agent_kwargs["tools"] = tools
            
        return Agent(**agent_kwargs)
    
    def get_default_model_config(self) -> ModelConfig:
        """Get default Bedrock model configuration."""
        return ModelConfig(
            model_id=os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-3-5-sonnet-20241022-v2:0"),
            region=self.aws_region,
            max_tokens=8192,
        )
    
    @property
    def provider_name(self) -> str:
        return "bedrock"
    
    def validate_config(self) -> bool:
        """Validate Bedrock configuration."""
        # Check if we have either IAM credentials or API key
        has_iam_credentials = (
            self.aws_access_key_id and self.aws_secret_access_key
        ) or os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
        
        # Check if we have required environment variables
        has_env_config = bool(os.environ.get("AWS_REGION") and os.environ.get("BEDROCK_MODEL_ID"))
        
        return has_env_config and (has_iam_credentials or self._has_iam_role())
    
    def _has_iam_role(self) -> bool:
        """Check if running with IAM role (EC2/Lambda)."""
        try:
            import boto3
            # Try to get credentials from default credential chain
            session = boto3.Session()
            credentials = session.get_credentials()
            return credentials is not None
        except Exception:
            return False